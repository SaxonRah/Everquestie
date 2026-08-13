from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .events import Event


SCHEMA = r"""
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=10000;

CREATE TABLE IF NOT EXISTS source_pages (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    source_name TEXT NOT NULL DEFAULT 'Allakhazam',
    source_kind TEXT NOT NULL DEFAULT 'local_mirror',
    source_key TEXT NOT NULL DEFAULT '',
    source_version TEXT NOT NULL DEFAULT '',
    local_path TEXT NOT NULL DEFAULT '',
    fetched_at TEXT,
    title TEXT,
    entity_type TEXT,
    imported_at TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    plain_text TEXT NOT NULL,
    raw_html TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE SET NULL,
    source_url TEXT,
    external_id TEXT NOT NULL DEFAULT '',
    zone TEXT,
    level_min INTEGER,
    level_max INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    data_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(kind, normalized_name, external_id)
);

CREATE INDEX IF NOT EXISTS ix_entities_name
ON entities(normalized_name);
CREATE INDEX IF NOT EXISTS ix_entities_external
ON entities(kind, external_id);

CREATE TABLE IF NOT EXISTS entity_sources (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    source_page_id INTEGER NOT NULL REFERENCES source_pages(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'evidence',
    confidence REAL,
    PRIMARY KEY(entity_id, source_page_id, role)
);

CREATE INDEX IF NOT EXISTS ix_entity_sources_entity
ON entity_sources(entity_id);
CREATE INDEX IF NOT EXISTS ix_entity_sources_source
ON entity_sources(source_page_id);

CREATE TABLE IF NOT EXISTS entity_external_ids (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE SET NULL,
    PRIMARY KEY(namespace, external_id),
    UNIQUE(entity_id, namespace, external_id)
);

CREATE INDEX IF NOT EXISTS ix_entity_external_ids_entity
ON entity_external_ids(entity_id);

CREATE TABLE IF NOT EXISTS entity_aliases (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    alias_type TEXT NOT NULL DEFAULT 'source',
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE CASCADE,
    UNIQUE(entity_id, normalized_alias, alias_type, source_page_id)
);

CREATE INDEX IF NOT EXISTS ix_entity_aliases_normalized
ON entity_aliases(normalized_alias);

CREATE TABLE IF NOT EXISTS entity_relationships (
    id INTEGER PRIMARY KEY,
    source_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation TEXT NOT NULL,
    quantity INTEGER,
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE CASCADE,
    evidence TEXT NOT NULL DEFAULT '',
    data_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(source_entity_id, target_entity_id, relation, source_page_id)
);

CREATE INDEX IF NOT EXISTS ix_relationships_source
ON entity_relationships(source_entity_id, relation);
CREATE INDEX IF NOT EXISTS ix_relationships_target
ON entity_relationships(target_entity_id, relation);

CREATE TABLE IF NOT EXISTS entity_locations (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    zone_entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    y REAL,
    x REAL,
    z REAL,
    label TEXT NOT NULL DEFAULT '',
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE CASCADE,
    evidence TEXT NOT NULL DEFAULT '',
    data_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS ix_locations_entity
ON entity_locations(entity_id);

CREATE TABLE IF NOT EXISTS quest_steps (
    id INTEGER PRIMARY KEY,
    quest_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    description TEXT NOT NULL,
    zone TEXT,
    match_json TEXT NOT NULL DEFAULT '{}',
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE CASCADE,
    UNIQUE(quest_entity_id, step_order)
);

CREATE TABLE IF NOT EXISTS tracked_quests (
    quest_entity_id INTEGER PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    tracked_at TEXT NOT NULL,
    active_step INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS quest_progress (
    quest_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    progress_count INTEGER NOT NULL DEFAULT 0,
    complete INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    PRIMARY KEY(quest_entity_id, step_order)
);

CREATE TABLE IF NOT EXISTS entity_details (
    entity_id INTEGER PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE SET NULL,
    detail_format TEXT NOT NULL DEFAULT 'text',
    detail_text TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_entity_details_source
ON entity_details(source_page_id);

CREATE TABLE IF NOT EXISTS skill_caps (
    class_id INTEGER NOT NULL,
    skill_id INTEGER NOT NULL,
    level INTEGER NOT NULL,
    cap INTEGER NOT NULL,
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE CASCADE,
    PRIMARY KEY(class_id, skill_id, level)
);

CREATE TABLE IF NOT EXISTS base_stats (
    level INTEGER NOT NULL,
    class_id INTEGER NOT NULL,
    hp REAL,
    mana REAL,
    endurance REAL,
    hp_regen REAL,
    mana_regen REAL,
    endurance_regen REAL,
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE CASCADE,
    PRIMARY KEY(level, class_id)
);

CREATE TABLE IF NOT EXISTS ac_mitigation (
    class_id INTEGER NOT NULL,
    level INTEGER NOT NULL,
    ac_cap REAL,
    soft_cap_multiplier REAL,
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE CASCADE,
    PRIMARY KEY(class_id, level)
);

CREATE TABLE IF NOT EXISTS spell_stacking (
    spell_id INTEGER PRIMARY KEY,
    stacking_group INTEGER,
    rank INTEGER,
    stacking_type INTEGER,
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE CASCADE
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

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def normalize_name(name: str) -> str:
    return " ".join(name.casefold().split())


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._batch_depth = 0
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.fts_available = self._ensure_fts()
        self._commit()

    def _migrate(self) -> None:
        """Additive migrations while preserving existing ~/.eqquest databases."""
        # v0.9 generalizes source_pages into a multi-source provenance record while
        # retaining the old table name so existing Allakhazam imports stay valid.
        source_cols = {
            r["name"] for r in self.conn.execute("PRAGMA table_info(source_pages)").fetchall()
        }
        additions = {
            "source_kind": "TEXT NOT NULL DEFAULT 'local_mirror'",
            "source_key": "TEXT NOT NULL DEFAULT ''",
            "source_version": "TEXT NOT NULL DEFAULT ''",
            "local_path": "TEXT NOT NULL DEFAULT ''",
            "fetched_at": "TEXT",
        }
        for name, ddl in additions.items():
            if name not in source_cols:
                self.conn.execute(f"ALTER TABLE source_pages ADD COLUMN {name} {ddl}")

        step_cols = {
            r["name"] for r in self.conn.execute("PRAGMA table_info(quest_steps)").fetchall()
        }
        if "source_page_id" not in step_cols:
            self.conn.execute(
                "ALTER TABLE quest_steps ADD COLUMN source_page_id INTEGER REFERENCES source_pages(id) ON DELETE CASCADE"
            )

        # Older databases constrained entity kinds to quest/npc/item/zone.  EverQuestie
        # now owns a general knowledge DB, so rebuild only this table without the CHECK.
        sql_row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='entities'"
        ).fetchone()
        entity_sql = (sql_row["sql"] if sql_row else "") or ""
        if "CHECK(kind IN" in entity_sql:
            self._migrate_entities_without_kind_check()

        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS entity_sources (
                entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                source_page_id INTEGER NOT NULL REFERENCES source_pages(id) ON DELETE CASCADE,
                role TEXT NOT NULL DEFAULT 'evidence',
                confidence REAL,
                PRIMARY KEY(entity_id, source_page_id, role)
            );
            CREATE INDEX IF NOT EXISTS ix_entity_sources_entity
            ON entity_sources(entity_id);
            CREATE INDEX IF NOT EXISTS ix_entity_sources_source
            ON entity_sources(source_page_id);
            CREATE TABLE IF NOT EXISTS entity_external_ids (
                entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                namespace TEXT NOT NULL,
                external_id TEXT NOT NULL,
                source_page_id INTEGER REFERENCES source_pages(id) ON DELETE SET NULL,
                PRIMARY KEY(namespace, external_id),
                UNIQUE(entity_id, namespace, external_id)
            );
            CREATE INDEX IF NOT EXISTS ix_entity_external_ids_entity
            ON entity_external_ids(entity_id);
            """
        )

        # Backfill primary-source links for rows created before entity_sources existed.
        self.conn.execute(
            """
            INSERT OR IGNORE INTO entity_sources(entity_id, source_page_id, role)
            SELECT id, source_page_id, 'primary'
            FROM entities
            WHERE source_page_id IS NOT NULL
            """
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO entity_external_ids(entity_id, namespace, external_id, source_page_id)
            SELECT id, 'allakhazam:' || kind, external_id, source_page_id
            FROM entities
            WHERE external_id<>'' AND source_url LIKE '%everquest.allakhazam.com/%'
            """
        )

    def _ensure_fts(self) -> bool:
        """Create the local full-text index when SQLite was built with FTS5.

        FTS is an acceleration/index layer only.  EverQuestie always retains a
        LIKE-based fallback so a Python build without FTS5 can still run.
        """
        try:
            self.conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS entity_fts USING fts5(
                    entity_id UNINDEXED,
                    kind UNINDEXED,
                    name,
                    aliases,
                    body,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
            # FTS is a derived index.  Mark it dirty whenever searchable source
            # tables change so Search never silently trusts a stale populated index.
            for table in ("entities", "entity_aliases", "entity_details", "quest_steps"):
                for action in ("INSERT", "UPDATE", "DELETE"):
                    trigger = f"eq_fts_dirty_{table}_{action.lower()}"
                    self.conn.execute(
                        f"""
                        CREATE TRIGGER IF NOT EXISTS {trigger}
                        AFTER {action} ON {table}
                        BEGIN
                          INSERT INTO app_meta(key, value) VALUES('fts_dirty', '1')
                          ON CONFLICT(key) DO UPDATE SET value='1';
                        END
                        """
                    )
            return True
        except sqlite3.OperationalError:
            return False

    def _migrate_entities_without_kind_check(self) -> None:
        self.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            self.conn.executescript(
                """
                CREATE TABLE entities_v09 (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE SET NULL,
                    source_url TEXT,
                    external_id TEXT NOT NULL DEFAULT '',
                    zone TEXT,
                    level_min INTEGER,
                    level_max INTEGER,
                    notes TEXT NOT NULL DEFAULT '',
                    data_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(kind, normalized_name, external_id)
                );
                INSERT INTO entities_v09(
                    id, kind, name, normalized_name, source_page_id, source_url,
                    external_id, zone, level_min, level_max, notes, data_json
                )
                SELECT id, kind, name, normalized_name, source_page_id, source_url,
                       external_id, zone, level_min, level_max, notes, data_json
                FROM entities;
                DROP TABLE entities;
                ALTER TABLE entities_v09 RENAME TO entities;
                CREATE INDEX IF NOT EXISTS ix_entities_name ON entities(normalized_name);
                CREATE INDEX IF NOT EXISTS ix_entities_external ON entities(kind, external_id);
                """
            )
        finally:
            self.conn.execute("PRAGMA foreign_keys=ON")

    def _commit(self) -> None:
        if self._batch_depth == 0:
            self.conn.commit()

    @contextmanager
    def batch(self):
        """Group large mirror/client imports into one SQLite transaction.

        The outermost batch owns the commit/rollback.  Nested helpers can safely use
        ``batch()`` without accidentally committing a transaction that has already
        failed.
        """
        outermost = self._batch_depth == 0
        self._batch_depth += 1
        try:
            yield self
        except Exception:
            if outermost:
                self.conn.rollback()
            raise
        else:
            if outermost:
                self.conn.commit()
        finally:
            self._batch_depth -= 1

    def close(self) -> None:
        if self._batch_depth:
            self.conn.commit()
            self._batch_depth = 0
        self.conn.close()

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row is not None else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO app_meta(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, str(value)),
        )
        self._commit()


    def add_event(self, e: Event) -> None:
        self.conn.execute(
            """
            INSERT INTO observed_events(
                occurred_at, kind, actor, target, zone, item,
                amount, text, fields_json, raw
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                e.timestamp.isoformat() if e.timestamp else None,
                e.kind,
                e.actor,
                e.target,
                e.zone,
                e.item,
                e.amount,
                e.text,
                json.dumps(e.fields, ensure_ascii=False),
                e.raw,
            ),
        )
        self._commit()

    def upsert_source_page(
        self,
        *,
        url: str,
        title: str,
        entity_type: str | None,
        sha256: str,
        plain_text: str,
        raw_html: str,
        source_name: str = "Allakhazam",
        source_kind: str = "local_mirror",
        source_key: str = "",
        source_version: str = "",
        local_path: str = "",
        fetched_at: str | None = None,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO source_pages(
                url, source_name, source_kind, source_key, source_version,
                local_path, fetched_at, title, entity_type, imported_at,
                sha256, plain_text, raw_html
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(url) DO UPDATE SET
                source_name=excluded.source_name,
                source_kind=excluded.source_kind,
                source_key=CASE WHEN excluded.source_key<>'' THEN excluded.source_key ELSE source_pages.source_key END,
                source_version=CASE WHEN excluded.source_version<>'' THEN excluded.source_version ELSE source_pages.source_version END,
                local_path=CASE WHEN excluded.local_path<>'' THEN excluded.local_path ELSE source_pages.local_path END,
                fetched_at=COALESCE(excluded.fetched_at, source_pages.fetched_at),
                title=excluded.title,
                entity_type=excluded.entity_type,
                imported_at=excluded.imported_at,
                sha256=excluded.sha256,
                plain_text=excluded.plain_text,
                raw_html=excluded.raw_html
            """,
            (
                url, source_name, source_kind, source_key, source_version,
                local_path, fetched_at, title, entity_type, now,
                sha256, plain_text, raw_html,
            ),
        )
        self._commit()
        row = self.conn.execute(
            "SELECT id FROM source_pages WHERE url=?", (url,)
        ).fetchone()
        return int(row["id"])

    def link_entity_source(
        self,
        entity_id: int,
        source_page_id: int,
        *,
        role: str = "evidence",
        confidence: float | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO entity_sources(entity_id, source_page_id, role, confidence)
            VALUES(?,?,?,?)
            ON CONFLICT(entity_id, source_page_id, role) DO UPDATE SET
                confidence=COALESCE(excluded.confidence, entity_sources.confidence)
            """,
            (entity_id, source_page_id, role, confidence),
        )
        self._commit()

    def sources_for_entity(self, entity_id: int):
        return self.conn.execute(
            """
            SELECT sp.*, es.role, es.confidence
            FROM entity_sources es
            JOIN source_pages sp ON sp.id=es.source_page_id
            WHERE es.entity_id=?
            ORDER BY CASE es.role WHEN 'primary' THEN 0 ELSE 1 END,
                     sp.source_name, sp.title, sp.id
            """,
            (entity_id,),
        ).fetchall()

    def source_stats(self):
        return self.conn.execute(
            """
            SELECT source_name, source_kind, COUNT(*) AS records,
                   COUNT(DISTINCT entity_type) AS entity_types
            FROM source_pages
            GROUP BY source_name, source_kind
            ORDER BY source_name, source_kind
            """
        ).fetchall()

    def source_pages(self):
        return self.conn.execute("SELECT * FROM source_pages ORDER BY id").fetchall()

    def entity_by_external_id(self, kind: str, external_id: str | None):
        if not external_id:
            return None
        return self.conn.execute(
            """
            SELECT * FROM entities
            WHERE kind=? AND external_id=?
            ORDER BY CASE WHEN source_page_id IS NULL THEN 1 ELSE 0 END, id
            LIMIT 1
            """,
            (kind, external_id),
        ).fetchone()

    def entity_by_namespaced_external_id(self, namespace: str, external_id: str | None):
        if not external_id:
            return None
        return self.conn.execute(
            """
            SELECT e.*
            FROM entity_external_ids x
            JOIN entities e ON e.id=x.entity_id
            WHERE x.namespace=? AND x.external_id=?
            LIMIT 1
            """,
            (namespace, str(external_id)),
        ).fetchone()

    def add_external_id(
        self,
        entity_id: int,
        namespace: str,
        external_id: str,
        *,
        source_page_id: int | None = None,
    ) -> None:
        if not namespace or not external_id:
            return
        self.conn.execute(
            """
            INSERT INTO entity_external_ids(entity_id, namespace, external_id, source_page_id)
            VALUES(?,?,?,?)
            ON CONFLICT(namespace, external_id) DO UPDATE SET
                entity_id=excluded.entity_id,
                source_page_id=COALESCE(excluded.source_page_id, entity_external_ids.source_page_id)
            """,
            (entity_id, namespace, str(external_id), source_page_id),
        )
        self._commit()

    def external_ids_for_entity(self, entity_id: int):
        return self.conn.execute(
            "SELECT * FROM entity_external_ids WHERE entity_id=? ORDER BY namespace, external_id",
            (entity_id,),
        ).fetchall()

    def upsert_entity(
        self,
        *,
        kind: str,
        name: str,
        source_page_id: int | None = None,
        source_url: str | None = None,
        external_id: str | None = None,
        external_namespace: str | None = None,
        merge_by_name: bool = False,
        zone: str | None = None,
        level_min: int | None = None,
        level_max: int | None = None,
        notes: str = "",
        data: dict[str, Any] | None = None,
    ) -> int:
        norm = normalize_name(name)
        ext = external_id or ""
        if not external_namespace and source_url:
            if "everquest.allakhazam.com" in source_url:
                external_namespace = f"allakhazam:{kind}"
            elif source_url.startswith("eqclient://"):
                external_namespace = f"eqclient:{kind}"
        payload = json.dumps(data or {}, ensure_ascii=False)

        # Allakhazam numeric IDs are stronger identity than display names.  This is
        # important when a user imports a page as "Summon the Spirits" while the
        # source title is "Gubjak #1: Summon the Spirits".
        existing = None
        if ext and external_namespace:
            existing = self.entity_by_namespaced_external_id(external_namespace, ext)
        if existing is None and ext and (not external_namespace or external_namespace.startswith("allakhazam:")):
            # Legacy compatibility: pre-v0.9 Allakhazam IDs lived directly on entities.
            existing = self.entity_by_external_id(kind, ext)
        if existing is None and merge_by_name:
            existing = self.conn.execute(
                "SELECT * FROM entities WHERE kind=? AND normalized_name=? ORDER BY id LIMIT 1",
                (kind, norm),
            ).fetchone()
        if existing is not None:
            entity_id = int(existing["id"])
            old_data = json.loads(existing["data_json"] or "{}")
            if data:
                old_data.update(data)
            self.conn.execute(
                """
                UPDATE entities SET
                    name=?, normalized_name=?,
                    source_page_id=COALESCE(?, source_page_id),
                    source_url=COALESCE(?, source_url),
                    zone=COALESCE(?, zone),
                    level_min=COALESCE(?, level_min),
                    level_max=COALESCE(?, level_max),
                    notes=CASE WHEN ?<>'' THEN ? ELSE notes END,
                    data_json=?
                WHERE id=?
                """,
                (
                    name, norm, source_page_id, source_url, zone,
                    level_min, level_max, notes, notes,
                    json.dumps(old_data, ensure_ascii=False), entity_id,
                ),
            )
            self._commit()
            if source_page_id is not None:
                self.link_entity_source(entity_id, source_page_id, role="primary")
            if external_namespace and ext:
                self.add_external_id(entity_id, external_namespace, ext, source_page_id=source_page_id)
            return entity_id

        self.conn.execute(
            """
            INSERT INTO entities(
                kind, name, normalized_name, source_page_id,
                source_url, external_id, zone, level_min, level_max,
                notes, data_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT DO UPDATE SET
                name=excluded.name,
                source_page_id=COALESCE(excluded.source_page_id, entities.source_page_id),
                source_url=COALESCE(excluded.source_url, entities.source_url),
                zone=COALESCE(excluded.zone, entities.zone),
                level_min=COALESCE(excluded.level_min, entities.level_min),
                level_max=COALESCE(excluded.level_max, entities.level_max),
                notes=CASE WHEN excluded.notes<>'' THEN excluded.notes ELSE entities.notes END,
                data_json=CASE WHEN excluded.data_json<>'{}'
                               THEN excluded.data_json ELSE entities.data_json END
            """,
            (
                kind, name, norm, source_page_id, source_url, ext, zone,
                level_min, level_max, notes, payload,
            ),
        )
        self._commit()
        row = self.conn.execute(
            """
            SELECT id FROM entities
            WHERE kind=? AND normalized_name=? AND external_id=?
            """,
            (kind, norm, ext),
        ).fetchone()
        entity_id = int(row["id"])
        if source_page_id is not None:
            self.link_entity_source(entity_id, source_page_id, role="primary")
        if external_namespace and ext:
            self.add_external_id(entity_id, external_namespace, ext, source_page_id=source_page_id)
        return entity_id

    def merge_entity_data(self, entity_id: int, data: dict[str, Any]) -> None:
        if not data:
            return
        row = self.conn.execute("SELECT data_json FROM entities WHERE id=?", (entity_id,)).fetchone()
        if row is None:
            return
        try:
            current = json.loads(row["data_json"] or "{}")
        except json.JSONDecodeError:
            current = {}
        if not isinstance(current, dict):
            current = {}
        current.update(data)
        self.conn.execute(
            "UPDATE entities SET data_json=? WHERE id=?",
            (json.dumps(current, ensure_ascii=False), entity_id),
        )
        self._commit()

    def add_alias(
        self,
        entity_id: int,
        alias: str,
        *,
        alias_type: str = "source",
        source_page_id: int | None = None,
    ) -> None:
        alias = " ".join(alias.split()).strip()
        if not alias:
            return
        self.conn.execute(
            """
            INSERT OR IGNORE INTO entity_aliases(
                entity_id, alias, normalized_alias, alias_type, source_page_id
            ) VALUES(?,?,?,?,?)
            """,
            (entity_id, alias, normalize_name(alias), alias_type, source_page_id),
        )
        self._commit()

    def aliases_for_entity(self, entity_id: int):
        return self.conn.execute(
            "SELECT * FROM entity_aliases WHERE entity_id=? ORDER BY alias_type, alias",
            (entity_id,),
        ).fetchall()

    def name_matches_entity(self, entity_id: int, observed_name: str | None) -> bool:
        if not observed_name:
            return False
        norm = normalize_name(observed_name)
        row = self.conn.execute(
            "SELECT normalized_name FROM entities WHERE id=?", (entity_id,)
        ).fetchone()
        if row and row["normalized_name"] == norm:
            return True
        return self.conn.execute(
            """
            SELECT 1 FROM entity_aliases
            WHERE entity_id=? AND normalized_alias=? LIMIT 1
            """,
            (entity_id, norm),
        ).fetchone() is not None

    def upsert_relationship(
        self,
        source_entity_id: int,
        target_entity_id: int,
        relation: str,
        *,
        quantity: int | None = None,
        source_page_id: int | None = None,
        evidence: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        payload = json.dumps(data or {}, ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO entity_relationships(
                source_entity_id, target_entity_id, relation, quantity,
                source_page_id, evidence, data_json
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(source_entity_id, target_entity_id, relation, source_page_id)
            DO UPDATE SET
                quantity=COALESCE(excluded.quantity, entity_relationships.quantity),
                evidence=CASE WHEN excluded.evidence<>'' THEN excluded.evidence ELSE entity_relationships.evidence END,
                data_json=CASE WHEN excluded.data_json<>'{}' THEN excluded.data_json ELSE entity_relationships.data_json END
            """,
            (
                source_entity_id, target_entity_id, relation, quantity,
                source_page_id, evidence, payload,
            ),
        )
        self._commit()

    def relationships_for_entity(self, entity_id: int):
        return self.conn.execute(
            """
            SELECT r.*,
                   s.kind AS source_kind, s.name AS source_name, s.source_url AS source_url,
                   t.kind AS target_kind, t.name AS target_name, t.source_url AS target_url,
                   CASE WHEN r.source_entity_id=? THEN 'out' ELSE 'in' END AS direction
            FROM entity_relationships r
            JOIN entities s ON s.id=r.source_entity_id
            JOIN entities t ON t.id=r.target_entity_id
            WHERE r.source_entity_id=? OR r.target_entity_id=?
            ORDER BY r.relation, direction, s.name, t.name
            """,
            (entity_id, entity_id, entity_id),
        ).fetchall()

    def relationship_targets(self, source_entity_id: int, relation: str):
        return self.conn.execute(
            """
            SELECT e.*, r.quantity, r.evidence, r.data_json AS relationship_data_json
            FROM entity_relationships r
            JOIN entities e ON e.id=r.target_entity_id
            WHERE r.source_entity_id=? AND r.relation=?
            ORDER BY e.name
            """,
            (source_entity_id, relation),
        ).fetchall()

    def add_location(
        self,
        entity_id: int,
        *,
        zone_entity_id: int | None,
        y: float | None,
        x: float | None,
        z: float | None = None,
        label: str = "",
        source_page_id: int | None = None,
        evidence: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        # Page re-imports clear their derived locations first, so a simple insert
        # preserves multiple legitimate locations for the same entity.
        self.conn.execute(
            """
            INSERT INTO entity_locations(
                entity_id, zone_entity_id, y, x, z, label,
                source_page_id, evidence, data_json
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                entity_id, zone_entity_id, y, x, z, label,
                source_page_id, evidence,
                json.dumps(data or {}, ensure_ascii=False),
            ),
        )
        self._commit()

    def locations_for_entity(self, entity_id: int):
        return self.conn.execute(
            """
            SELECT l.*, z.name AS zone_name, z.source_url AS zone_url
            FROM entity_locations l
            LEFT JOIN entities z ON z.id=l.zone_entity_id
            WHERE l.entity_id=?
            ORDER BY l.id
            """,
            (entity_id,),
        ).fetchall()

    def locations_in_zone(self, zone_name: str):
        zone_row, _status = self.resolve_entity(zone_name, "zone")
        if zone_row is not None:
            return self.conn.execute(
                """
                SELECT l.*, e.id AS entity_id, e.kind, e.name,
                       z.name AS zone_name, e.source_url
                FROM entity_locations l
                JOIN entities e ON e.id=l.entity_id
                LEFT JOIN entities z ON z.id=l.zone_entity_id
                WHERE l.zone_entity_id=?
                  AND l.x IS NOT NULL AND l.y IS NOT NULL
                ORDER BY e.kind, e.name, l.id
                """,
                (int(zone_row["id"]),),
            ).fetchall()

        norm = normalize_name(zone_name)
        return self.conn.execute(
            """
            SELECT l.*, e.id AS entity_id, e.kind, e.name,
                   z.name AS zone_name, e.source_url
            FROM entity_locations l
            JOIN entities e ON e.id=l.entity_id
            LEFT JOIN entities z ON z.id=l.zone_entity_id
            WHERE lower(trim(COALESCE(z.name, e.zone, '')))=?
              AND l.x IS NOT NULL AND l.y IS NOT NULL
            ORDER BY e.kind, e.name, l.id
            """,
            (norm,),
        ).fetchall()

    def clear_page_derivatives(self, source_page_id: int) -> None:
        """Remove only facts generated from one imported page before re-extracting it."""
        self.conn.execute(
            "DELETE FROM entity_relationships WHERE source_page_id=?", (source_page_id,)
        )
        self.conn.execute(
            "DELETE FROM entity_locations WHERE source_page_id=?", (source_page_id,)
        )
        self.conn.execute(
            "DELETE FROM entity_aliases WHERE source_page_id=?", (source_page_id,)
        )
        self.conn.execute(
            "DELETE FROM quest_steps WHERE source_page_id=?", (source_page_id,)
        )
        self._commit()

    def add_quest_step(
        self,
        quest_id: int,
        order: int,
        description: str,
        *,
        zone: str | None = None,
        match: dict[str, Any] | None = None,
        source_page_id: int | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO quest_steps(
                quest_entity_id, step_order, description, zone, match_json, source_page_id
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(quest_entity_id, step_order) DO UPDATE SET
                description=excluded.description,
                zone=excluded.zone,
                match_json=excluded.match_json,
                source_page_id=COALESCE(excluded.source_page_id, quest_steps.source_page_id)
            """,
            (
                quest_id, order, description, zone,
                json.dumps(match or {}, ensure_ascii=False), source_page_id,
            ),
        )
        self._commit()

    def upsert_entity_detail(
        self,
        entity_id: int,
        *,
        source_page_id: int | None = None,
        detail_format: str = "text",
        detail_text: str = "",
        detail_json: dict[str, Any] | list[Any] | str | int | float | bool | None = None,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        if detail_json is None:
            payload = "{}"
        elif isinstance(detail_json, str):
            payload = detail_json
        else:
            payload = json.dumps(detail_json, ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO entity_details(
                entity_id, source_page_id, detail_format, detail_text, detail_json, updated_at
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(entity_id) DO UPDATE SET
                source_page_id=COALESCE(excluded.source_page_id, entity_details.source_page_id),
                detail_format=excluded.detail_format,
                detail_text=excluded.detail_text,
                detail_json=excluded.detail_json,
                updated_at=excluded.updated_at
            """,
            (entity_id, source_page_id, detail_format, detail_text, payload, now),
        )
        if source_page_id is not None:
            self.link_entity_source(entity_id, source_page_id, role="detail")
        self._commit()

    def entity_detail(self, entity_id: int):
        return self.conn.execute(
            "SELECT * FROM entity_details WHERE entity_id=?", (entity_id,)
        ).fetchone()

    def clear_support_table_source(self, table: str, source_page_id: int) -> None:
        allowed = {"skill_caps", "base_stats", "ac_mitigation", "spell_stacking"}
        if table not in allowed:
            raise ValueError(f"Unsupported client-data table: {table}")
        self.conn.execute(f"DELETE FROM {table} WHERE source_page_id=?", (source_page_id,))
        self._commit()

    def replace_skill_caps(self, source_page_id: int, rows: list[tuple[int, int, int, int]]) -> int:
        self.clear_support_table_source("skill_caps", source_page_id)
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO skill_caps(class_id, skill_id, level, cap, source_page_id)
            VALUES(?,?,?,?,?)
            """,
            [(a, b, c, d, source_page_id) for a, b, c, d in rows],
        )
        self._commit()
        return len(rows)

    def replace_base_stats(self, source_page_id: int, rows: list[tuple]) -> int:
        self.clear_support_table_source("base_stats", source_page_id)
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO base_stats(
                level, class_id, hp, mana, endurance,
                hp_regen, mana_regen, endurance_regen, source_page_id
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            [tuple(row) + (source_page_id,) for row in rows],
        )
        self._commit()
        return len(rows)

    def replace_ac_mitigation(self, source_page_id: int, rows: list[tuple]) -> int:
        self.clear_support_table_source("ac_mitigation", source_page_id)
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO ac_mitigation(
                class_id, level, ac_cap, soft_cap_multiplier, source_page_id
            ) VALUES(?,?,?,?,?)
            """,
            [tuple(row) + (source_page_id,) for row in rows],
        )
        self._commit()
        return len(rows)

    def replace_spell_stacking(self, source_page_id: int, rows: list[tuple]) -> int:
        self.clear_support_table_source("spell_stacking", source_page_id)
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO spell_stacking(
                spell_id, stacking_group, rank, stacking_type, source_page_id
            ) VALUES(?,?,?,?,?)
            """,
            [tuple(row) + (source_page_id,) for row in rows],
        )
        self._commit()
        return len(rows)

    def support_table_counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in ("skill_caps", "base_stats", "ac_mitigation", "spell_stacking", "entity_details"):
            result[table] = int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return result

    def rebuild_search_index(self) -> int:
        """Rebuild the derived FTS5 index from EverQuestie's normalized DB.

        The knowledge corpus can exceed 80K entities and rich spell records can be
        large, so this deliberately streams rows in bounded batches instead of
        materializing the entire corpus and a second FTS payload copy in RAM.
        """
        if not self.fts_available:
            return 0
        inserted = 0
        with self.batch():
            self.conn.execute("DELETE FROM entity_fts")
            cursor = self.conn.execute(
                """
                SELECT e.id, e.kind, e.name, e.notes, e.data_json,
                       COALESCE((
                           SELECT group_concat(a.alias, ' ')
                           FROM entity_aliases a WHERE a.entity_id=e.id
                       ), '') AS aliases,
                       COALESCE(d.detail_text, '') AS detail_text,
                       COALESCE(d.detail_json, '') AS detail_json,
                       COALESCE((
                           SELECT group_concat(qs.description, ' ')
                           FROM quest_steps qs WHERE qs.quest_entity_id=e.id
                       ), '') AS quest_text
                FROM entities e
                LEFT JOIN entity_details d ON d.entity_id=e.id
                ORDER BY e.id
                """
            )
            while True:
                rows = cursor.fetchmany(1000)
                if not rows:
                    break
                payload = []
                for row in rows:
                    body = "\n".join(
                        part for part in (
                            str(row["notes"] or ""),
                            str(row["detail_text"] or ""),
                            str(row["detail_json"] or ""),
                            str(row["quest_text"] or ""),
                            str(row["data_json"] or ""),
                        ) if part
                    )
                    payload.append(
                        (int(row["id"]), row["kind"], row["name"], row["aliases"], body)
                    )
                self.conn.executemany(
                    "INSERT INTO entity_fts(entity_id, kind, name, aliases, body) VALUES(?,?,?,?,?)",
                    payload,
                )
                inserted += len(payload)
            self.set_meta("fts_last_rebuild", datetime.now().isoformat(timespec="seconds"))
            self.set_meta("fts_dirty", "0")
        return inserted

    @staticmethod
    def _fts_query(term: str) -> str:
        # Prefix-match ordinary whitespace-delimited words while neutralizing FTS
        # punctuation/operators.  This keeps the Search box forgiving for EQ names.
        import re
        tokens = re.findall(r"[\w']+", term, flags=re.UNICODE)
        return " AND ".join('"' + token.replace('"', '""') + '"*' for token in tokens)

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
            indexed = int(self.conn.execute("SELECT COUNT(*) FROM entity_fts").fetchone()[0])
            if indexed == 0:
                return self.search_entities(term, kind, limit=limit, offset=offset)
            return self.conn.execute(
                """
                SELECT e.*, sp.title AS source_title, bm25(entity_fts, 3.0, 1.5, 0.5) AS rank
                FROM entity_fts
                JOIN entities e ON e.id=CAST(entity_fts.entity_id AS INTEGER)
                LEFT JOIN source_pages sp ON sp.id=e.source_page_id
                WHERE entity_fts MATCH ?
                  AND (? IS NULL OR e.kind=?)
                ORDER BY rank, e.kind, e.name
                LIMIT ? OFFSET ?
                """,
                (query, kind, kind, safe_limit, safe_offset),
            ).fetchall()
        except sqlite3.OperationalError:
            return self.search_entities(term, kind, limit=limit, offset=offset)

    def database_diagnostics(self) -> dict[str, Any]:
        integrity = str(self.conn.execute("PRAGMA integrity_check").fetchone()[0])
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
                fts_rows = int(self.conn.execute("SELECT COUNT(*) FROM entity_fts").fetchone()[0])
            except sqlite3.OperationalError:
                pass
        return {
            "path": str(self.path),
            "integrity": integrity,
            "fts_available": bool(self.fts_available),
            "fts_rows": fts_rows,
            "fts_last_rebuild": self.get_meta("fts_last_rebuild", ""),
            "fts_dirty": self.get_meta("fts_dirty", "1") == "1",
            "counts": counts,
            "support": self.support_table_counts(),
        }

    def search_entities(
        self,
        term: str = "",
        kind: str | None = None,
        *,
        limit: int = 250,
        offset: int = 0,
    ):
        clauses = []
        args: list[Any] = []
        if term.strip():
            needle = f"%{normalize_name(term)}%"
            clauses.append(
                "(e.normalized_name LIKE ? OR EXISTS ("
                "SELECT 1 FROM entity_aliases a WHERE a.entity_id=e.id AND a.normalized_alias LIKE ?))"
            )
            args.extend([needle, needle])
        if kind:
            clauses.append("e.kind=?")
            args.append(kind)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        safe_limit = max(1, min(int(limit), 5000))
        safe_offset = max(0, int(offset))
        args.extend([safe_limit, safe_offset])
        return self.conn.execute(
            f"""
            SELECT e.*, sp.title AS source_title
            FROM entities e
            LEFT JOIN source_pages sp ON sp.id=e.source_page_id
            {where}
            ORDER BY e.kind, e.name
            LIMIT ? OFFSET ?
            """,
            args,
        ).fetchall()

    def entity_kind_counts(self, term: str = "", kind: str | None = None):
        """Return entity counts grouped by knowledge kind.

        The Knowledge tree uses this to stay responsive with very large local MCP
        inventories (for example tens of thousands of spells) without materializing
        every child row merely to display a collapsible topic node.
        """
        clauses = []
        args: list[Any] = []
        if term.strip():
            needle = f"%{normalize_name(term)}%"
            clauses.append(
                "(e.normalized_name LIKE ? OR EXISTS ("
                "SELECT 1 FROM entity_aliases a WHERE a.entity_id=e.id AND a.normalized_alias LIKE ?))"
            )
            args.extend([needle, needle])
        if kind:
            clauses.append("e.kind=?")
            args.append(kind)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return self.conn.execute(
            f"""
            SELECT e.kind, COUNT(*) AS count
            FROM entities e
            {where}
            GROUP BY e.kind
            ORDER BY e.kind
            """,
            args,
        ).fetchall()

    def resolve_entity(self, term: str, kind: str | None = None):
        """Return (row, status) where status is exact, alias, unique, ambiguous, missing."""
        norm = normalize_name(term)
        rows = self.search_entities(term, kind)
        exact = [r for r in rows if r["normalized_name"] == norm]
        if len(exact) == 1:
            return exact[0], "exact"

        alias_rows = self.conn.execute(
            """
            SELECT DISTINCT e.*
            FROM entity_aliases a
            JOIN entities e ON e.id=a.entity_id
            WHERE a.normalized_alias=?
              AND (? IS NULL OR e.kind=?)
            """,
            (norm, kind, kind),
        ).fetchall()
        if len(alias_rows) == 1:
            return alias_rows[0], "alias"
        if len(rows) == 1:
            return rows[0], "unique"
        if len(rows) > 1 or len(alias_rows) > 1:
            return None, "ambiguous"
        return None, "missing"

    def entity(self, entity_id: int):
        return self.conn.execute(
            """
            SELECT e.*, sp.plain_text AS source_text,
                   sp.raw_html AS source_html,
                   sp.imported_at AS source_imported_at
            FROM entities e
            LEFT JOIN source_pages sp ON sp.id=e.source_page_id
            WHERE e.id=?
            """,
            (entity_id,),
        ).fetchone()

    def track_quest(self, quest_id: int) -> None:
        self.conn.execute(
            """
            INSERT INTO tracked_quests(quest_entity_id, tracked_at, active_step)
            VALUES(?,?,1)
            ON CONFLICT(quest_entity_id) DO NOTHING
            """,
            (quest_id, datetime.now().isoformat(timespec="seconds")),
        )
        self._recompute_active_step(quest_id)
        self._commit()

    def untrack_quest(self, quest_id: int) -> None:
        self.conn.execute(
            "DELETE FROM tracked_quests WHERE quest_entity_id=?", (quest_id,)
        )
        self._commit()

    def tracked_quests(self):
        return self.conn.execute(
            """
            SELECT e.id, e.name, e.zone, e.source_url, tq.active_step
            FROM tracked_quests tq
            JOIN entities e ON e.id=tq.quest_entity_id
            ORDER BY tq.tracked_at
            """
        ).fetchall()

    def quest_steps(self, quest_id: int):
        return self.conn.execute(
            """
            SELECT qs.*,
                   COALESCE(qp.progress_count,0) AS progress_count,
                   COALESCE(qp.complete,0) AS complete
            FROM quest_steps qs
            LEFT JOIN quest_progress qp
              ON qp.quest_entity_id=qs.quest_entity_id
             AND qp.step_order=qs.step_order
            WHERE qs.quest_entity_id=?
            ORDER BY qs.step_order
            """,
            (quest_id,),
        ).fetchall()

    def _recompute_active_step(self, quest_id: int) -> None:
        pending = self.conn.execute(
            """
            SELECT qs.step_order
            FROM quest_steps qs
            LEFT JOIN quest_progress qp
              ON qp.quest_entity_id=qs.quest_entity_id
             AND qp.step_order=qs.step_order
            WHERE qs.quest_entity_id=? AND COALESCE(qp.complete,0)=0
            ORDER BY qs.step_order LIMIT 1
            """,
            (quest_id,),
        ).fetchone()
        if pending:
            active = int(pending["step_order"])
        else:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(step_order),0)+1 AS n FROM quest_steps WHERE quest_entity_id=?",
                (quest_id,),
            ).fetchone()
            active = int(row["n"])
        self.conn.execute(
            "UPDATE tracked_quests SET active_step=? WHERE quest_entity_id=?",
            (active, quest_id),
        )

    def set_step_progress(
        self,
        quest_id: int,
        step_order: int,
        count: int,
        complete: bool,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds") if complete else None
        self.conn.execute(
            """
            INSERT INTO quest_progress(
                quest_entity_id, step_order, progress_count,
                complete, completed_at
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(quest_entity_id, step_order) DO UPDATE SET
                progress_count=MAX(quest_progress.progress_count, excluded.progress_count),
                complete=MAX(quest_progress.complete, excluded.complete),
                completed_at=CASE
                    WHEN excluded.complete=1
                    THEN COALESCE(quest_progress.completed_at, excluded.completed_at)
                    ELSE quest_progress.completed_at
                END
            """,
            (quest_id, step_order, count, int(complete), now),
        )
        self._recompute_active_step(quest_id)
        self._commit()


    def reset_quest_progress(self, quest_id: int) -> None:
        """Clear reconstructed/live progress for one quest and return it to step 1."""
        self.conn.execute(
            "DELETE FROM quest_progress WHERE quest_entity_id=?", (quest_id,)
        )
        self._recompute_active_step(quest_id)
        self._commit()

    def is_quest_tracked(self, quest_id: int) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM tracked_quests WHERE quest_entity_id=?", (quest_id,)
        ).fetchone() is not None

    def observed_event_history(self):
        """Return stored observations in original insertion order as Event objects."""
        rows = self.conn.execute(
            "SELECT * FROM observed_events ORDER BY id"
        ).fetchall()
        out: list[Event] = []
        for r in rows:
            occurred = None
            if r["occurred_at"]:
                try:
                    occurred = datetime.fromisoformat(r["occurred_at"])
                except ValueError:
                    occurred = None
            try:
                fields = json.loads(r["fields_json"] or "{}")
            except json.JSONDecodeError:
                fields = {}
            out.append(Event(
                kind=r["kind"], raw=r["raw"], timestamp=occurred,
                actor=r["actor"], target=r["target"], text=r["text"],
                zone=r["zone"], item=r["item"], amount=r["amount"],
                fields=fields,
            ))
        return out

    def add_demo_seed(self) -> None:
        # Retained only as a small smoke-test record. Imported Allakhazam data takes priority.
        qid = self.upsert_entity(
            kind="quest",
            name="Crushbone Belts & Shoulderpads",
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=294",
            external_id="quest:294",
            notes="Demo quest shell. Import the Allakhazam page to populate authoritative details.",
        )
        if not self.quest_steps(qid):
            self.add_quest_step(
                qid, 1,
                "Demo: obtain a Crushbone Belt.",
                match={"event": "loot", "item": "Crushbone Belt", "count": 1},
            )
            self.add_quest_step(
                qid, 2,
                "Demo: speak with or observe Canloe Nusback.",
                match={"event": "npc_say", "npc": "Canloe Nusback"},
            )
