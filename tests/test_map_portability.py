import sqlite3
import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot, snapshot_portability_errors
from eqquest.map_catalog import MapCatalog
from eqquest.map_portability import normalize_legacy_map_sources


class MapPortabilityMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.working = self.root / "working.sqlite3"
        self.output = self.root / "everquestie-knowledge.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _legacy_values():
        map_root = (
            r"C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest"
            r"\maps\Good's Maps"
        )
        map_path = map_root + r"\yxtta_2.txt"
        return map_root, map_path

    def _insert_legacy_source(self, db: Database, *, source_line: int | None = None) -> int:
        map_root, map_path = self._legacy_values()
        cur = db.conn.execute(
            """
            INSERT INTO map_sources(
                root,source_name,source_version,source_key,map_stem,zone_name,layer,
                path,mtime_ns,size,indexed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                map_root,
                "legacy-local",
                "",
                map_path,
                "yxtta",
                "",
                2,
                map_path,
                123,
                456,
                "2026-08-14T00:00:00",
            ),
        )
        source_id = int(cur.lastrowid)
        if source_line is not None:
            db.conn.execute(
                """
                INSERT INTO map_labels(
                    source_id,map_stem,zone_name,layer,source_line,raw_text,clean_text,
                    normalized_text,x,y,z,r,g,b,size
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    source_id,
                    "yxtta",
                    "",
                    2,
                    source_line,
                    "Legacy POI",
                    "Legacy POI",
                    "legacy poi",
                    10.0,
                    20.0,
                    30.0,
                    255,
                    255,
                    255,
                    1,
                ),
            )
        return source_id

    def test_release_migrates_exact_goods_maps_windows_path_on_snapshot_copy(self):
        map_root, map_path = self._legacy_values()
        db = Database(self.working)
        try:
            MapCatalog(db)
            self._insert_legacy_source(db, source_line=17)
            db.conn.commit()
        finally:
            db.close()

        report = create_knowledge_snapshot(
            self.working,
            self.output,
            snapshot_version="legacy-map-portability-test",
        )
        self.assertEqual(report.diagnostics["integrity"], "ok")

        # The builder DB may still be actively receiving mirror/catalog writes. Release
        # finalization therefore migrates only its copied snapshot, never the source DB.
        working = sqlite3.connect(self.working)
        try:
            row = working.execute(
                "SELECT root,source_name,source_key,path FROM map_sources"
            ).fetchone()
            self.assertEqual(row, (map_root, "legacy-local", map_path, map_path))
        finally:
            working.close()

        snapshot_db = Database(self.output)
        try:
            row = snapshot_db.conn.execute(
                "SELECT root,source_name,source_key,path FROM map_sources"
            ).fetchone()
            self.assertEqual(row["root"], "Good's Maps")
            self.assertEqual(row["source_name"], "Good's Maps")
            self.assertEqual(row["source_key"], "yxtta_2.txt")
            self.assertEqual(row["path"], "mapcatalog://goodsmaps/yxtta_2.txt")
            self.assertEqual(
                snapshot_db.conn.execute("SELECT COUNT(*) FROM map_labels").fetchone()[0],
                1,
            )
            self.assertEqual(snapshot_portability_errors(snapshot_db), [])
        finally:
            snapshot_db.close()

    def test_existing_portable_row_wins_without_losing_unique_legacy_labels(self):
        db = Database(self.working)
        try:
            MapCatalog(db)
            portable = db.conn.execute(
                """
                INSERT INTO map_sources(
                    root,source_name,source_version,source_key,map_stem,zone_name,layer,
                    path,mtime_ns,size,indexed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "Good's Maps",
                    "Good's Maps",
                    "current",
                    "yxtta_2.txt",
                    "yxtta",
                    "",
                    2,
                    "mapcatalog://goodsmaps/yxtta_2.txt",
                    999,
                    456,
                    "2026-08-14T01:00:00",
                ),
            )
            portable_id = int(portable.lastrowid)
            db.conn.execute(
                """
                INSERT INTO map_labels(
                    source_id,map_stem,zone_name,layer,source_line,raw_text,clean_text,
                    normalized_text,x,y,z,r,g,b,size
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    portable_id,
                    "yxtta",
                    "",
                    2,
                    1,
                    "Portable POI",
                    "Portable POI",
                    "portable poi",
                    1.0,
                    2.0,
                    3.0,
                    255,
                    255,
                    255,
                    1,
                ),
            )
            self._insert_legacy_source(db, source_line=2)
            db.conn.commit()

            result = normalize_legacy_map_sources(db)
            self.assertEqual(result.normalized, 0)
            self.assertEqual(result.deduplicated, 1)
            rows = db.conn.execute(
                "SELECT id,source_name,source_key,path FROM map_sources"
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(int(rows[0]["id"]), portable_id)
            self.assertEqual(rows[0]["source_name"], "Good's Maps")
            self.assertEqual(rows[0]["source_key"], "yxtta_2.txt")
            lines = [
                int(row[0])
                for row in db.conn.execute(
                    "SELECT source_line FROM map_labels WHERE source_id=? ORDER BY source_line",
                    (portable_id,),
                ).fetchall()
            ]
            self.assertEqual(lines, [1, 2])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
