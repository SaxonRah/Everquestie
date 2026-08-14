from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any

from .db import Database
from .eqmap import map_to_game, normalize_map_name


ZONE_TRAVEL_CATALOG_VERSION = "1"
_SHORT_NAME_KEYS = (
    "map_short_name",
    "short_name",
    "shortName",
    "zone_short_name",
    "zoneShortName",
)

_TRAVEL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("portal", re.compile(r"^(?:portal|teleport|teleporter)\s+(?:to\s+)?(.+)$", re.I)),
    ("zone_line", re.compile(r"^(?:zone\s*line|zoneline|zone)\s*(?:to|:)\s*(.+)$", re.I)),
    ("exit", re.compile(r"^(?:exit|entrance)\s+(?:to\s+)?(.+)$", re.I)),
    ("travel", re.compile(r"^to\s+(.+)$", re.I)),
    ("zone_line", re.compile(r"^(.+?)\s+(?:zone\s*line|zoneline)$", re.I)),
)


@dataclass(frozen=True, slots=True)
class ZoneTravelEdge:
    id: int
    source_zone_entity_id: int
    target_zone_entity_id: int | None
    connection_kind: str
    bidirectional: bool
    status: str
    reason: str
    evidence: str
    source_name: str
    source_kind: str
    source_key: str
    source_version: str
    x: float | None
    y: float | None
    z: float | None


@dataclass(frozen=True, slots=True)
class ZoneTravelBuildStats:
    labels_scanned: int
    candidates: int
    linked: int
    ambiguous: int
    unresolved: int


