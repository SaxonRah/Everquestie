from __future__ import annotations

from pathlib import Path
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected patch anchor not found in {path}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_map_catalog() -> None:
    path = ROOT / "eqquest" / "map_catalog.py"
    replace_once(path, 'MAP_CATALOG_VERSION = "1"', 'MAP_CATALOG_VERSION = "2"')

    replace_once(
        path,
        """    path: str\n    layer: int\n""",
        """    path: str\n    source_name: str\n    source_version: str\n    source_key: str\n    layer: int\n""",
    )

    replace_once(
        path,
        '''    """EverQuestie-owned index of Good/Brewall/native EQ P-record labels.\n\n    Map labels are kept separate from normalized knowledge entities.  They are local\n    evidence with coordinates and source-file provenance.  Reconciliation only links\n    a label to an existing entity when an exact cleaned name/alias can be resolved\n    conservatively; the catalog never invents an NPC/item/quest type.\n    """''',
        '''    """EverQuestie-owned, portable index of Good/Brewall/native EQ labels.\n\n    Catalog construction is an explicit builder/manual operation.  The resulting\n    labels are normalized knowledge that can be shipped in EverQuestie's versioned\n    knowledge database.  Local map files remain optional rendering assets: persisted\n    source keys are relative to the map-pack root and never require a builder machine\n    path at runtime.  Reconciliation remains conservative and never invents entity\n    semantics from a map label alone.\n    """''',
    )

    replace_once(
        path,
        """            CREATE TABLE IF NOT EXISTS map_sources (\n                id INTEGER PRIMARY KEY,\n                root TEXT NOT NULL,\n                map_stem TEXT NOT NULL,\n""",
        """            CREATE TABLE IF NOT EXISTS map_sources (\n                id INTEGER PRIMARY KEY,\n                root TEXT NOT NULL,\n                source_name TEXT NOT NULL DEFAULT 'legacy-local',\n                source_version TEXT NOT NULL DEFAULT '',\n                source_key TEXT NOT NULL DEFAULT '',\n                map_stem TEXT NOT NULL,\n""",
    )

    replace_once(
        path,
        '''        self.db.conn.execute(\n            "INSERT INTO app_meta(key,value) VALUES('map_catalog_version',?) "\n            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",\n            (MAP_CATALOG_VERSION,),\n        )''',
        '''        source_cols = {\n            row["name"] for row in self.db.conn.execute("PRAGMA table_info(map_sources)").fetchall()\n        }\n        for name, ddl in {\n            "source_name": "TEXT NOT NULL DEFAULT 'legacy-local'",\n            "source_version": "TEXT NOT NULL DEFAULT ''",\n            "source_key": "TEXT NOT NULL DEFAULT ''",\n        }.items():\n            if name not in source_cols:\n                self.db.conn.execute(f"ALTER TABLE map_sources ADD COLUMN {name} {ddl}")\n        self.db.conn.execute(\n            "UPDATE map_sources SET source_name='legacy-local' WHERE source_name=''"\n        )\n        self.db.conn.execute(\n            "UPDATE map_sources SET source_key=path WHERE source_key=''"\n        )\n        self.db.conn.execute(\n            "CREATE UNIQUE INDEX IF NOT EXISTS ux_map_sources_identity "\n            "ON map_sources(source_name, source_key)"\n        )\n        self.db.conn.execute(\n            "INSERT INTO app_meta(key,value) VALUES('map_catalog_version',?) "\n            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",\n            (MAP_CATALOG_VERSION,),\n        )''',
    )

    old_method = '''    def _upsert_source(\n        self,\n        *,\n        root: str,\n        map_stem: str,\n        zone_name: str,\n        layer: int,\n        path: Path,\n        mtime_ns: int,\n        size: int,\n    ) -> tuple[int, bool]:\n        row = self.db.conn.execute(\n            "SELECT * FROM map_sources WHERE path=?", (str(path),)\n        ).fetchone()\n        unchanged = bool(\n            row\n            and int(row["mtime_ns"] or 0) == int(mtime_ns)\n            and int(row["size"] or 0) == int(size)\n            and str(row["zone_name"] or "") == zone_name\n            and str(row["root"] or "") == root\n        )\n        if unchanged and row is not None:\n            return int(row["id"]), True\n\n        now = datetime.now().isoformat(timespec="seconds")\n        self.db.conn.execute(\n            """\n            INSERT INTO map_sources(root,map_stem,zone_name,layer,path,mtime_ns,size,indexed_at)\n            VALUES(?,?,?,?,?,?,?,?)\n            ON CONFLICT(path) DO UPDATE SET\n                root=excluded.root,\n                map_stem=excluded.map_stem,\n                zone_name=excluded.zone_name,\n                layer=excluded.layer,\n                mtime_ns=excluded.mtime_ns,\n                size=excluded.size,\n                indexed_at=excluded.indexed_at\n            """,\n            (root, map_stem, zone_name, int(layer), str(path), int(mtime_ns), int(size), now),\n        )\n        source_id = int(\n            self.db.conn.execute("SELECT id FROM map_sources WHERE path=?", (str(path),)).fetchone()[0]\n        )\n        return source_id, False\n'''
    new_method = '''    @staticmethod\n    def _portable_source_path(source_name: str, source_key: str) -> str:\n        source_token = normalize_map_name(source_name) or "maps"\n        return f"mapcatalog://{source_token}/{source_key}"\n\n    def _upsert_source(\n        self,\n        *,\n        source_name: str,\n        source_version: str,\n        source_key: str,\n        map_stem: str,\n        zone_name: str,\n        layer: int,\n        mtime_ns: int,\n        size: int,\n    ) -> tuple[int, bool]:\n        row = self.db.conn.execute(\n            "SELECT * FROM map_sources WHERE source_name=? AND source_key=?",\n            (source_name, source_key),\n        ).fetchone()\n        unchanged = bool(\n            row\n            and int(row["mtime_ns"] or 0) == int(mtime_ns)\n            and int(row["size"] or 0) == int(size)\n            and str(row["zone_name"] or "") == zone_name\n            and str(row["source_version"] or "") == source_version\n        )\n        if unchanged and row is not None:\n            return int(row["id"]), True\n\n        now = datetime.now().isoformat(timespec="seconds")\n        portable_path = self._portable_source_path(source_name, source_key)\n        self.db.conn.execute(\n            """\n            INSERT INTO map_sources(\n                root,source_name,source_version,source_key,map_stem,zone_name,layer,\n                path,mtime_ns,size,indexed_at\n            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)\n            ON CONFLICT(source_name,source_key) DO UPDATE SET\n                root=excluded.root,\n                source_version=excluded.source_version,\n                map_stem=excluded.map_stem,\n                zone_name=excluded.zone_name,\n                layer=excluded.layer,\n                path=excluded.path,\n                mtime_ns=excluded.mtime_ns,\n                size=excluded.size,\n                indexed_at=excluded.indexed_at\n            """,\n            (\n                source_name, source_name, source_version, source_key, map_stem, zone_name,\n                int(layer), portable_path, int(mtime_ns), int(size), now,\n            ),\n        )\n        source_id = int(\n            self.db.conn.execute(\n                "SELECT id FROM map_sources WHERE source_name=? AND source_key=?",\n                (source_name, source_key),\n            ).fetchone()[0]\n        )\n        return source_id, False\n'''
    replace_once(path, old_method, new_method)

    replace_once(
        path,
        '''    def index_root(\n        self,\n        root: str | Path,\n        *,\n        progress: Callable[[str, int, int, str], None] | None = None,\n    ) -> MapIndexStats:\n        """Incrementally index map labels without monopolizing SQLite.\n\n        Map files are parsed before a write transaction begins. Changed files are\n        committed one file at a time, and reconciliation writes are chunked so the UI\n        connection can continue saving settings, view state, and log-derived state.\n        """\n        root_path = Path(root).resolve()\n        if not root_path.is_dir():\n            raise FileNotFoundError(root_path)\n        root_s = str(root_path)\n        zone_by_stem = self._zone_map()''',
        '''    def index_root(\n        self,\n        root: str | Path,\n        *,\n        source_name: str | None = None,\n        source_version: str = "",\n        progress: Callable[[str, int, int, str], None] | None = None,\n    ) -> MapIndexStats:\n        """Explicitly build or refresh one portable map-catalog source.\n\n        The filesystem root is only an input to this build operation.  Persisted map\n        identity uses ``source_name`` + a relative ``source_key`` so a catalog can be\n        shipped to another machine without retaining builder-local absolute paths.\n        """\n        root_path = Path(root).resolve()\n        if not root_path.is_dir():\n            raise FileNotFoundError(root_path)\n        catalog_source_name = " ".join((source_name or root_path.name or "Map Pack").split()).strip()\n        catalog_source_version = str(source_version or "")\n        zone_by_stem = self._zone_map()''',
    )

    replace_once(path, '        seen_paths: set[str] = set()\n', '        seen_keys: set[str] = set()\n')

    replace_once(
        path,
        '''        for index, (map_stem, layer_no, path, zone_name) in enumerate(candidates, start=1):\n            seen_paths.add(str(path))\n            stat = path.stat()\n            existing = self.db.conn.execute(\n                "SELECT * FROM map_sources WHERE path=?", (str(path),)\n            ).fetchone()\n            unchanged = bool(\n                existing\n                and int(existing["mtime_ns"] or 0) == int(stat.st_mtime_ns)\n                and int(existing["size"] or 0) == int(stat.st_size)\n                and str(existing["zone_name"] or "") == zone_name\n                and str(existing["root"] or "") == root_s\n            )''',
        '''        for index, (map_stem, layer_no, path, zone_name) in enumerate(candidates, start=1):\n            source_key = path.relative_to(root_path).as_posix()\n            seen_keys.add(source_key)\n            stat = path.stat()\n            existing = self.db.conn.execute(\n                "SELECT * FROM map_sources WHERE source_name=? AND source_key=?",\n                (catalog_source_name, source_key),\n            ).fetchone()\n            unchanged = bool(\n                existing\n                and int(existing["mtime_ns"] or 0) == int(stat.st_mtime_ns)\n                and int(existing["size"] or 0) == int(stat.st_size)\n                and str(existing["zone_name"] or "") == zone_name\n                and str(existing["source_version"] or "") == catalog_source_version\n            )''',
    )

    replace_once(
        path,
        '''                source_id, _ = self._upsert_source(\n                    root=root_s,\n                    map_stem=map_stem,\n                    zone_name=zone_name,\n                    layer=layer_no,\n                    path=path,\n                    mtime_ns=stat.st_mtime_ns,\n                    size=stat.st_size,\n                )''',
        '''                source_id, _ = self._upsert_source(\n                    source_name=catalog_source_name,\n                    source_version=catalog_source_version,\n                    source_key=source_key,\n                    map_stem=map_stem,\n                    zone_name=zone_name,\n                    layer=layer_no,\n                    mtime_ns=stat.st_mtime_ns,\n                    size=stat.st_size,\n                )''',
    )

    replace_once(
        path,
        '''        stale = self.db.conn.execute(\n            "SELECT id,path FROM map_sources WHERE root=?", (root_s,)\n        ).fetchall()\n        with self.db.batch():\n            for row in stale:\n                if str(row["path"]) not in seen_paths:\n                    self.db.conn.execute("DELETE FROM map_sources WHERE id=?", (int(row["id"]),))\n                    stale_removed += 1\n            self.db.set_meta("map_catalog_root", root_s)\n            if stale_removed:\n                self.db.set_meta("map_links_dirty", "1")''',
        '''        stale = self.db.conn.execute(\n            "SELECT id,source_key FROM map_sources WHERE source_name=?", (catalog_source_name,)\n        ).fetchall()\n        with self.db.batch():\n            for row in stale:\n                if str(row["source_key"]) not in seen_keys:\n                    self.db.conn.execute("DELETE FROM map_sources WHERE id=?", (int(row["id"]),))\n                    stale_removed += 1\n            self.db.set_meta("map_catalog_last_source", catalog_source_name)\n            self.db.set_meta(\n                f"map_catalog_source_version::{normalize_name(catalog_source_name)}",\n                catalog_source_version,\n            )\n            if stale_removed:\n                self.db.set_meta("map_links_dirty", "1")''',
    )

    replace_once(
        path,
        '''        label_count = int(self.db.conn.execute(\n            "SELECT COUNT(*) FROM map_labels ml JOIN map_sources ms ON ms.id=ml.source_id WHERE ms.root=?",\n            (root_s,),\n        ).fetchone()[0])''',
        '''        label_count = int(self.db.conn.execute(\n            "SELECT COUNT(*) FROM map_labels ml JOIN map_sources ms ON ms.id=ml.source_id "\n            "WHERE ms.source_name=?",\n            (catalog_source_name,),\n        ).fetchone()[0])''',
    )

    replace_once(
        path,
        '''            SELECT ml.*, ms.path\n            FROM map_labels ml JOIN map_sources ms ON ms.id=ml.source_id''',
        '''            SELECT ml.*, ms.path, ms.source_name, ms.source_version, ms.source_key\n            FROM map_labels ml JOIN map_sources ms ON ms.id=ml.source_id''',
    )
    replace_once(
        path,
        '''            SELECT ml.*,ms.path FROM map_labels ml\n            JOIN map_sources ms ON ms.id=ml.source_id''',
        '''            SELECT ml.*,ms.path,ms.source_name,ms.source_version,ms.source_key FROM map_labels ml\n            JOIN map_sources ms ON ms.id=ml.source_id''',
    )

    replace_once(
        path,
        '''            path=str(row["path"]),\n            layer=int(row["layer"]),''',
        '''            path=str(row["path"]),\n            source_name=str(row["source_name"] or "Map Pack"),\n            source_version=str(row["source_version"] or ""),\n            source_key=str(row["source_key"] or ""),\n            layer=int(row["layer"]),''',
    )

    replace_once(
        path,
        '''            SELECT ml.*,ms.path FROM map_labels ml\n            JOIN map_sources ms ON ms.id=ml.source_id\n            WHERE ml.linked_entity_id=?''',
        '''            SELECT ml.*,ms.path,ms.source_name,ms.source_version,ms.source_key FROM map_labels ml\n            JOIN map_sources ms ON ms.id=ml.source_id\n            WHERE ml.linked_entity_id=?''',
    )

    replace_once(path, '    lines = ["", "Local map evidence:"]', '    lines = ["", "Map catalog evidence:"]')
    replace_once(
        path,
        '''            f"layer {row['layer']} | {Path(str(row['path'])).name}:{row['source_line']}"''',
        '''            f"layer {row['layer']} | {row['source_name']}:{row['source_key']}:{row['source_line']}"''',
    )


