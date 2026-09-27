import sqlite3
import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from eqquest.knowledge_snapshot import RUNTIME_SOURCE_TEXT_LIMIT, create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog


class KnowledgeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.working = self.root / "working.sqlite3"
        self.output = self.root / "everquestie-knowledge.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def _populate_working_db(self) -> None:
        db = Database(self.working)
        try:
            source_id = db.upsert_source_page(
                url="eqclient+mcp://save_data_snapshot",
                title="EverQuest local data inventory",
                entity_type="multi",
                sha256="snapshot-hash",
                plain_text='{"eqPath":"C:\\\\EverQuest","systems":{}}',
                raw_html="",
                source_name="EverQuest Client via everquest1-mcp",
                source_kind="mcp_local_snapshot",
                source_key="save_data_snapshot",
                source_version="1.2.3 @ abcdef",
                local_path=r"C:\EverQuest",
            )
            quest_id = db.upsert_entity(
                kind="quest",
                name="Snapshot Test Quest",
                source_page_id=source_id,
                source_url="eqclient+mcp://save_data_snapshot",
                external_id="500",
                external_namespace="eqclient:quest",
                notes="Knowledge that should remain in the release snapshot.",
            )
            db.upsert_source_page(
                url="https://everquest.allakhazam.com/db/quest.html?quest=999999",
                title="Archived Mirror Quest",
                entity_type="quest",
                sha256="allakhazam-raw-html",
                plain_text=(
                    "Readable source text remains available at runtime. "
                    + ("source-body-" * 3000)
                ),
                raw_html="<html><body>builder-only raw mirror page</body></html>",
                source_name="Allakhazam",
                source_kind="local_mirror",
                source_key="quest/999999.html",
                source_version="mirror-test",
            )
            db.conn.execute(
                "INSERT INTO tracked_quests(quest_entity_id,tracked_at,active_step) VALUES(?,?,?)",
                (quest_id, "2026-08-14T00:00:00", 1),
            )
            db.conn.execute(
                "INSERT INTO quest_progress(quest_entity_id,step_order,progress_count,complete) "
                "VALUES(?,?,?,?)",
                (quest_id, 1, 3, 0),
            )
            db.conn.execute(
                "INSERT INTO observed_events(kind,fields_json,raw) VALUES(?,?,?)",
                ("loot", "{}", "You have looted a test item."),
            )
            db.set_meta("eq_game_path", r"C:\EverQuest")
            db.set_meta("map_root", r"C:\EverQuest\maps\Brewall")
            db.set_meta("some_runtime_view_state", "expanded")
            db.set_meta("eq_mcp_version", "1.2.3")
            db.set_meta("approved_zone_alias_supplement_count", "0")
            db.set_meta("approved_zone_alias_count", "0")
            db.set_meta("approved_travel_supplement_count", "0")
            db.set_meta("approved_travel_supplement_edge_count", "0")
            db.set_meta("approved_travel_supplement_debug_path", r"C:\repo\travel")
            db.conn.commit()
        finally:
            db.close()

    def test_snapshot_is_a_copy_and_strips_runtime_state(self):
        self._populate_working_db()

        report = create_knowledge_snapshot(
            self.working,
            self.output,
            snapshot_version="2026.08.14-test",
        )
        self.assertEqual(report.path, self.output.resolve())
        self.assertEqual(report.snapshot_version, "2026.08.14-test")
        self.assertEqual(report.schema_version, "1")
        self.assertEqual(report.stripped_user_rows["tracked_quests"], 1)
        self.assertEqual(report.stripped_user_rows["quest_progress"], 1)
        self.assertEqual(report.stripped_user_rows["observed_events"], 1)
        self.assertEqual(report.stripped_source_paths, 1)
        self.assertEqual(report.stripped_builder_payloads, 2)
        self.assertEqual(report.diagnostics["integrity"], "ok")
        reviewed = report.diagnostics["reviewed_release_inputs"]
        self.assertEqual(reviewed["status"], "ok")
        self.assertEqual(reviewed["actual"]["zone_aliases"], 0)
        self.assertEqual(reviewed["actual"]["travel_edges"], 0)

        # The builder/working DB is deliberately untouched.
        working = sqlite3.connect(self.working)
        try:
            self.assertEqual(working.execute("SELECT COUNT(*) FROM tracked_quests").fetchone()[0], 1)
            self.assertEqual(working.execute("SELECT COUNT(*) FROM observed_events").fetchone()[0], 1)
            self.assertEqual(
                working.execute(
                    "SELECT local_path FROM source_pages WHERE url='eqclient+mcp://save_data_snapshot'"
                ).fetchone()[0],
                r"C:\EverQuest",
            )
            self.assertGreater(
                working.execute(
                    "SELECT length(plain_text) FROM source_pages "
                    "WHERE url='https://everquest.allakhazam.com/db/quest.html?quest=999999'"
                ).fetchone()[0],
                RUNTIME_SOURCE_TEXT_LIMIT,
            )
        finally:
            working.close()

        snapshot = sqlite3.connect(self.output)
        snapshot.row_factory = sqlite3.Row
        try:
            self.assertEqual(snapshot.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(snapshot.execute("PRAGMA journal_mode").fetchone()[0].casefold(), "delete")
            for table in ("tracked_quests", "quest_progress", "observed_events"):
                self.assertEqual(snapshot.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            source = snapshot.execute(
                "SELECT local_path,plain_text,source_name,source_version "
                "FROM source_pages WHERE url='eqclient+mcp://save_data_snapshot'"
            ).fetchone()
            self.assertEqual(source["local_path"], "")
            self.assertEqual(source["plain_text"], "")
            self.assertEqual(source["source_name"], "EverQuest Client via everquest1-mcp")
            self.assertEqual(source["source_version"], "1.2.3 @ abcdef")

            mirror = snapshot.execute(
                "SELECT plain_text,raw_html FROM source_pages "
                "WHERE url='https://everquest.allakhazam.com/db/quest.html?quest=999999'"
            ).fetchone()
            self.assertEqual(len(mirror["plain_text"]), RUNTIME_SOURCE_TEXT_LIMIT)
            self.assertTrue(
                mirror["plain_text"].startswith(
                    "Readable source text remains available at runtime. "
                )
            )
            self.assertEqual(mirror["raw_html"], "")

            meta = dict(snapshot.execute("SELECT key,value FROM app_meta").fetchall())
            self.assertEqual(meta["database_role"], "knowledge_snapshot")
            self.assertEqual(meta["knowledge_schema_version"], "1")
            self.assertEqual(meta["knowledge_snapshot_version"], "2026.08.14-test")
            self.assertEqual(meta["eq_mcp_version"], "1.2.3")
            self.assertEqual(meta["approved_zone_alias_supplement_count"], "0")
            self.assertEqual(meta["approved_zone_alias_count"], "0")
            self.assertEqual(meta["approved_travel_supplement_count"], "0")
            self.assertEqual(meta["approved_travel_supplement_edge_count"], "0")
            self.assertNotIn("eq_game_path", meta)
            self.assertNotIn("map_root", meta)
            self.assertNotIn("some_runtime_view_state", meta)
            self.assertNotIn("approved_travel_supplement_debug_path", meta)
            self.assertEqual(meta["fts_dirty"], "0")
        finally:
            snapshot.close()

    def test_nonportable_legacy_map_paths_block_release(self):
        db = Database(self.working)
        try:
            MapCatalog(db)
            db.conn.execute(
                """
                INSERT INTO map_sources(
                    root,source_name,source_key,map_stem,layer,path,indexed_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    r"C:\maps\Brewall",
                    "Brewall",
                    r"C:\maps\Brewall\qeynos.txt",
                    "qeynos",
                    0,
                    r"C:\maps\Brewall\qeynos.txt",
                    "2026-08-14T00:00:00",
                ),
            )
            db.conn.commit()
        finally:
            db.close()

        with self.assertRaisesRegex(ValueError, "not portable"):
            create_knowledge_snapshot(
                self.working,
                self.output,
                snapshot_version="bad-map-test",
            )
        self.assertFalse(self.output.exists())

    def test_output_must_be_separate_from_working_db(self):
        self._populate_working_db()
        with self.assertRaisesRegex(ValueError, "separate output"):
            create_knowledge_snapshot(
                self.working,
                self.working,
                snapshot_version="same-file-test",
            )


if __name__ == "__main__":
    unittest.main()
