from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from .db import Database, normalize_name
from .knowledge_snapshot import KNOWLEDGE_SCHEMA_VERSION


KNOWLEDGE_DB_FILENAME = "everquestie-knowledge.sqlite3"
USER_STATE_DB_FILENAME = "everquestie-user.sqlite3"
USER_STATE_SCHEMA_VERSION = "1"

_STATE_TABLES = {"tracked_quests", "quest_progress", "observed_events"}
_USER_META_EXACT = {
    "eq_game_path",
    "allakhazam_db_mirror",
    "allakhazam_wiki_mirror",
    "map_root",
    "map_theme",
}
_USER_META_PREFIXES = ("map_binding::", "map_view::")

USER_STATE_SCHEMA = r"""
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=10000;

CREATE TABLE IF NOT EXISTS user_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracked_quests (
    quest_key TEXT PRIMARY KEY,
    entity_kind TEXT NOT NULL DEFAULT 'quest',
    entity_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    external_namespace TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    tracked_at TEXT NOT NULL,
    active_step INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_tracked_quests_name
ON tracked_quests(entity_kind, normalized_name);
CREATE INDEX IF NOT EXISTS ix_tracked_quests_external
ON tracked_quests(external_namespace, external_id);

CREATE TABLE IF NOT EXISTS quest_progress (
    quest_key TEXT NOT NULL REFERENCES tracked_quests(quest_key) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    progress_count INTEGER NOT NULL DEFAULT 0,
    complete INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    PRIMARY KEY(quest_key, step_order)
);

CREATE TABLE IF NOT EXISTS observed_events (
    id INTEGER PRIMARY KEY,
    occurred_at TEXT,
    kind TEXT NOT NULL,
    actor TEXT,
    target TEXT,
    zone TEXT,
    item TEXT,
    amount INTEGER,
    text TEXT,
    fields_json TEXT NOT NULL,
    raw TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_observed_events_kind
ON observed_events(kind);

CREATE TABLE IF NOT EXISTS user_state_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _file_uri(path: Path, *, mode: str, immutable: bool = False) -> str:
    suffix = f"?mode={mode}"
    if immutable:
        suffix += "&immutable=1"
    return path.resolve().as_uri() + suffix


def _is_user_meta(key: str) -> bool:
    return key in _USER_META_EXACT or any(key.startswith(p) for p in _USER_META_PREFIXES)


def locate_knowledge_snapshot() -> Path | None:
    """Find the finalized knowledge artifact without requiring a source checkout."""
    override = os.environ.get("EVERQUESTIE_KNOWLEDGE_DB", "").strip()
    if override:
        candidate = Path(override).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(
                f"EVERQUESTIE_KNOWLEDGE_DB does not point to a file: {candidate}"
            )
        return candidate

    candidates: list[Path] = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / KNOWLEDGE_DB_FILENAME)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / KNOWLEDGE_DB_FILENAME)

    package_root = Path(__file__).resolve().parent.parent
    candidates.extend(
        (
            package_root / KNOWLEDGE_DB_FILENAME,
            package_root / "data" / KNOWLEDGE_DB_FILENAME,
            Path(__file__).resolve().parent / "assets" / KNOWLEDGE_DB_FILENAME,
        )
    )
    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.expanduser().resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate
    return None


class RuntimeDatabase(Database):
    """Read-only packaged knowledge plus a separate writable player-state DB.

    The ordinary :class:`Database` remains the writable builder/migration database.
    RuntimeDatabase attaches a finalized snapshot using SQLite mode=ro&immutable=1,
    exposes knowledge tables through TEMP views, and keeps player state in main.
    """

    knowledge_writable = False
    runtime_split = True

    def __init__(
        self,
        knowledge_path: str | Path,
        state_path: str | Path,
        *,
        legacy_path: str | Path | None = None,
        migrate_legacy: bool = True,
    ):
        self.knowledge_path = Path(knowledge_path).expanduser().resolve()
        if not self.knowledge_path.is_file():
            raise FileNotFoundError(self.knowledge_path)
        self.state_path = Path(state_path).expanduser().resolve()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = self.knowledge_path
        self._batch_depth = 0

        self.conn = sqlite3.connect(_file_uri(self.state_path, mode="rwc"), uri=True)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.executescript(USER_STATE_SCHEMA)
            self._validate_state_schema()
            self.conn.execute(
                "ATTACH DATABASE ? AS knowledge",
                (_file_uri(self.knowledge_path, mode="ro", immutable=True),),
            )
            self._validate_knowledge_snapshot()
            self._install_knowledge_views()
            self.fts_available = self._knowledge_table_exists("entity_fts")
            self.conn.commit()

            legacy = Path(legacy_path).expanduser().resolve() if legacy_path else None
            migration_done = self.conn.execute(
                "SELECT value FROM user_state_meta WHERE key='legacy_migration_complete'"
            ).fetchone()
            if (
                migrate_legacy
                and migration_done is None
                and legacy is not None
                and legacy.is_file()
                and legacy not in {self.state_path, self.knowledge_path}
            ):
                self._migrate_legacy_state(legacy)
        except Exception:
            self.conn.close()
            raise

    def _validate_state_schema(self) -> None:
        row = self.conn.execute(
            "SELECT value FROM user_state_meta WHERE key='schema_version'"
        ).fetchone()
        if row is not None and str(row["value"]) != USER_STATE_SCHEMA_VERSION:
            raise ValueError(
                "Incompatible EverQuestie user-state schema: "
                f"expected {USER_STATE_SCHEMA_VERSION}, found {row['value']}"
            )
        if row is None:
            self.conn.execute(
                "INSERT INTO user_state_meta(key,value) VALUES('schema_version',?)",
                (USER_STATE_SCHEMA_VERSION,),
            )

    def _knowledge_table_exists(self, name: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM knowledge.sqlite_master "
            "WHERE type IN ('table','view') AND name=?",
            (name,),
        ).fetchone() is not None

    def _validate_knowledge_snapshot(self) -> None:
        if not self._knowledge_table_exists("app_meta"):
            raise ValueError("Knowledge DB is missing app_meta")
        role = self.conn.execute(
            "SELECT value FROM knowledge.app_meta WHERE key='database_role'"
        ).fetchone()
        if role is None or str(role["value"]) != "knowledge_snapshot":
            raise ValueError("Knowledge DB is not a finalized knowledge_snapshot")
        schema = self.conn.execute(
            "SELECT value FROM knowledge.app_meta WHERE key='knowledge_schema_version'"
        ).fetchone()
        found = str(schema["value"]) if schema is not None else ""
        if found != KNOWLEDGE_SCHEMA_VERSION:
            raise ValueError(
                "Incompatible EverQuestie knowledge schema: "
                f"expected {KNOWLEDGE_SCHEMA_VERSION}, found {found or 'missing'}"
            )
        quick = str(self.conn.execute("PRAGMA knowledge.quick_check").fetchone()[0])
        if quick != "ok":
            raise ValueError(f"Knowledge DB quick_check failed: {quick}")

    def _install_knowledge_views(self) -> None:
        rows = self.conn.execute(
            "SELECT name FROM knowledge.sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for row in rows:
            name = str(row["name"])
            if name in _STATE_TABLES or name == "app_meta":
                continue
            ident = _quote_identifier(name)
            self.conn.execute(
                f"CREATE TEMP VIEW IF NOT EXISTS {ident} AS SELECT * FROM knowledge.{ident}"
            )
        self.conn.execute(
            """
            CREATE TEMP VIEW IF NOT EXISTS app_meta AS
            SELECT key,value FROM user_meta
            UNION ALL
            SELECT k.key,k.value FROM knowledge.app_meta k
            WHERE NOT EXISTS (SELECT 1 FROM user_meta u WHERE u.key=k.key)
            """
        )

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM user_meta WHERE key=?", (key,)).fetchone()
        if row is not None:
            return str(row["value"])
        row = self.conn.execute(
            "SELECT value FROM knowledge.app_meta WHERE key=?", (key,)
        ).fetchone()
        return str(row["value"]) if row is not None else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO user_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self._commit()

    @staticmethod
    def _external_priority(namespace: str) -> tuple[int, str]:
        folded = namespace.casefold()
        if folded.startswith("eqclient:"):
            return 0, folded
        if folded.startswith("everquestie:"):
            return 1, folded
        if folded.startswith("eqemu:"):
            return 2, folded
        if folded.startswith("allakhazam:"):
            return 4, folded
        return 3, folded

    @classmethod
    def _identity_from_connection(
        cls, conn: sqlite3.Connection, entity_id: int
    ) -> dict[str, str] | None:
        row = conn.execute(
            "SELECT id,kind,name,normalized_name,external_id FROM entities WHERE id=?",
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        ids = []
        try:
            ids = conn.execute(
                "SELECT namespace,external_id FROM entity_external_ids WHERE entity_id=?",
                (entity_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            pass
        namespace = ""
        external_id = ""
        if ids:
            chosen = min(ids, key=lambda x: cls._external_priority(str(x["namespace"])))
            namespace = str(chosen["namespace"])
            external_id = str(chosen["external_id"])
        elif str(row["external_id"] or ""):
            namespace = f"legacy:{row['kind']}"
            external_id = str(row["external_id"])
        kind = str(row["kind"])
        name = str(row["name"])
        normalized = str(row["normalized_name"] or normalize_name(name))
        key = (
            f"x|{namespace}|{external_id}"
            if namespace and external_id
            else f"n|{kind}|{normalized}"
        )
        return {
            "quest_key": key,
            "entity_kind": kind,
            "entity_name": name,
            "normalized_name": normalized,
            "external_namespace": namespace,
            "external_id": external_id,
        }

    def _identity_for_entity(self, entity_id: int) -> dict[str, str]:
        identity = self._identity_from_connection(self.conn, entity_id)
        if identity is None:
            raise KeyError(f"Unknown knowledge entity id {entity_id}")
        return identity

    def _resolve_state_identity(self, state: sqlite3.Row):
        namespace = str(state["external_namespace"] or "")
        external_id = str(state["external_id"] or "")
        if namespace and external_id:
            if namespace.startswith("legacy:"):
                found = self.entity_by_external_id(str(state["entity_kind"]), external_id)
            else:
                found = self.entity_by_namespaced_external_id(namespace, external_id)
            if found is not None:
                return found
        rows = self.conn.execute(
            "SELECT * FROM entities WHERE kind=? AND normalized_name=? ORDER BY id LIMIT 2",
            (str(state["entity_kind"]), str(state["normalized_name"])),
        ).fetchall()
        return rows[0] if len(rows) == 1 else None

    def _tracked_key_for_entity(self, entity_id: int) -> str | None:
        for state in self.conn.execute(
            "SELECT * FROM tracked_quests ORDER BY tracked_at,quest_key"
        ).fetchall():
            entity = self._resolve_state_identity(state)
            if entity is not None and int(entity["id"]) == int(entity_id):
                return str(state["quest_key"])
        return None

    def track_quest(self, quest_id: int) -> None:
        if self._tracked_key_for_entity(quest_id) is not None:
            self._recompute_active_step(quest_id)
            self._commit()
            return
        i = self._identity_for_entity(quest_id)
        self.conn.execute(
            """
            INSERT INTO tracked_quests(
                quest_key,entity_kind,entity_name,normalized_name,
                external_namespace,external_id,tracked_at,active_step
            ) VALUES(?,?,?,?,?,?,?,1)
            ON CONFLICT(quest_key) DO NOTHING
            """,
            (
                i["quest_key"], i["entity_kind"], i["entity_name"], i["normalized_name"],
                i["external_namespace"], i["external_id"],
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self._recompute_active_step(quest_id)
        self._commit()

    def untrack_quest(self, quest_id: int) -> None:
        key = self._tracked_key_for_entity(quest_id)
        if key is not None:
            self.conn.execute("DELETE FROM tracked_quests WHERE quest_key=?", (key,))
            self._commit()

    def tracked_quests(self):
        result: list[dict[str, Any]] = []
        for state in self.conn.execute(
            "SELECT * FROM tracked_quests ORDER BY tracked_at,quest_key"
        ).fetchall():
            entity = self._resolve_state_identity(state)
            if entity is None:
                continue
            result.append(
                {
                    "id": int(entity["id"]),
                    "name": str(entity["name"]),
                    "zone": entity["zone"],
                    "source_url": entity["source_url"],
                    "active_step": int(state["active_step"]),
                    "tracked_at": str(state["tracked_at"]),
                    "quest_key": str(state["quest_key"]),
                }
            )
        return result

    def quest_steps(self, quest_id: int):
        key = self._tracked_key_for_entity(quest_id)
        progress = {}
        if key is not None:
            progress = {
                int(r["step_order"]): r
                for r in self.conn.execute(
                    "SELECT * FROM quest_progress WHERE quest_key=?", (key,)
                ).fetchall()
            }
        out = []
        for row in self.conn.execute(
            "SELECT * FROM quest_steps WHERE quest_entity_id=? ORDER BY step_order",
            (quest_id,),
        ).fetchall():
            step = dict(row)
            state = progress.get(int(row["step_order"]))
            step["progress_count"] = int(state["progress_count"]) if state else 0
            step["complete"] = int(state["complete"]) if state else 0
            if state:
                step["completed_at"] = state["completed_at"]
            out.append(step)
        return out

    def _recompute_active_step(self, quest_id: int) -> None:
        key = self._tracked_key_for_entity(quest_id)
        if key is None:
            return
        steps = self.quest_steps(quest_id)
        pending = next((s for s in steps if not int(s["complete"])), None)
        active = (
            int(pending["step_order"])
            if pending is not None
            else max((int(s["step_order"]) for s in steps), default=0) + 1
        )
        self.conn.execute(
            "UPDATE tracked_quests SET active_step=? WHERE quest_key=?", (active, key)
        )

    def set_step_progress(
        self, quest_id: int, step_order: int, count: int, complete: bool
    ) -> None:
        key = self._tracked_key_for_entity(quest_id)
        if key is None:
            self.track_quest(quest_id)
            key = self._tracked_key_for_entity(quest_id)
        if key is None:
            raise KeyError(f"Unable to persist progress for quest entity {quest_id}")
        now = datetime.now().isoformat(timespec="seconds") if complete else None
        self.conn.execute(
            """
            INSERT INTO quest_progress(
                quest_key,step_order,progress_count,complete,completed_at
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(quest_key,step_order) DO UPDATE SET
                progress_count=MAX(quest_progress.progress_count,excluded.progress_count),
                complete=MAX(quest_progress.complete,excluded.complete),
                completed_at=CASE WHEN excluded.complete=1
                    THEN COALESCE(quest_progress.completed_at,excluded.completed_at)
                    ELSE quest_progress.completed_at END
            """,
            (key, step_order, count, int(complete), now),
        )
        self._recompute_active_step(quest_id)
        self._commit()

    def reset_quest_progress(self, quest_id: int) -> None:
        key = self._tracked_key_for_entity(quest_id)
        if key is not None:
            self.conn.execute("DELETE FROM quest_progress WHERE quest_key=?", (key,))
            self._recompute_active_step(quest_id)
            self._commit()

    def is_quest_tracked(self, quest_id: int) -> bool:
        return self._tracked_key_for_entity(quest_id) is not None

    def search_entities_fts(
        self,
        term: str,
        kind: str | None = None,
        *,
        limit: int = 250,
        offset: int = 0,
    ):
        term = term.strip()
        if not term or not self.fts_available or self.get_meta("fts_dirty", "1") == "1":
            return self.search_entities(term, kind, limit=limit, offset=offset)
        query = self._fts_query(term)
        if not query:
            return self.search_entities(term, kind, limit=limit, offset=offset)
        safe_limit = max(1, min(int(limit), 5000))
        safe_offset = max(0, int(offset))
        try:
            return self.conn.execute(
                """
                SELECT e.*,sp.title AS source_title,
                       bm25(entity_fts,3.0,1.5,0.5) AS rank
                FROM knowledge.entity_fts
                JOIN entities e ON e.id=CAST(entity_fts.entity_id AS INTEGER)
                LEFT JOIN source_pages sp ON sp.id=e.source_page_id
                WHERE entity_fts MATCH ? AND (? IS NULL OR e.kind=?)
                ORDER BY rank,e.kind,e.name LIMIT ? OFFSET ?
                """,
                (query, kind, kind, safe_limit, safe_offset),
            ).fetchall()
        except sqlite3.OperationalError:
            return self.search_entities(term, kind, limit=limit, offset=offset)

    def database_diagnostics(self) -> dict[str, Any]:
        knowledge_integrity = str(
            self.conn.execute("PRAGMA knowledge.integrity_check").fetchone()[0]
        )
        state_integrity = str(self.conn.execute("PRAGMA main.integrity_check").fetchone()[0])
        counts = {
            "entities": int(self.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]),
            "relationships": int(self.conn.execute("SELECT COUNT(*) FROM entity_relationships").fetchone()[0]),
            "locations": int(self.conn.execute("SELECT COUNT(*) FROM entity_locations").fetchone()[0]),
            "sources": int(self.conn.execute("SELECT COUNT(*) FROM source_pages").fetchone()[0]),
            "aliases": int(self.conn.execute("SELECT COUNT(*) FROM entity_aliases").fetchone()[0]),
            "details": int(self.conn.execute("SELECT COUNT(*) FROM entity_details").fetchone()[0]),
            "tracked_quests": int(self.conn.execute("SELECT COUNT(*) FROM tracked_quests").fetchone()[0]),
            "observed_events": int(self.conn.execute("SELECT COUNT(*) FROM observed_events").fetchone()[0]),
        }
        fts_rows = 0
        if self.fts_available:
            try:
                fts_rows = int(
                    self.conn.execute("SELECT COUNT(*) FROM knowledge.entity_fts").fetchone()[0]
                )
            except sqlite3.OperationalError:
                pass
        return {
            "path": str(self.knowledge_path),
            "state_path": str(self.state_path),
            "integrity": knowledge_integrity,
            "state_integrity": state_integrity,
            "runtime_split": True,
            "knowledge_read_only": True,
            "knowledge_schema_version": self.get_meta("knowledge_schema_version", ""),
            "knowledge_snapshot_version": self.get_meta("knowledge_snapshot_version", ""),
            "fts_available": bool(self.fts_available),
            "fts_rows": fts_rows,
            "fts_last_rebuild": self.get_meta("fts_last_rebuild", ""),
            "fts_dirty": self.get_meta("fts_dirty", "1") == "1",
            "counts": counts,
            "support": self.support_table_counts(),
        }

    def _migrate_legacy_state(self, legacy_path: Path) -> None:
        legacy = sqlite3.connect(_file_uri(legacy_path, mode="ro"), uri=True)
        legacy.row_factory = sqlite3.Row
        migrated: dict[int, str] = {}
        try:
            tables = {
                str(r["name"])
                for r in legacy.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            with self.batch():
                if "app_meta" in tables:
                    for row in legacy.execute("SELECT key,value FROM app_meta"):
                        key = str(row["key"])
                        if _is_user_meta(key):
                            self.conn.execute(
                                "INSERT INTO user_meta(key,value) VALUES(?,?) "
                                "ON CONFLICT(key) DO NOTHING",
                                (key, str(row["value"])),
                            )
                if "tracked_quests" in tables and "entities" in tables:
                    for row in legacy.execute(
                        "SELECT quest_entity_id,tracked_at,active_step FROM tracked_quests"
                    ):
                        old_id = int(row["quest_entity_id"])
                        i = self._identity_from_connection(legacy, old_id)
                        if i is None:
                            continue
                        migrated[old_id] = i["quest_key"]
                        self.conn.execute(
                            """
                            INSERT INTO tracked_quests(
                                quest_key,entity_kind,entity_name,normalized_name,
                                external_namespace,external_id,tracked_at,active_step
                            ) VALUES(?,?,?,?,?,?,?,?)
                            ON CONFLICT(quest_key) DO NOTHING
                            """,
                            (
                                i["quest_key"], i["entity_kind"], i["entity_name"],
                                i["normalized_name"], i["external_namespace"], i["external_id"],
                                str(row["tracked_at"]), int(row["active_step"]),
                            ),
                        )
                if "quest_progress" in tables:
                    for row in legacy.execute("SELECT * FROM quest_progress"):
                        key = migrated.get(int(row["quest_entity_id"]))
                        if key is None:
                            continue
                        self.conn.execute(
                            """
                            INSERT INTO quest_progress(
                                quest_key,step_order,progress_count,complete,completed_at
                            ) VALUES(?,?,?,?,?)
                            ON CONFLICT(quest_key,step_order) DO UPDATE SET
                                progress_count=MAX(quest_progress.progress_count,excluded.progress_count),
                                complete=MAX(quest_progress.complete,excluded.complete),
                                completed_at=COALESCE(quest_progress.completed_at,excluded.completed_at)
                            """,
                            (
                                key, int(row["step_order"]), int(row["progress_count"]),
                                int(row["complete"]), row["completed_at"],
                            ),
                        )
                if "observed_events" in tables:
                    rows = legacy.execute(
                        "SELECT occurred_at,kind,actor,target,zone,item,amount,text,fields_json,raw "
                        "FROM observed_events ORDER BY id"
                    ).fetchall()
                    self.conn.executemany(
                        """
                        INSERT INTO observed_events(
                            occurred_at,kind,actor,target,zone,item,amount,text,fields_json,raw
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)
                        """,
                        [tuple(row) for row in rows],
                    )
                now = datetime.now().isoformat(timespec="seconds")
                for key, value in (
                    ("legacy_migrated_from", str(legacy_path)),
                    ("legacy_migrated_at", now),
                    ("legacy_migration_complete", "1"),
                ):
                    self.conn.execute(
                        "INSERT INTO user_state_meta(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value),
                    )
        finally:
            legacy.close()

    def close(self) -> None:
        if self._batch_depth:
            self.conn.commit()
            self._batch_depth = 0
        self.conn.close()


def open_application_database(legacy_path: str | Path) -> Database:
    """Select packaged split runtime or the source-checkout builder DB fallback."""
    legacy = Path(legacy_path).expanduser().resolve()
    knowledge = locate_knowledge_snapshot()
    if knowledge is None:
        if getattr(sys, "frozen", False):
            raise FileNotFoundError(
                f"Packaged EverQuestie is missing {KNOWLEDGE_DB_FILENAME}"
            )
        return Database(legacy)
    state_override = os.environ.get("EVERQUESTIE_USER_DB", "").strip()
    state = (
        Path(state_override).expanduser()
        if state_override
        else legacy.parent / USER_STATE_DB_FILENAME
    )
    return RuntimeDatabase(knowledge, state, legacy_path=legacy, migrate_legacy=True)


def _install_runtime_adapters() -> None:
    """Skip builder-only map schema creation against a read-only runtime snapshot."""
    from .map_catalog import MapCatalog

    original = MapCatalog.ensure_schema
    if getattr(original, "_everquestie_runtime_adapter", False):
        return

    def ensure_schema(self):
        if getattr(self.db, "knowledge_writable", True):
            return original(self)
        return None

    ensure_schema._everquestie_runtime_adapter = True  # type: ignore[attr-defined]
    MapCatalog.ensure_schema = ensure_schema


def main() -> None:
    from . import app as app_module

    _install_runtime_adapters()
    app_module.Database = open_application_database
    app_module.main()