def patch_map_view() -> None:
    path = ROOT / "eqquest" / "mapview.py"
    replace_once(path, '        self.after(700, self.ensure_map_catalog)\n', '')
    replace_once(path, '        self.after(50, self.ensure_map_catalog)\n', '')
    replace_once(
        path,
        '        self.map_status.set(f"Map pack: {Path(root).name} | {count} base map files")\n',
        '        self.map_status.set(f"Map pack: {Path(root).name} | {count} base map files | catalog refresh is manual")\n',
    )
    replace_once(
        path,
        '        self.lookup_status.set("Updating local map catalog in background…")\n',
        '        self.lookup_status.set("Manually refreshing the EverQuestie map catalog…")\n',
    )
    replace_once(
        path,
        '''                stats = MapCatalog(thread_db).index_root(root, progress=progress)''',
        '''                stats = MapCatalog(thread_db).index_root(\n                    root, source_name=Path(root).name, progress=progress\n                )''',
    )
    replace_once(
        path,
        '''                f"Map file: {Path(hit.path).name}",\n                f"Map source line: {hit.source_line}",''',
        '''                f"Map catalog source: {hit.source_name}"\n                + (f" {hit.source_version}" if hit.source_version else ""),\n                f"Map file key: {hit.source_key or Path(hit.path).name}",\n                f"Map source line: {hit.source_line}",''',
    )
    replace_once(path, '                    "Local map evidence only — no normalized EverQuestie knowledge entity is linked yet.",', '                    "Map catalog evidence only — no normalized EverQuestie knowledge entity is linked yet.",')

    old_open = '''    def _open_lookup_on_map(self, _event=None) -> None:\n        hit = self._lookup_selected_map_hit\n        if isinstance(hit, MapCatalogHit):\n            self.load_map(hit.path)\n            self.after(80, lambda: self._center_map_point(hit.x, hit.y))\n            self.lookup_status.set(f"Opened {hit.zone_name or hit.map_stem} at {hit.text}")\n            return\n'''
    new_open = '''    def _catalog_hit_local_path(self, hit: MapCatalogHit) -> Path | None:\n        root = self.map_root.get().strip()\n        if root and hit.source_key:\n            candidate = Path(root) / Path(hit.source_key)\n            if candidate.is_file():\n                return candidate\n        legacy = Path(hit.path)\n        if legacy.is_file():\n            return legacy\n        if root:\n            filename = f"{hit.map_stem}.txt" if hit.layer == 0 else f"{hit.map_stem}_{hit.layer}.txt"\n            candidate = Path(root) / filename\n            if candidate.is_file():\n                return candidate\n        return None\n\n    def _open_lookup_on_map(self, _event=None) -> None:\n        hit = self._lookup_selected_map_hit\n        if isinstance(hit, MapCatalogHit):\n            local_path = self._catalog_hit_local_path(hit)\n            if local_path is None:\n                self.lookup_status.set(\n                    f"Catalog hit found for {hit.text}, but that map file is not present in the selected local map pack."\n                )\n                return\n            self.load_map(local_path)\n            self.after(80, lambda: self._center_map_point(hit.x, hit.y))\n            self.lookup_status.set(f"Opened {hit.zone_name or hit.map_stem} at {hit.text}")\n            return\n'''
    replace_once(path, old_open, new_open)

    replace_once(
        ROOT / "eqquest" / "app.py",
        '''            "  Allakhazam: quest/world/community evidence when explicitly imported from the local mirror",\n            "  Good/Brewall/EQ maps: selected map geometry and POIs",''',
        '''            "  Map catalog: prebuilt EverQuestie knowledge; local map files are rendering assets",\n            "  Allakhazam DB/Wiki: optional future enrichment when a mirror is available",''',
    )


