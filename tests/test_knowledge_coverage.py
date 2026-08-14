import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from eqquest.knowledge_coverage import (
    knowledge_normalization_coverage,
    normalization_coverage_text,
    provider_normalization_coverage,
)
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase


class KnowledgeNormalizationCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "working.sqlite3"
        self.snapshot_path = self.root / "everquestie-knowledge.sqlite3"
        self.state_path = self.root / "everquestie-user.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def _populate(self) -> None:
        db = Database(self.db_path)
        try:
            quest_url = "https://everquest.allakhazam.com/db/quest.html?quest=1"
            quest_page = db.upsert_source_page(
                url=quest_url,
                title="Coverage Quest",
                entity_type="quest",
                sha256="quest-hash",
                plain_text="Coverage quest source",
                raw_html="<html></html>",
                source_name="Allakhazam",
                source_kind="local_mirror",
                source_key="quest:1",
                local_path=r"C:\mirror\quest1.html",
            )
            # Persist a second mirror source page with no normalized derivative. This
            # models helper/index material or a source record awaiting a richer parser.
            db.upsert_source_page(
                url="https://everquest.allakhazam.com/search.html?q=coverage",
                title="Coverage Search",
                entity_type=None,
                sha256="search-hash",
                plain_text="Search helper page",
                raw_html="<html></html>",
                source_name="Allakhazam",
                source_kind="local_mirror",
                source_key="search:coverage",
                local_path=r"C:\mirror\search.html",
            )

            quest_id = db.upsert_entity(
                kind="quest",
                name="Coverage Quest",
                source_page_id=quest_page,
                source_url=quest_url,
                external_id="quest:1",
                notes="Structured quest fixture.",
            )
            npc_url = "https://everquest.allakhazam.com/db/npc.html?id=2"
            npc_id = db.upsert_entity(
                kind="npc",
                name="Coverage NPC",
                source_page_id=quest_page,
                source_url=npc_url,
                external_id="npc:2",
                notes="Structured relationship target fixture.",
            )
            db.add_alias(
                quest_id,
                "Short Coverage Quest",
                alias_type="quest_short_name",
                source_page_id=quest_page,
            )
            db.upsert_relationship(
                quest_id,
                npc_id,
                "started_by",
                source_page_id=quest_page,
                evidence="Quest Started By: Coverage NPC",
            )
            db.add_location(
                npc_id,
                zone_entity_id=None,
                y=20.0,
                x=10.0,
                z=5.0,
                label="Coverage spawn",
                source_page_id=quest_page,
                evidence="/loc 20, 10, 5",
            )
            db.add_quest_step(
                quest_id,
                1,
                "Speak with Coverage NPC",
                source_page_id=quest_page,
            )
            db.upsert_entity_detail(
                quest_id,
                source_page_id=quest_page,
                detail_text="Coverage quest detail",
                detail_json={"fixture": True},
            )

            skill_page = db.upsert_source_page(
                url="eqclient://Resources/skillcaps.txt",
                title="EverQuest Resources/skillcaps.txt",
                entity_type="skill_cap",
                sha256="skill-hash",
                plain_text="1^0^1^10\n1^0^2^15",
                raw_html="",
                source_name="EverQuest Client",
                source_kind="local_game_files",
                source_key="Resources/skillcaps.txt",
                local_path=r"C:\EverQuest\Resources\skillcaps.txt",
            )
            db.replace_skill_caps(
                skill_page,
                [
                    (1, 0, 1, 10),
                    (1, 0, 2, 15),
                ],
            )
        finally:
            db.close()

    def test_provider_coverage_distinguishes_captured_and_normalized_pages(self):
        self._populate()
        db = Database(self.db_path)
        try:
            coverage = provider_normalization_coverage(
                db, "Allakhazam", "local_mirror"
            )
        finally:
            db.close()

        self.assertEqual(coverage.source_pages, 2)
        self.assertEqual(coverage.classified_pages, 1)
        self.assertEqual(coverage.unclassified_pages, 1)
        self.assertEqual(coverage.normalized_pages, 1)
        self.assertEqual(coverage.unnormalized_pages, 1)
        self.assertEqual(coverage.normalized_fraction, 0.5)
        self.assertEqual(coverage.entity_links, 2)
        self.assertEqual(coverage.primary_entity_links, 2)
        self.assertEqual(coverage.external_ids, 2)
        self.assertEqual(coverage.aliases, 1)
        self.assertEqual(coverage.relationships, 1)
        self.assertEqual(coverage.locations, 1)
        self.assertEqual(coverage.quest_steps, 1)
        self.assertEqual(coverage.details, 1)
        self.assertEqual(coverage.support_rows, 0)
        self.assertEqual(dict(coverage.page_types), {"quest": 1, "(unclassified)": 1})
        self.assertEqual(dict(coverage.entity_kinds), {"npc": 1, "quest": 1})
        self.assertEqual(dict(coverage.relation_types), {"started_by": 1})

    def test_support_table_source_is_normalized_without_relationships(self):
        self._populate()
        db = Database(self.db_path)
        try:
            coverage = provider_normalization_coverage(
                db, "EverQuest Client", "local_game_files"
            )
        finally:
            db.close()

        self.assertEqual(coverage.source_pages, 1)
        self.assertEqual(coverage.classified_pages, 1)
        self.assertEqual(coverage.normalized_pages, 1)
        self.assertEqual(coverage.support_rows, 2)
        self.assertEqual(coverage.relationships, 0)
        self.assertEqual(coverage.entity_links, 0)
        self.assertEqual(dict(coverage.page_types), {"skill_cap": 1})

    def test_aggregate_and_text_explain_mirror_file_vs_db_record_boundary(self):
        self._populate()
        db = Database(self.db_path)
        try:
            report = knowledge_normalization_coverage(db)
            text = normalization_coverage_text(db)
        finally:
            db.close()

        self.assertEqual(report.source_pages, 3)
        self.assertEqual(report.normalized_pages, 2)
        self.assertEqual(report.relationships, 1)
        self.assertIsNotNone(report.provider("allakhazam", "LOCAL_MIRROR"))
        self.assertIn("Allakhazam [local_mirror]", text)
        self.assertIn("source pages: 2", text)
        self.assertIn("pages with normalized DB derivatives: 1 (50.0%)", text)
        self.assertIn("relationships / locations / quest steps: 1 / 1 / 1", text)
        self.assertIn("unfinished mirror may contain many more files on disk", text)
        self.assertIn("support-table sources can normalize correctly without producing graph edges", text)

    def test_projection_reads_finalized_immutable_knowledge_through_runtime_database(self):
        self._populate()
        create_knowledge_snapshot(
            self.db_path,
            self.snapshot_path,
            snapshot_version="coverage-runtime-test",
        )
        runtime = RuntimeDatabase(
            self.snapshot_path,
            self.state_path,
            migrate_legacy=False,
        )
        try:
            allakhazam = provider_normalization_coverage(
                runtime, "Allakhazam", "local_mirror"
            )
            eqclient = provider_normalization_coverage(
                runtime, "EverQuest Client", "local_game_files"
            )
        finally:
            runtime.close()

        self.assertEqual(allakhazam.source_pages, 2)
        self.assertEqual(allakhazam.normalized_pages, 1)
        self.assertEqual(allakhazam.relationships, 1)
        self.assertEqual(eqclient.source_pages, 1)
        self.assertEqual(eqclient.normalized_pages, 1)
        self.assertEqual(eqclient.support_rows, 2)


if __name__ == "__main__":
    unittest.main()
