from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
import json
from pathlib import Path
from typing import Callable, Iterable

from .db import Database, normalize_name
from .eqmap import discover_base_maps, map_to_game, normalize_map_name, parse_map_file
from .local_search import map_label_terms, parse_local_query


MAP_CATALOG_VERSION = "2"


@dataclass(frozen=True, slots=True)
class MapCatalogHit:
    label_id: int
    map_stem: str
    zone_name: str
    path: str
    source_name: str
    source_version: str
    source_key: str
    layer: int
    text: str
    clean_text: str
    x: float
    y: float
    z: float
    source_line: int
    linked_entity_id: int | None
    link_status: str
    link_reason: str
    score: tuple
    reason: str


@dataclass(frozen=True, slots=True)
class MapIndexStats:
    base_maps: int
    files_indexed: int
    files_unchanged: int
    labels: int
    linked: int
    ambiguous: int
    unresolved: int


class MapCatalog:
    """EverQuestie-owned, portable index of Good/Brewall/native EQ labels.

    Catalog construction is an explicit builder/manual operation.  The resulting
    labels are normalized knowledge that can be shipped in EverQuestie's versioned
    knowledge database.  Local map files remain optional rendering assets: persisted
    source keys are relative to the map-pack root and never require a builder machine
    path at runtime.  Reconciliation remains conservative and never invents entity
    semantics from a map label alone.
    """

    def __init__(self, db: Database):
        self.db = db
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.db.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS map_sources (
                id INTEGER PRIMARY KEY,
                root TEXT NOT NULL,
                source_name TEXT NOT NULL DEFAULT 'legacy-local',
                source_version TEXT NOT NULL DEFAULT '',
                source_key TEXT NOT NULL DEFAULT '',
                map_stem TEXT NOT NULL,
                zone_name TEXT NOT NULL DEFAULT '',
                layer INTEGER NOT NULL,
                path TEXT NOT NULL UNIQUE,
                mtime_ns INTEGER NOT NULL DEFAULT 0,
                size INTEGER NOT NULL DEFAULT 0,
                indexed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_map_sources_root ON map_sources(root);
            CREATE INDEX IF NOT EXISTS ix_map_sources_stem ON map_sources(map_stem, layer);

            CREATE TABLE IF NOT EXISTS map_labels (
                id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL REFERENCES map_sources(id) ON DELETE CASCADE,
                map_stem TEXT NOT NULL,
                zone_name TEXT NOT NULL DEFAULT '',
                layer INTEGER NOT NULL,
                source_line INTEGER NOT NULL,
                raw_text TEXT NOT NULL,
                clean_text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                z REAL NOT NULL,
                r INTEGER NOT NULL DEFAULT 0,
                g INTEGER NOT NULL DEFAULT 0,
                b INTEGER NOT NULL DEFAULT 0,
                size INTEGER NOT NULL DEFAULT 1,
                linked_entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
                link_status TEXT NOT NULL DEFAULT 'unresolved',
                link_reason TEXT NOT NULL DEFAULT '',
                UNIQUE(source_id, source_line)
            );
            CREATE INDEX IF NOT EXISTS ix_map_labels_name ON map_labels(normalized_text);
            CREATE INDEX IF NOT EXISTS ix_map_labels_zone ON map_labels(zone_name, normalized_text);
            CREATE INDEX IF NOT EXISTS ix_map_labels_entity ON map_labels(linked_entity_id);

            CREATE TRIGGER IF NOT EXISTS eq_map_links_dirty_entity_insert
            AFTER INSERT ON entities
            WHEN COALESCE((SELECT value FROM app_meta WHERE key='map_links_dirty'), '0') <> '1'
            BEGIN
              INSERT INTO app_meta(key, value) VALUES('map_links_dirty', '1')
              ON CONFLICT(key) DO UPDATE SET value='1';
            END;
            CREATE TRIGGER IF NOT EXISTS eq_map_links_dirty_entity_update
            AFTER UPDATE OF name, normalized_name, zone ON entities
            WHEN COALESCE((SELECT value FROM app_meta WHERE key='map_links_dirty'), '0') <> '1'
            BEGIN
              INSERT INTO app_meta(key, value) VALUES('map_links_dirty', '1')
              ON CONFLICT(key) DO UPDATE SET value='1';
            END;
            CREATE TRIGGER IF NOT EXISTS eq_map_links_dirty_alias_insert
            AFTER INSERT ON entity_aliases
            WHEN COALESCE((SELECT value FROM app_meta WHERE key='map_links_dirty'), '0') <> '1'
            BEGIN
              INSERT INTO app_meta(key, value) VALUES('map_links_dirty', '1')
              ON CONFLICT(key) DO UPDATE SET value='1';
            END;
            CREATE TRIGGER IF NOT EXISTS eq_map_links_dirty_location_insert
            AFTER INSERT ON entity_locations
            WHEN COALESCE((SELECT value FROM app_meta WHERE key='map_links_dirty'), '0') <> '1'
            BEGIN
              INSERT INTO app_meta(key, value) VALUES('map_links_dirty', '1')
              ON CONFLICT(key) DO UPDATE SET value='1';
            END;
            """
        )
        source_cols = {
            row["name"] for row in self.db.conn.execute("PRAGMA table_info(map_sources)").fetchall()
        }
        for name, ddl in {
            "source_name": "TEXT NOT NULL DEFAULT 'legacy-local'",
            "source_version": "TEXT NOT NULL DEFAULT ''",
            "source_key": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in source_cols:
                self.db.conn.execute(f"ALTER TABLE map_sources ADD COLUMN {name} {ddl}")
        self.db.conn.execute(
            "UPDATE map_sources SET source_name='legacy-local' WHERE source_name=''"
        )
        self.db.conn.execute(
            "UPDATE map_sources SET source_key=path WHERE source_key=''"
        )
        self.db.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_map_sources_identity "
            "ON map_sources(source_name, source_key)"
        )
        self.db.conn.execute(
            "INSERT INTO app_meta(key,value) VALUES('map_catalog_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (MAP_CATALOG_VERSION,),
        )
        self.db.conn.commit()

    @staticmethod
    def _canonical_text(text: str) -> str:
        variants = map_label_terms(text)
        if not variants:
            return " ".join((text or "").replace("_", " ").split()).strip()
        # map_label_terms is ordered from source text toward progressively cleaner
        # decorated-label guesses, so the final variant is the best canonical guess.
        return variants[-1]

    def _zone_map(self) -> dict[str, str]:
        """Map native map stems/long names/bindings to canonical zone display names."""
        result: dict[str, str] = {}
        zones = self.db.conn.execute(
            "SELECT id, name, normalized_name, data_json FROM entities WHERE kind='zone'"
        ).fetchall()
        by_compact_name: dict[str, str] = {}
        for row in zones:
            name = str(row["name"])
            by_compact_name[normalize_map_name(name)] = name
            result.setdefault(normalize_map_name(name), name)
            try:
                data = json.loads(row["data_json"] or "{}")
            except Exception:
                data = {}
            if isinstance(data, dict):
                for key in ("map_short_name", "short_name", "shortName", "zone_short_name"):
                    value = data.get(key)
                    if value:
                        result[normalize_map_name(str(value))] = name
        for row in self.db.conn.execute(
            "SELECT key, value FROM app_meta WHERE key LIKE 'map_binding::%'"
        ):
            suffix = str(row["key"]).split("::", 1)[-1]
            zone_name = by_compact_name.get(suffix)
            if zone_name and row["value"]:
                result[normalize_map_name(str(row["value"]))] = zone_name
        return result

    @staticmethod
    def _portable_source_path(source_name: str, source_key: str) -> str:
        source_token = normalize_map_name(source_name) or "maps"
        return f"mapcatalog://{source_token}/{source_key}"

    def _upsert_source(
        self,
        *,
        source_name: str,
        source_version: str,
        source_key: str,
        map_stem: str,
        zone_name: str,
        layer: int,
        mtime_ns: int,
        size: int,
    ) -> tuple[int, bool]:
        row = self.db.conn.execute(
            "SELECT * FROM map_sources WHERE source_name=? AND source_key=?",
            (source_name, source_key),
        ).fetchone()
        unchanged = bool(
            row
            and int(row["mtime_ns"] or 0) == int(mtime_ns)
            and int(row["size"] or 0) == int(size)
            and str(row["zone_name"] or "") == zone_name
            and str(row["source_version"] or "") == source_version
        )
        if unchanged and row is not None:
            return int(row["id"]), True

        now = datetime.now().isoformat(timespec="seconds")
        portable_path = self._portable_source_path(source_name, source_key)
        self.db.conn.execute(
            """
            INSERT INTO map_sources(
                root,source_name,source_version,source_key,map_stem,zone_name,layer,
                path,mtime_ns,size,indexed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_name,source_key) DO UPDATE SET
                root=excluded.root,
                source_version=excluded.source_version,
                map_stem=excluded.map_stem,
                zone_name=excluded.zone_name,
                layer=excluded.layer,
                path=excluded.path,
                mtime_ns=excluded.mtime_ns,
                size=excluded.size,
                indexed_at=excluded.indexed_at
            """,
            (
                source_name, source_name, source_version, source_key, map_stem, zone_name,
                int(layer), portable_path, int(mtime_ns), int(size), now,
            ),
        )
        source_id = int(
            self.db.conn.execute(
                "SELECT id FROM map_sources WHERE source_name=? AND source_key=?",
                (source_name, source_key),
            ).fetchone()[0]
        )
        return source_id, False

    def index_root(
        self,
        root: str | Path,
        *,
        source_name: str | None = None,
        source_version: str = "",
        progress: Callable[[str, int, int, str], None] | None = None,
    ) -> MapIndexStats:
        """Explicitly build or refresh one portable map-catalog source.

        The filesystem root is only an input to this build operation.  Persisted map
        identity uses ``source_name`` + a relative ``source_key`` so a catalog can be
        shipped to another machine without retaining builder-local absolute paths.
        """
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise FileNotFoundError(root_path)
        catalog_source_name = " ".join((source_name or root_path.name or "Map Pack").split()).strip()
        catalog_source_version = str(source_version or "")
        zone_by_stem = self._zone_map()
        base_maps = discover_base_maps(root_path)
        candidates: list[tuple[str, int, Path, str]] = []
        for base in base_maps:
            map_stem = base.stem
            zone_name = zone_by_stem.get(normalize_map_name(map_stem), "")
            for layer_no in range(4):
                path = root_path / (f"{map_stem}.txt" if layer_no == 0 else f"{map_stem}_{layer_no}.txt")
                if path.exists():
                    candidates.append((map_stem, layer_no, path.resolve(), zone_name))

        total_files = len(candidates)
        if progress:
            progress("scan", 0, max(1, total_files), f"Scanning {total_files:,} map files")
        seen_keys: set[str] = set()
        files_indexed = 0
        files_unchanged = 0
        stale_removed = 0

        for index, (map_stem, layer_no, path, zone_name) in enumerate(candidates, start=1):
            source_key = path.relative_to(root_path).as_posix()
            seen_keys.add(source_key)
            stat = path.stat()
            existing = self.db.conn.execute(
                "SELECT * FROM map_sources WHERE source_name=? AND source_key=?",
                (catalog_source_name, source_key),
            ).fetchone()
            unchanged = bool(
                existing
                and int(existing["mtime_ns"] or 0) == int(stat.st_mtime_ns)
                and int(existing["size"] or 0) == int(stat.st_size)
                and str(existing["zone_name"] or "") == zone_name
                and str(existing["source_version"] or "") == catalog_source_version
            )
            if unchanged:
                files_unchanged += 1
                if progress:
                    progress("index", index, max(1, total_files), f"Checked {path.name}")
                continue

            # File parsing is intentionally outside the SQLite transaction.
            parsed = parse_map_file(path, layer=layer_no)
            labels = []
            for point in parsed.points:
                raw = point.display_text
                clean = self._canonical_text(raw)
                labels.append((
                    map_stem, zone_name, layer_no, int(point.source_line),
                    raw, clean, normalize_name(clean), float(point.x), float(point.y),
                    float(point.z), int(point.r), int(point.g), int(point.b), int(point.size),
                ))

            with self.db.batch():
                source_id, _ = self._upsert_source(
                    source_name=catalog_source_name,
                    source_version=catalog_source_version,
                    source_key=source_key,
                    map_stem=map_stem,
                    zone_name=zone_name,
                    layer=layer_no,
                    mtime_ns=stat.st_mtime_ns,
                    size=stat.st_size,
                )
                self.db.conn.execute("DELETE FROM map_labels WHERE source_id=?", (source_id,))
                if labels:
                    self.db.conn.executemany(
                        """
                        INSERT INTO map_labels(
                            source_id,map_stem,zone_name,layer,source_line,
                            raw_text,clean_text,normalized_text,x,y,z,r,g,b,size
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        [(source_id, *row) for row in labels],
                    )
                self.db.set_meta("map_links_dirty", "1")
            files_indexed += 1
            if progress:
                progress("index", index, max(1, total_files), f"Indexed {path.name} ({len(labels):,} labels)")

        stale = self.db.conn.execute(
            "SELECT id,source_key FROM map_sources WHERE source_name=?", (catalog_source_name,)
        ).fetchall()
        with self.db.batch():
            for row in stale:
                if str(row["source_key"]) not in seen_keys:
                    self.db.conn.execute("DELETE FROM map_sources WHERE id=?", (int(row["id"]),))
                    stale_removed += 1
            self.db.set_meta("map_catalog_last_source", catalog_source_name)
            self.db.set_meta(
                f"map_catalog_source_version::{normalize_name(catalog_source_name)}",
                catalog_source_version,
            )
            if stale_removed:
                self.db.set_meta("map_links_dirty", "1")

        reconciliation = self.reconcile_all(
            force=bool(files_indexed or stale_removed), progress=progress
        )
        label_count = int(self.db.conn.execute(
            "SELECT COUNT(*) FROM map_labels ml JOIN map_sources ms ON ms.id=ml.source_id "
            "WHERE ms.source_name=?",
            (catalog_source_name,),
        ).fetchone()[0])
        if progress:
            progress("done", 1, 1, f"Ready: {label_count:,} indexed labels")
        return MapIndexStats(
            base_maps=len(base_maps),
            files_indexed=files_indexed,
            files_unchanged=files_unchanged,
            labels=label_count,
            linked=reconciliation["linked"],
            ambiguous=reconciliation["ambiguous"],
            unresolved=reconciliation["unresolved"],
        )

    def stats(self, root: str | Path | None = None) -> dict[str, int]:
        where = ""
        args: tuple[object, ...] = ()
        if root:
            where = " WHERE ms.root=?"
            args = (str(Path(root).resolve()),)
        row = self.db.conn.execute(
            """
            SELECT COUNT(DISTINCT ms.id) AS files, COUNT(ml.id) AS labels,
                   SUM(CASE WHEN ml.link_status='linked' THEN 1 ELSE 0 END) AS linked,
                   SUM(CASE WHEN ml.link_status='ambiguous' THEN 1 ELSE 0 END) AS ambiguous
            FROM map_sources ms LEFT JOIN map_labels ml ON ml.source_id=ms.id
            """ + where,
            args,
        ).fetchone()
        return {
            "files": int(row["files"] or 0),
            "labels": int(row["labels"] or 0),
            "linked": int(row["linked"] or 0),
            "ambiguous": int(row["ambiguous"] or 0),
        }

    @staticmethod
    def _entity_zone_matches(row, zone_name: str, location_zone_ids: set[int]) -> bool:
        if not zone_name:
            return False
        if str(row["kind"]) == "zone":
            return False
        if normalize_name(str(row["zone"] or "")) == normalize_name(zone_name):
            return True
        return int(row["id"]) in location_zone_ids

    def _candidate_entities(self, normalized_text: str):
        """Legacy exact-candidate query retained for compatibility with direct callers.

        Reconciliation itself loads the complete candidate relation set-wise through
        ``_candidate_index`` so full map catalogs never regress to one SQL query per
        label. This narrow helper remains available for older source-checkout callers
        until their external usage is explicitly retired.
        """
        return self.db.conn.execute(
            """
            SELECT DISTINCT e.*
            FROM entities e
            LEFT JOIN entity_aliases a ON a.entity_id=e.id
            WHERE e.normalized_name=? OR a.normalized_alias=?
            ORDER BY e.kind,e.name,e.id
            """,
            (normalized_text, normalized_text),
        ).fetchall()

    def _candidate_index(self) -> dict[str, dict[int, object]]:
        """Load exact entity/alias candidates for all map-label terms in two set queries."""
        result: dict[str, dict[int, object]] = {}

        for row in self.db.conn.execute(
            """
            WITH label_terms AS (
                SELECT DISTINCT normalized_text
                FROM map_labels
                WHERE normalized_text<>''
            )
            SELECT lt.normalized_text AS lookup_text,
                   e.id,e.kind,e.name,e.zone
            FROM label_terms lt
            JOIN entities e ON e.normalized_name=lt.normalized_text
            ORDER BY lt.normalized_text,e.kind,e.name,e.id
            """
        ).fetchall():
            key = str(row["lookup_text"] or "")
            result.setdefault(key, {})[int(row["id"])] = row

        for row in self.db.conn.execute(
            """
            WITH label_terms AS (
                SELECT DISTINCT normalized_text
                FROM map_labels
                WHERE normalized_text<>''
            )
            SELECT lt.normalized_text AS lookup_text,
                   e.id,e.kind,e.name,e.zone
            FROM label_terms lt
            JOIN entity_aliases a ON a.normalized_alias=lt.normalized_text
            JOIN entities e ON e.id=a.entity_id
            ORDER BY lt.normalized_text,e.kind,e.name,e.id
            """
        ).fetchall():
            key = str(row["lookup_text"] or "")
            result.setdefault(key, {})[int(row["id"])] = row

        return result

    def reconcile_all(
        self,
        *,
        force: bool = False,
        progress: Callable[[str, int, int, str], None] | None = None,
        chunk_size: int = 1000,
    ) -> dict[str, int]:
        """Reconcile map labels through the set-based canonical implementation.

        Only exact cleaned entity names/aliases are candidates. Current-zone evidence
        may disambiguate multiple exact candidates but never creates a candidate. The
        implementation groups repeated label/zone pairs so large shipped map catalogs
        avoid per-label candidate queries and per-label SQLite updates.
        """
        if not force and self.db.get_meta("map_links_dirty", "1") != "1":
            row = self.db.conn.execute(
                """
                SELECT SUM(link_status='linked'),
                       SUM(link_status='ambiguous'),
                       SUM(link_status='unresolved')
                FROM map_labels
                """
            ).fetchone()
            return {
                "linked": int(row[0] or 0),
                "ambiguous": int(row[1] or 0),
                "unresolved": int(row[2] or 0),
            }

        groups = self.db.conn.execute(
            """
            SELECT normalized_text,zone_name,COUNT(*) AS label_count
            FROM map_labels
            GROUP BY normalized_text,zone_name
            ORDER BY normalized_text,zone_name
            """
        ).fetchall()
        total = sum(int(row["label_count"] or 0) for row in groups)
        if progress:
            progress(
                "reconcile",
                0,
                max(1, total),
                f"Reconciling {total:,} map labels in {len(groups):,} unique label/zone groups",
            )

        candidates_by_text = self._candidate_index()
        location_by_zone: dict[str, set[int]] = {}
        linked = ambiguous = unresolved = 0
        pending: list[tuple[int | None, str, str, str, str]] = []
        processed = 0
        chunk_size = max(50, int(chunk_size))

        def flush() -> None:
            if not pending:
                return
            with self.db.batch():
                self.db.conn.executemany(
                    """
                    UPDATE map_labels
                    SET linked_entity_id=?,link_status=?,link_reason=?
                    WHERE normalized_text=? AND zone_name=?
                    """,
                    pending,
                )
            pending.clear()

        for group_index, group in enumerate(groups, start=1):
            normalized = str(group["normalized_text"] or "")
            zone_name = str(group["zone_name"] or "")
            label_count = int(group["label_count"] or 0)
            candidate_map = candidates_by_text.get(normalized, {}) if normalized else {}
            candidates = list(candidate_map.values())
            chosen = None
            reason = ""
            status = "unresolved"

            if len(candidates) == 1:
                chosen = candidates[0]
                status = "linked"
                reason = "exact cleaned name/alias; unique local entity"
            elif len(candidates) > 1:
                if zone_name:
                    key = normalize_name(zone_name)
                    if key not in location_by_zone:
                        location_by_zone[key] = {
                            int(row["entity_id"])
                            for row in self.db.locations_in_zone(zone_name)
                        }
                    zone_ids = location_by_zone[key]
                    narrowed = [
                        row
                        for row in candidates
                        if self._entity_zone_matches(row, zone_name, zone_ids)
                    ]
                    if len(narrowed) == 1:
                        chosen = narrowed[0]
                        status = "linked"
                        reason = "exact cleaned name/alias; unique current-zone entity"
                    else:
                        status = "ambiguous"
                        reason = f"{len(narrowed) or len(candidates)} exact entity candidates"
                else:
                    status = "ambiguous"
                    reason = f"{len(candidates)} exact entity candidates"

            entity_id = int(chosen["id"]) if chosen is not None else None
            pending.append((entity_id, status, reason, normalized, zone_name))
            processed += label_count

            if status == "linked":
                linked += label_count
            elif status == "ambiguous":
                ambiguous += label_count
            else:
                unresolved += label_count

            if len(pending) >= chunk_size:
                flush()
                if progress:
                    progress(
                        "reconcile",
                        processed,
                        max(1, total),
                        f"Reconciled {processed:,}/{total:,} labels "
                        f"({group_index:,}/{len(groups):,} unique groups)",
                    )

        flush()
        with self.db.batch():
            self.db.set_meta("map_links_dirty", "0")
            self.db.set_meta(
                "map_links_last_reconcile",
                datetime.now().isoformat(timespec="seconds"),
            )
        if progress:
            progress(
                "reconcile",
                max(1, total),
                max(1, total),
                f"Reconciled {total:,} labels in {len(groups):,} unique groups",
            )
        return {"linked": linked, "ambiguous": ambiguous, "unresolved": unresolved}

    def ensure_reconciled(self) -> None:
        if self.db.get_meta("map_links_dirty", "1") == "1":
            self.reconcile_all()

    @staticmethod
    def _fuzzy_similarity(left: str, right: str) -> float:
        left = normalize_name(left)
        right = normalize_name(right)
        if not left or not right or left[:1] != right[:1]:
            return 0.0
        best = SequenceMatcher(None, left, right).ratio()
        for a in (w for w in left.split() if len(w) >= 5):
            for b in (w for w in right.split() if len(w) >= 5):
                if a[:1] == b[:1] and abs(len(a) - len(b)) <= 2:
                    best = max(best, SequenceMatcher(None, a, b).ratio())
        return best

    def search(
        self,
        raw_query: str,
        *,
        current_zone: str | None = None,
        limit: int = 100,
    ) -> list[MapCatalogHit]:
        query = parse_local_query(raw_query)
        source_filter = normalize_name(query.source or "")
        if source_filter in {"map", "maps", "map catalog"}:
            source_filter = ""

        requested_zone = query.zone
        if requested_zone and requested_zone.casefold() == "current":
            requested_zone = current_zone

        # A type-only query must not turn unclassified map labels into implied NPCs,
        # spells, etc. Zone-only browsing is okay because zone membership is map fact.
        text = query.text.strip()
        if not text and query.kinds:
            return []

        rows = self.db.conn.execute(
            """
            SELECT ml.*, ms.path, ms.source_name, ms.source_version, ms.source_key
            FROM map_labels ml JOIN map_sources ms ON ms.id=ml.source_id
            ORDER BY ml.zone_name,ml.map_stem,ml.layer,ml.source_line
            """
        ).fetchall()

        needles = [normalize_name(v) for v in map_label_terms(text) if v] if text else []
        wanted_zone = normalize_map_name(requested_zone or "")
        current_zone_norm = normalize_map_name(current_zone or "")
        direct: list[MapCatalogHit] = []
        fuzzy: list[MapCatalogHit] = []
        allow_fuzzy = bool(text and not query.exact and (not query.kinds or "npc" in query.kinds))

        for row in rows:
            if source_filter and source_filter not in normalize_name(str(row["source_name"] or "")):
                continue
            zone_norm = normalize_map_name(str(row["zone_name"] or ""))
            stem_norm = normalize_map_name(str(row["map_stem"] or ""))
            if wanted_zone and wanted_zone not in {zone_norm, stem_norm}:
                continue
            cleaned = str(row["clean_text"] or row["raw_text"] or "")
            variants = [normalize_name(v) for v in map_label_terms(str(row["raw_text"])) if v]
            if not text:
                score = (0, 0 if current_zone_norm and current_zone_norm in {zone_norm, stem_norm} else 1,
                         str(row["zone_name"] or row["map_stem"]).casefold(), str(row["raw_text"]).casefold())
                reason = "map label · zone browse"
                direct.append(self._hit(row, score, reason))
                continue

            best = None
            reason = ""
            for needle in needles:
                if needle in variants:
                    candidate = 0
                    candidate_reason = "map label exact"
                elif not query.exact and any(v.startswith(needle) or needle.startswith(v) for v in variants):
                    candidate = 1
                    candidate_reason = "map label prefix"
                elif not query.exact and any(needle in v or v in needle for v in variants):
                    candidate = 2
                    candidate_reason = "map label contains"
                else:
                    continue
                if best is None or candidate < best:
                    best = candidate
                    reason = candidate_reason
            zone_bonus = 0 if current_zone_norm and current_zone_norm in {zone_norm, stem_norm} else 1
            if best is not None:
                if query.kinds:
                    reason += " · type unclassified"
                if zone_bonus == 0:
                    reason += " · current zone"
                direct.append(self._hit(
                    row,
                    (best, zone_bonus, len(cleaned), str(row["map_stem"]), int(row["source_line"])),
                    reason,
                ))
                continue

            if allow_fuzzy:
                similarity = max(
                    (self._fuzzy_similarity(needle, variant) for needle in needles for variant in variants),
                    default=0.0,
                )
                if similarity >= 0.74:
                    reason = f"map label fuzzy suggestion {similarity:.0%}"
                    if query.kinds:
                        reason += " · type unclassified"
                    if zone_bonus == 0:
                        reason += " · current zone"
                    fuzzy.append(self._hit(
                        row,
                        (3, zone_bonus, -similarity, len(cleaned), str(row["map_stem"]), int(row["source_line"])),
                        reason,
                    ))

        direct.sort(key=lambda hit: hit.score)
        if direct:
            return direct[: max(1, int(limit))]
        fuzzy.sort(key=lambda hit: hit.score)
        return fuzzy[: max(1, int(limit))]

    def hits_for_entity(self, entity_id: int, *, limit: int = 100) -> list[MapCatalogHit]:
        rows = self.db.conn.execute(
            """
            SELECT ml.*,ms.path,ms.source_name,ms.source_version,ms.source_key FROM map_labels ml
            JOIN map_sources ms ON ms.id=ml.source_id
            WHERE ml.linked_entity_id=?
            ORDER BY CASE WHEN ml.zone_name<>'' THEN 0 ELSE 1 END,
                     ml.zone_name,ml.map_stem,ml.layer,ml.source_line
            LIMIT ?
            """,
            (int(entity_id), max(1, min(int(limit), 1000))),
        ).fetchall()
        return [self._hit(row, (0, i), "linked map catalog evidence") for i, row in enumerate(rows)]

    @staticmethod
    def _hit(row, score: tuple, reason: str) -> MapCatalogHit:
        return MapCatalogHit(
            label_id=int(row["id"]),
            map_stem=str(row["map_stem"]),
            zone_name=str(row["zone_name"] or ""),
            path=str(row["path"]),
            source_name=str(row["source_name"] or "Map Pack"),
            source_version=str(row["source_version"] or ""),
            source_key=str(row["source_key"] or ""),
            layer=int(row["layer"]),
            text=str(row["raw_text"]),
            clean_text=str(row["clean_text"]),
            x=float(row["x"]), y=float(row["y"]), z=float(row["z"]),
            source_line=int(row["source_line"]),
            linked_entity_id=(int(row["linked_entity_id"]) if row["linked_entity_id"] is not None else None),
            link_status=str(row["link_status"] or "unresolved"),
            link_reason=str(row["link_reason"] or ""),
            score=score,
            reason=reason,
        )

def map_evidence_lines(db: Database, entity_id: int, *, limit: int = 50) -> list[str]:
    """Render linked map-label evidence without promoting it to entity-location truth."""
    try:
        rows = db.conn.execute(
            """
            SELECT ml.*,ms.path,ms.source_name,ms.source_version,ms.source_key
            FROM map_labels ml
            JOIN map_sources ms ON ms.id=ml.source_id
            WHERE ml.linked_entity_id=?
            ORDER BY ml.zone_name,ml.map_stem,ml.layer,ml.source_line
            LIMIT ?
            """,
            (int(entity_id), max(1, min(int(limit), 500))),
        ).fetchall()
    except Exception:
        return []
    if not rows:
        return []
    lines = ["", "Map catalog evidence:"]
    for row in rows:
        gx, gy, gz = map_to_game(float(row["x"]), float(row["y"]), float(row["z"]))
        zone = str(row["zone_name"] or row["map_stem"])
        lines.append(
            f"  • {row['raw_text']} | {zone} | /loc Y {gy:g}, X {gx:g}, Z {gz:g} | "
            f"layer {row['layer']} | {row['source_name']}:{row['source_key']}:{row['source_line']}"
        )
    return lines