def write_builder_tool() -> None:
    path = ROOT / "tools" / "build_map_catalog.py"
    path.write_text(textwrap.dedent('''\
        from __future__ import annotations

        import argparse
        from pathlib import Path

        from eqquest.db import Database
        from eqquest.map_catalog import MapCatalog


        def main() -> int:
            parser = argparse.ArgumentParser(
                description="Explicitly build or refresh a portable EverQuestie map catalog."
            )
            parser.add_argument("--db", required=True, help="EverQuestie knowledge SQLite database")
            parser.add_argument("--maps", required=True, help="Good/Brewall/EverQuest map-pack root")
            parser.add_argument(
                "--source-name",
                required=True,
                help="Stable catalog source name, e.g. Brewall or Good",
            )
            parser.add_argument(
                "--source-version",
                default="",
                help="Optional map-pack version/date retained in catalog provenance",
            )
            args = parser.parse_args()

            db_path = Path(args.db).expanduser().resolve()
            maps = Path(args.maps).expanduser().resolve()
            db = Database(db_path)
            try:
                def progress(stage: str, current: int, total: int, detail: str) -> None:
                    print(f"[{stage}] {current}/{total} {detail}")

                stats = MapCatalog(db).index_root(
                    maps,
                    source_name=args.source_name,
                    source_version=args.source_version,
                    progress=progress,
                )
                print(
                    f"catalog ready: {stats.base_maps} base maps, {stats.labels} labels, "
                    f"{stats.linked} linked, {stats.ambiguous} ambiguous, {stats.unresolved} unresolved"
                )
                return 0
            finally:
                db.close()


        if __name__ == "__main__":
            raise SystemExit(main())
        '''), encoding="utf-8")


