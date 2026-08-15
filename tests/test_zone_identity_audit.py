from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from eqquest.zone_identity_audit import ZoneIdentityAudit, zone_identity_audit_text


class ZoneIdentityAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "knowledge.sqlite3")

        client_source = self.db.upsert_source_page(
            url="eqclient://zones",
            title="ZoneNames",
            entity_type="zone",
            sha256="client-zones",
            plain_text="",
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="Resources/ZoneNames.txt",
        )
        provider_source = self.db.upsert_source_page(
            url="https://everquest.allakhazam.com/db/zone.html?zstrat=1",
            title="Stone Hive",
            entity_type="zone",
            sha256="alla-stone",
            plain_text="",
            raw_html="",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key="zone:1",
        )

        self.stone_client = self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            source_page_id=client_source,
            source_url="eqclient://zones#396",
            external_id="396",
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )
        self.stone_provider = self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            source_page_id=provider_source,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=1",
            external_id="zone:1",
            external_namespace="allakhazam:zone",
            merge_by_name=False,
        )

        # A relationship attached to the provider shadow demonstrates that future
        # canonicalization cannot simply delete duplicate entities.
        npc = self.db.upsert_entity(kind="npc", name="A Stone Worker", merge_by_name=True)
        self.db.upsert_relationship(
            self.stone_provider,
            npc,
            "contains",
            evidence="fixture",
        )

        self.db.upsert_entity(
            kind="zone",
            name="Shared Instance",
            external_id="500",
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )
        self.db.upsert_entity(
            kind="zone",
            name="Shared Instance",
            external_id="501",
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )

        self.db.upsert_entity(
            kind="zone",
            name="Historical Zone",
            external_id="zone:10",
            external_namespace="allakhazam:zone",
            merge_by_name=False,
        )
        self.db.upsert_entity(
            kind="zone",
            name="Historical Zone",
            external_id="zone:11",
            external_namespace="allakhazam:zone",
            merge_by_name=False,
        )
        self.db.upsert_entity(
            kind="zone",
            name="Provider Only Unique",
            external_id="zone:12",
            external_namespace="allakhazam:zone",
            merge_by_name=False,
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_classifies_client_authority_multi_client_and_provider_only_groups(self):
        summary = ZoneIdentityAudit(self.db).summary()
        self.assertEqual(summary.zone_entities, 7)
        self.assertEqual(summary.name_groups, 4)
        self.assertEqual(summary.client_backed_entities, 3)
        self.assertEqual(summary.provider_only_entities, 4)
        self.assertEqual(summary.duplicate_name_groups, 3)
        self.assertEqual(summary.entities_in_duplicate_groups, 6)
        self.assertEqual(summary.client_authority_duplicate_groups, 1)
        self.assertEqual(summary.client_authority_shadow_entities, 1)
        self.assertEqual(summary.multi_client_collision_groups, 1)
        self.assertEqual(summary.provider_only_duplicate_groups, 1)
        self.assertEqual(summary.provider_only_unique_groups, 1)
        self.assertEqual(summary.duplicate_groups_with_downstream_refs, 1)

        by_name = {group.display_name: group for group in summary.groups}
        stone = by_name["Stone Hive"]
        self.assertEqual(stone.classification, "client_authority_duplicate")
        self.assertEqual(len(stone.client_members), 1)
        self.assertEqual(len(stone.non_client_members), 1)
        provider_member = next(member for member in stone.members if not member.client_backed)
        self.assertEqual(provider_member.relationships_out, 1)
        self.assertGreater(provider_member.downstream_refs, 0)
        self.assertTrue(any("Allakhazam" in source for source in provider_member.sources))

        shared = by_name["Shared Instance"]
        self.assertEqual(shared.classification, "multi_client_collision")
        self.assertEqual(len(shared.client_members), 2)

        historical = by_name["Historical Zone"]
        self.assertEqual(historical.classification, "provider_only_duplicate")
        self.assertEqual(len(historical.client_members), 0)

    def test_example_limit_does_not_change_summary_counts(self):
        full = ZoneIdentityAudit(self.db).summary(duplicate_example_limit=100)
        limited = ZoneIdentityAudit(self.db).summary(duplicate_example_limit=1)
        self.assertEqual(limited.duplicate_name_groups, full.duplicate_name_groups)
        self.assertEqual(limited.client_authority_duplicate_groups, full.client_authority_duplicate_groups)
        self.assertEqual(len(limited.groups), 1)

    def test_human_report_explains_join_vs_merge_boundary(self):
        text = zone_identity_audit_text(self.db)
        self.assertIn("EverQuestie canonical zone identity audit", text)
        self.assertIn("Unique-client authority duplicate groups: 1", text)
        self.assertIn("Multi-client same-name collision groups: 1", text)
        self.assertIn("not automatically merge-safe", text)
        self.assertIn("Stone Hive", text)
        self.assertIn("Allakhazam", text)


if __name__ == "__main__":
    unittest.main()