class ZoneTravelCatalog:
    """Source-aware canonical zone topology compiled into EverQuestie knowledge.

    Map labels are one evidence provider, not the topology schema. Future builder
    providers (including a later Allakhazam/wiki mirror) can add connections to the
    same table without changing runtime route queries.
    """

    def __init__(self, db: Database):
        self.db = db
        if getattr(db, "knowledge_writable", True):
            self.ensure_schema()

    def ensure_schema(self) -> None:
        self.db.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS zone_travel_edges (
                id INTEGER PRIMARY KEY,
                source_zone_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                target_zone_entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
                connection_kind TEXT NOT NULL DEFAULT 'travel',
                bidirectional INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'unresolved',
                reason TEXT NOT NULL DEFAULT '',
                evidence TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_key TEXT NOT NULL,
                source_version TEXT NOT NULL DEFAULT '',
                source_page_id INTEGER REFERENCES source_pages(id) ON DELETE CASCADE,
                map_stem TEXT NOT NULL DEFAULT '',
                label_id INTEGER,
                x REAL,
                y REAL,
                z REAL,
                data_json TEXT NOT NULL DEFAULT '{}',
                catalog_version TEXT NOT NULL DEFAULT '1',
                updated_at TEXT NOT NULL,
                UNIQUE(source_kind, source_name, source_key, connection_kind)
            );
            CREATE INDEX IF NOT EXISTS ix_zone_travel_source
            ON zone_travel_edges(source_zone_entity_id, status);
            CREATE INDEX IF NOT EXISTS ix_zone_travel_target
            ON zone_travel_edges(target_zone_entity_id, status);
            CREATE INDEX IF NOT EXISTS ix_zone_travel_provider
            ON zone_travel_edges(source_kind, source_name);
            """
        )
        self.db.conn.commit()

    def _table_exists(self) -> bool:
        return self.db.conn.execute(
            """
            SELECT 1 FROM sqlite_temp_master
            WHERE type IN ('table','view') AND name='zone_travel_edges'
            UNION ALL
            SELECT 1 FROM sqlite_master
            WHERE type IN ('table','view') AND name='zone_travel_edges'
            LIMIT 1
            """
        ).fetchone() is not None

    @staticmethod
    def _human_text(value: str) -> str:
        text = (value or "").replace("_", " ").replace("->", " to ").replace("=>", " to ")
        return " ".join(text.strip(" \t\r\n.-:=><").split())

    @classmethod
    def _travel_candidate(cls, label: str) -> tuple[str, str] | None:
        text = cls._human_text(label)
        if not text:
            return None
        for kind, pattern in _TRAVEL_PATTERNS:
            match = pattern.match(text)
            if not match:
                continue
            destination = cls._human_text(match.group(1))
            if destination:
                return kind, destination
        return None

    @staticmethod
    def _add_token(tokens: dict[str, set[int]], token: str, entity_id: int) -> None:
        normalized = normalize_map_name(token)
        if normalized:
            tokens.setdefault(normalized, set()).add(entity_id)

    def _zone_tokens(self) -> dict[str, set[int]]:
        tokens: dict[str, set[int]] = {}
        zone_ids: set[int] = set()
        for row in self.db.conn.execute(
            "SELECT id,name,data_json FROM entities WHERE kind='zone' ORDER BY id"
        ).fetchall():
            entity_id = int(row["id"])
            zone_ids.add(entity_id)
            name = str(row["name"])
            self._add_token(tokens, name, entity_id)
            if name.casefold().startswith("the "):
                self._add_token(tokens, name[4:], entity_id)
            try:
                data: Any = json.loads(row["data_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                data = {}
            if isinstance(data, dict):
                for key in _SHORT_NAME_KEYS:
                    value = str(data.get(key) or "").strip()
                    if value:
                        self._add_token(tokens, value, entity_id)

        if zone_ids:
            for row in self.db.conn.execute(
                "SELECT entity_id,alias,alias_type FROM entity_aliases ORDER BY entity_id,id"
            ).fetchall():
                entity_id = int(row["entity_id"])
                if entity_id not in zone_ids:
                    continue
                alias = str(row["alias"] or "").strip()
                alias_type = str(row["alias_type"] or "").casefold()
                if not alias or alias.isdigit() or alias_type == "eq_zone_id":
                    continue
                self._add_token(tokens, alias, entity_id)
                if alias.casefold().startswith("the "):
                    self._add_token(tokens, alias[4:], entity_id)

        # Canonical map bindings are also strong exact short-name evidence.
        table = self.db.conn.execute(
            """
            SELECT 1 FROM sqlite_temp_master
            WHERE type IN ('table','view') AND name='zone_map_bindings'
            UNION ALL
            SELECT 1 FROM sqlite_master
            WHERE type IN ('table','view') AND name='zone_map_bindings'
            LIMIT 1
            """
        ).fetchone()
        if table is not None:
            for row in self.db.conn.execute(
                "SELECT zone_entity_id,map_stem FROM zone_map_bindings "
                "WHERE status='linked' AND zone_entity_id IS NOT NULL"
            ).fetchall():
                self._add_token(tokens, str(row["map_stem"]), int(row["zone_entity_id"]))
        return tokens

    def _resolve_destination(
        self,
        destination: str,
        source_zone_entity_id: int,
        tokens: dict[str, set[int]],
    ) -> tuple[int | None, str, str]:
        key = normalize_map_name(destination)
        matches = sorted(tokens.get(key, set()))
        if not matches:
            return None, "unresolved", "travel destination has no exact canonical zone identity"
        if len(matches) > 1:
            return None, "ambiguous", f"travel destination matches {len(matches)} canonical zones"
        target = matches[0]
        if target == source_zone_entity_id:
            return None, "unresolved", "travel label resolves back to its source zone"
        return target, "linked", "exact canonical zone name/alias/short-name match"

    def reconcile_from_maps(self, *, source_name: str | None = None) -> ZoneTravelBuildStats:
        """Compile conservative directed travel candidates from canonicalized map labels."""
        if not getattr(self.db, "knowledge_writable", True):
            raise RuntimeError("zone travel compilation is builder-only")
        self.ensure_schema()

        delete_sql = "DELETE FROM zone_travel_edges WHERE source_kind='map_label'"
        delete_args: tuple[object, ...] = ()
        if source_name:
            delete_sql += " AND source_name=?"
            delete_args = (source_name,)

        where = "WHERE zmb.status='linked' AND zmb.zone_entity_id IS NOT NULL"
        args: tuple[object, ...] = ()
        if source_name:
            where += " AND ms.source_name=?"
            args = (source_name,)
        rows = self.db.conn.execute(
            """
            SELECT ml.id AS label_id,ml.clean_text,ml.source_line,ml.layer,
                   ml.x,ml.y,ml.z,ms.source_name,ms.source_version,ms.source_key,
                   ms.map_stem,zmb.zone_entity_id AS source_zone_entity_id,
                   zmb.zone_name AS source_zone_name
            FROM map_labels ml
            JOIN map_sources ms ON ms.id=ml.source_id
            JOIN zone_map_bindings zmb
              ON zmb.source_name=ms.source_name AND zmb.map_stem=ms.map_stem
            """
            + where
            + " ORDER BY ms.source_name,ms.source_key,ml.source_line",
            args,
        ).fetchall()

        tokens = self._zone_tokens()
        now = datetime.now().isoformat(timespec="seconds")
        candidates = linked = ambiguous = unresolved = 0
        with self.db.batch():
            self.db.conn.execute(delete_sql, delete_args)
            for row in rows:
                candidate = self._travel_candidate(str(row["clean_text"] or ""))
                if candidate is None:
                    continue
                candidates += 1
                kind, destination = candidate
                source_zone_id = int(row["source_zone_entity_id"])
                target_id, status, reason = self._resolve_destination(
                    destination,
                    source_zone_id,
                    tokens,
                )
                if status == "linked":
                    linked += 1
                elif status == "ambiguous":
                    ambiguous += 1
                else:
                    unresolved += 1

                gx, gy, gz = map_to_game(float(row["x"]), float(row["y"]), float(row["z"]))
                source_key = (
                    f"{row['source_key']}#L{int(row['layer'])}:P{int(row['source_line'])}"
                )
                payload = {
                    "destination_text": destination,
                    "source_zone_name": str(row["source_zone_name"] or ""),
                    "map_label_id": int(row["label_id"]),
                }
                self.db.conn.execute(
                    """
                    INSERT INTO zone_travel_edges(
                        source_zone_entity_id,target_zone_entity_id,connection_kind,
                        bidirectional,status,reason,evidence,source_name,source_kind,
                        source_key,source_version,source_page_id,map_stem,label_id,
                        x,y,z,data_json,catalog_version,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_kind,source_name,source_key,connection_kind)
                    DO UPDATE SET
                        source_zone_entity_id=excluded.source_zone_entity_id,
                        target_zone_entity_id=excluded.target_zone_entity_id,
                        bidirectional=excluded.bidirectional,
                        status=excluded.status,
                        reason=excluded.reason,
                        evidence=excluded.evidence,
                        source_version=excluded.source_version,
                        map_stem=excluded.map_stem,
                        label_id=excluded.label_id,
                        x=excluded.x,y=excluded.y,z=excluded.z,
                        data_json=excluded.data_json,
                        catalog_version=excluded.catalog_version,
                        updated_at=excluded.updated_at
                    """,
                    (
                        source_zone_id,
                        target_id,
                        kind,
                        0,
                        status,
                        reason,
                        str(row["clean_text"] or ""),
                        str(row["source_name"] or ""),
                        "map_label",
                        source_key,
                        str(row["source_version"] or ""),
                        None,
                        str(row["map_stem"] or ""),
                        int(row["label_id"]),
                        gx,
                        gy,
                        gz,
                        json.dumps(payload, ensure_ascii=False),
                        ZONE_TRAVEL_CATALOG_VERSION,
                        now,
                    ),
                )

        return ZoneTravelBuildStats(
            labels_scanned=len(rows),
            candidates=candidates,
            linked=linked,
            ambiguous=ambiguous,
            unresolved=unresolved,
        )

    def add_provider_connection(
        self,
        source_zone_entity_id: int,
        target_zone_entity_id: int,
        *,
        connection_kind: str = "travel",
        bidirectional: bool = False,
        source_name: str,
        source_kind: str = "provider",
        source_key: str,
        source_version: str = "",
        source_page_id: int | None = None,
        evidence: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        """Add explicit provider topology without coupling route queries to that provider."""
        if not getattr(self.db, "knowledge_writable", True):
            raise RuntimeError("zone travel compilation is builder-only")
        self.ensure_schema()
        now = datetime.now().isoformat(timespec="seconds")
        self.db.conn.execute(
            """
            INSERT INTO zone_travel_edges(
                source_zone_entity_id,target_zone_entity_id,connection_kind,
                bidirectional,status,reason,evidence,source_name,source_kind,
                source_key,source_version,source_page_id,data_json,catalog_version,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_kind,source_name,source_key,connection_kind)
            DO UPDATE SET
                source_zone_entity_id=excluded.source_zone_entity_id,
                target_zone_entity_id=excluded.target_zone_entity_id,
                bidirectional=excluded.bidirectional,
                status='linked',
                reason=excluded.reason,
                evidence=excluded.evidence,
                source_version=excluded.source_version,
                source_page_id=excluded.source_page_id,
                data_json=excluded.data_json,
                catalog_version=excluded.catalog_version,
                updated_at=excluded.updated_at
            """,
            (
                int(source_zone_entity_id),
                int(target_zone_entity_id),
                connection_kind,
                int(bool(bidirectional)),
                "linked",
                "explicit provider connection",
                evidence,
                source_name,
                source_kind,
                source_key,
                source_version,
                source_page_id,
                json.dumps(data or {}, ensure_ascii=False),
                ZONE_TRAVEL_CATALOG_VERSION,
                now,
            ),
        )
        self.db._commit()

    @staticmethod
    def _edge(row) -> ZoneTravelEdge:
        return ZoneTravelEdge(
            id=int(row["id"]),
            source_zone_entity_id=int(row["source_zone_entity_id"]),
            target_zone_entity_id=(
                int(row["target_zone_entity_id"])
                if row["target_zone_entity_id"] is not None
                else None
            ),
            connection_kind=str(row["connection_kind"]),
            bidirectional=bool(row["bidirectional"]),
            status=str(row["status"]),
            reason=str(row["reason"] or ""),
            evidence=str(row["evidence"] or ""),
            source_name=str(row["source_name"]),
            source_kind=str(row["source_kind"]),
            source_key=str(row["source_key"]),
            source_version=str(row["source_version"] or ""),
            x=(float(row["x"]) if row["x"] is not None else None),
            y=(float(row["y"]) if row["y"] is not None else None),
            z=(float(row["z"]) if row["z"] is not None else None),
        )

    def edges_from(self, source_zone_entity_id: int, *, linked_only: bool = True) -> list[ZoneTravelEdge]:
        if not self._table_exists():
            return []
        sql = "SELECT * FROM zone_travel_edges WHERE source_zone_entity_id=?"
        args: list[object] = [int(source_zone_entity_id)]
        if linked_only:
            sql += " AND status='linked' AND target_zone_entity_id IS NOT NULL"
        sql += " ORDER BY connection_kind,target_zone_entity_id,source_name,source_key"
        return [self._edge(row) for row in self.db.conn.execute(sql, args).fetchall()]

    def shortest_path(
        self,
        source_zone_entity_id: int,
        target_zone_entity_id: int,
        *,
        max_hops: int = 64,
    ) -> list[int]:
        """Return a conservative route using only linked directed/bidirectional evidence."""
        source = int(source_zone_entity_id)
        target = int(target_zone_entity_id)
        if source == target:
            return [source]
        if not self._table_exists():
            return []

        adjacency: dict[int, set[int]] = {}
        for row in self.db.conn.execute(
            "SELECT source_zone_entity_id,target_zone_entity_id,bidirectional "
            "FROM zone_travel_edges WHERE status='linked' "
            "AND target_zone_entity_id IS NOT NULL"
        ).fetchall():
            a = int(row["source_zone_entity_id"])
            b = int(row["target_zone_entity_id"])
            adjacency.setdefault(a, set()).add(b)
            if bool(row["bidirectional"]):
                adjacency.setdefault(b, set()).add(a)

        queue: deque[tuple[int, list[int]]] = deque([(source, [source])])
        visited = {source}
        while queue:
            current, path = queue.popleft()
            if len(path) - 1 >= max_hops:
                continue
            for nxt in sorted(adjacency.get(current, set())):
                if nxt in visited:
                    continue
                new_path = path + [nxt]
                if nxt == target:
                    return new_path
                visited.add(nxt)
                queue.append((nxt, new_path))
        return []