def write_tests() -> None:
    path = ROOT / "tests" / "test_map_catalog.py"
    text = path.read_text(encoding="utf-8")
    replace_once(
        path,
        '''        stats = self.catalog.index_root(self.root)\n        self.assertEqual(stats.base_maps, 1)\n        self.assertEqual(stats.labels, 2)''',
        '''        stats = self.catalog.index_root(self.root, source_name="Brewall", source_version="2026-08")\n        self.assertEqual(stats.base_maps, 1)\n        self.assertEqual(stats.labels, 2)''',
    )
    replace_once(
        path,
        '''        self.assertTrue(Path(hits[0].path).name.startswith("stonehive"))''',
        '''        self.assertEqual(hits[0].source_name, "Brewall")\n        self.assertEqual(hits[0].source_version, "2026-08")\n        self.assertEqual(hits[0].source_key, "stonehive_1.txt")\n        self.assertTrue(hits[0].path.startswith("mapcatalog://"))\n        self.assertNotIn(str(self.root), hits[0].path)''',
    )

    marker = '''    def test_search_is_read_only_when_links_are_dirty(self):\n        self.catalog.index_root(self.root)\n        self.db.set_meta("map_links_dirty", "1")\n        hits = self.catalog.search("Warwing")\n        self.assertTrue(hits)\n        self.assertEqual(self.db.get_meta("map_links_dirty"), "1")\n'''
    addition = marker + '''\n    def test_same_catalog_source_can_move_without_duplicate_rows(self):\n        self.catalog.index_root(self.root, source_name="Brewall")\n        moved = Path(self.tmp.name) / "moved_maps"\n        moved.mkdir()\n        for source in self.root.glob("*.txt"):\n            (moved / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")\n        self.catalog.index_root(moved, source_name="Brewall")\n        sources = self.db.conn.execute(\n            "SELECT source_name,source_key,path,root FROM map_sources ORDER BY source_key"\n        ).fetchall()\n        self.assertEqual(len(sources), 2)\n        self.assertEqual({row["source_name"] for row in sources}, {"Brewall"})\n        self.assertEqual({row["root"] for row in sources}, {"Brewall"})\n        self.assertTrue(all(str(row["path"]).startswith("mapcatalog://") for row in sources))\n        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM map_labels").fetchone()[0], 2)\n'''
    replace_once(path, marker, addition)

    compatibility = ROOT / "tests" / "test_source_compatibility.py"
    compatibility.write_text(textwrap.dedent('''\
        import tempfile
        import unittest
        from pathlib import Path

        from eqquest.db import Database


        class FutureSourceCompatibilityTests(unittest.TestCase):
            def test_future_allakhazam_identity_can_enrich_existing_entity(self):
                with tempfile.TemporaryDirectory() as td:
                    db = Database(Path(td) / "knowledge.sqlite3")
                    try:
                        client_source = db.upsert_source_page(
                            url="eqclient://Resources/ZoneNames.txt",
                            title="ZoneNames",
                            entity_type="zone",
                            sha256="client",
                            plain_text="Stone Hive",
                            raw_html="",
                            source_name="EverQuest Client",
                            source_kind="builder_input",
                            source_key="Resources/ZoneNames.txt",
                        )
                        entity_id = db.upsert_entity(
                            kind="zone",
                            name="Stone Hive",
                            source_page_id=client_source,
                            source_url="eqclient://Resources/ZoneNames.txt",
                            external_id="123",
                            external_namespace="eqclient:zone",
                            merge_by_name=True,
                        )

                        future_source = db.upsert_source_page(
                            url="https://everquest.allakhazam.com/db/zone.html?zstrat=456",
                            title="Stone Hive",
                            entity_type="zone",
                            sha256="future",
                            plain_text="future mirror evidence",
                            raw_html="<html></html>",
                            source_name="Allakhazam",
                            source_kind="builder_mirror",
                            source_key="zone:456",
                        )
                        db.link_entity_source(entity_id, future_source, role="evidence")
                        db.add_external_id(
                            entity_id,
                            "allakhazam:zone",
                            "zone:456",
                            source_page_id=future_source,
                        )

                        self.assertEqual(
                            int(db.entity_by_namespaced_external_id("eqclient:zone", "123")["id"]),
                            entity_id,
                        )
                        self.assertEqual(
                            int(db.entity_by_namespaced_external_id("allakhazam:zone", "zone:456")["id"]),
                            entity_id,
                        )
                        self.assertEqual(
                            {row["source_name"] for row in db.sources_for_entity(entity_id)},
                            {"EverQuest Client", "Allakhazam"},
                        )
                    finally:
                        db.close()


        if __name__ == "__main__":
            unittest.main()
        '''), encoding="utf-8")


def write_docs() -> None:
    distribution = ROOT / "docs" / "DATABASE_DISTRIBUTION.md"
    distribution.write_text(textwrap.dedent('''\
        # EverQuestie database distribution architecture

        ## Release principle

        A normal EverQuestie user must not need `everquest1-mcp`, Node.js, a source checkout, a website mirror, or a local database compilation step to use the shipped knowledge base.

        Source adapters are **builder/developer inputs**. EverQuestie owns the normalized schema and release artifacts.

        ## Target release layout

        EverQuestie is moving toward two SQLite roles:

        1. **Shipped knowledge snapshot** — versioned, read-only/read-mostly EverQuestie knowledge produced by the release pipeline.
        2. **User state database** — writable local state such as observed log events, tracked quest progress, settings, map-root selection, manual bindings, view state, and user overrides.

        Replacing a shipped knowledge snapshot must never delete or recreate player state.

        The current v0.13 development database still combines these roles in one SQLite file. Do not silently overwrite that file with a release snapshot until the content/user-state split or a safe upgrader exists.

        ## Knowledge inputs and future providers

        Development must proceed without waiting for the Allakhazam DB or Wiki mirrors. Current builders can populate knowledge from the installed EverQuest client, map packs, MCP-derived local snapshots, and any other approved deterministic source available to the project.

        Allakhazam DB and Wiki are **optional future enrichment providers**. When those mirrors become available they plug into the same generic provenance and identity model (`source_pages`, `entity_sources`, and namespaced `entity_external_ids`) rather than requiring a new runtime database design.

        The project owner has confirmed authority to incorporate and distribute information gathered from the approved project resources. Provenance is retained for reconciliation, auditing, refreshes, and conflict analysis; it is not a runtime distribution gate.

        ## Map catalog placement

        The normalized global map catalog belongs in the shipped knowledge snapshot.

        Catalog construction is performed once by the builder or by an explicit manual developer action. Normal application startup must not crawl or rebuild Good/Brewall/EverQuest map packs.

        `map_sources` and `map_labels` persist portable map-pack identity (`source_name`, optional `source_version`, and a relative `source_key`). They must not require a builder-machine absolute path after the snapshot is built.

        A user's selected map directory is different: it is a local rendering asset and belongs in writable user state/settings. At runtime EverQuestie can resolve a catalog `source_key` against that local map root when the matching map file is present.

        This separation lets the shipped DB answer global map/POI searches even when a player has not locally indexed anything.

        ## Runtime behavior

        Normal gameplay remains local and deterministic. Runtime EverQuestie should:

        - read the shipped knowledge snapshot locally;
        - write player/session state only to the user's local database;
        - use the prebuilt global map catalog for map evidence/search;
        - use a selected local Good/Brewall/EQ map directory only for rendering and optional user overrides;
        - never require MCP, Allakhazam DB, or Allakhazam Wiki to be present;
        - never perform a hidden source rebuild on startup;
        - never make background website requests.

        Explicit online Search remains a separate user-triggered feature.

        ## Release build pipeline

        Before a packaged release, the reproducible builder should:

        1. create a fresh EverQuestie knowledge database;
        2. import all currently available approved source inventories (with Allakhazam DB/Wiki optional);
        3. build/refresh the global map catalog explicitly;
        4. run identity and relationship reconciliation;
        5. rebuild FTS;
        6. run database integrity and identity audits;
        7. strip user/session state and builder-local paths;
        8. record source versions, build timestamp, schema version, and knowledge snapshot version;
        9. `VACUUM`/optimize the SQLite file;
        10. run the complete regression suite against that snapshot;
        11. package the snapshot with the Windows application.

        The installer/first-run path creates the writable user-state database automatically. Users should not see MCP setup, mirror setup, map catalog compilation, or other builder infrastructure as prerequisites.

        ## Development tooling

        MCP/client compilers, map-catalog builders, Allakhazam importers, Wiki importers, and future source adapters may remain available as developer/advanced tooling. They enrich the same EverQuestie-owned knowledge model; none is individually required for the application to function.
        '''), encoding="utf-8")

    tools_readme = ROOT / "tools" / "README.md"
    tools_readme.write_text(textwrap.dedent('''\
        # EverQuestie tools

        These commands are builder/developer tooling. Normal EverQuestie users should not need them for a packaged release.

        ## Build or refresh the global map catalog

        Run explicitly from the repository root:

        ```powershell
        python .\\tools\\build_map_catalog.py --db .\\build\\everquestie-knowledge.sqlite3 --maps "C:\\EQ Maps\\Brewall" --source-name Brewall --source-version 2026-08
        ```

        Run the command once per approved map pack/source. Catalog rows store portable relative map keys, not builder-machine file paths, so the database can later ship with EverQuestie. The user's local map root is only needed when opening/rendering the corresponding map file.

        ## MCP setup

        MCP is builder/developer infrastructure. If a knowledge build currently needs it, from the EverQuestie repository root on Windows run:

        ```powershell
        .\\tools\\setup_mcp_submodule.cmd
        ```

        or directly:

        ```powershell
        .\\tools\\setup_mcp_submodule.ps1
        ```

        The helper initializes the pinned `third_party/everquest1-mcp` Git submodule, runs `npm install`, and builds the MCP project. `-Update` fetches upstream metadata while retaining the commit pinned by the EverQuestie checkout unless `-Ref <tag-or-commit>` is supplied.
        '''), encoding="utf-8")


def main() -> None:
    patch_map_catalog()
    patch_map_view()
    write_builder_tool()
    write_tests()
    write_docs()
    print("portable/manual map catalog patch applied")


if __name__ == "__main__":
    main()
