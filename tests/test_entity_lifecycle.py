from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.entity_lifecycle import (
    entity_expansion_evidence,
    entity_lifecycle_decision,
)
from eqquest.profile_availability import entity_profile_decision, profiled_entity_detail_text
from eqquest.world_profiles import set_active_world_profile


class EntityLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.classic = self.db.upsert_entity(
            kind="zone",
            name="Greater Faydark",
            external_id="54",
            external_namespace="eqclient:zone",
            data={"expansion": "Classic"},
        )
        self.modern = self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            external_id="396",
            external_namespace="eqclient:zone",
            data={"expansion": "The Serpent's Spine"},
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _source(self, key: str, *, kind: str = "local_mirror") -> int:
        return self.db.upsert_source_page(
            url=f"test://{key}",
            title=key,
            entity_type="multi",
            sha256=key,
            plain_text="",
            raw_html="",
            source_name="Lifecycle test source",
            source_kind=kind,
            source_key=key,
        )

    def test_direct_allakhazam_style_npc_expansion_beats_location_fallback(self):
        source = self._source("npc-expansion")
        npc = self.db.upsert_entity(
            kind="npc",
            name="Modern Visitor",
            external_id="npc:modern",
            source_page_id=source,
            data={"expansion": "The Serpent's Spine"},
        )
        # The location is deliberately classic-looking. Explicit entity lifecycle is
        # stronger than where the current corpus happens to place the NPC.
        self.db.add_location(
            npc,
            zone_entity_id=self.classic,
            x=1.0,
            y=2.0,
            evidence="synthetic location",
        )

        lifecycle = entity_lifecycle_decision(self.db, npc, "p99")
        decision = entity_profile_decision(self.db, npc, "p99")

        self.assertFalse(lifecycle.compatibility)
        self.assertTrue(decision.blocked)
        self.assertIn("after Velious", decision.reason)
        self.assertEqual(decision.expansion_evidence[0].expansion, "The Serpent's Spine")
        self.assertEqual(decision.expansion_evidence[0].origin, "entity.data_json")

    def test_direct_classic_item_is_available_even_if_only_known_location_is_modern(self):
        source = self._source("classic-item")
        item = self.db.upsert_entity(
            kind="item",
            name="Old Portable Token",
            external_id="item:classic",
            source_page_id=source,
            data={"expansion": "Classic"},
        )
        self.db.add_location(
            item,
            zone_entity_id=self.modern,
            x=3.0,
            y=4.0,
            evidence="modern acquisition evidence",
        )

        decision = entity_profile_decision(self.db, item, "p99")

        self.assertTrue(decision.available)
        self.assertIn("at or before Velious", decision.reason)
        self.assertEqual(len(decision.zones), 1)
        self.assertFalse(decision.zones[0].allowed)

    def test_rich_detail_expansion_can_classify_portable_spell(self):
        detail_source = self._source("mcp-spell-detail", kind="mcp_local_details")
        spell = self.db.upsert_entity(
            kind="spell",
            name="Modern Test Spell",
            external_id="12345",
            external_namespace="eqclient:spell",
        )
        self.db.upsert_entity_detail(
            spell,
            source_page_id=detail_source,
            detail_format="mcp-json",
            detail_json={"name": "Modern Test Spell", "expansion": "Planes of Power"},
        )
        set_active_world_profile(self.db, "p99")

        evidence = entity_expansion_evidence(self.db, spell)
        decision = entity_profile_decision(self.db, spell, "p99")

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].origin, "entity_details.detail_json")
        self.assertEqual(evidence[0].source_kind, "mcp_local_details")
        self.assertTrue(decision.blocked)
        text = profiled_entity_detail_text(self.db, spell)
        self.assertIn("Direct expansion: Planes of Power", text)
        self.assertIn("Status: OUTSIDE PROFILE", text)

    def test_conflicting_direct_expansion_sources_remain_undetermined(self):
        entity_source = self._source("entity-source")
        detail_source = self._source("detail-source", kind="mcp_local_details")
        item = self.db.upsert_entity(
            kind="item",
            name="Conflicted Token",
            external_id="item:conflicted",
            source_page_id=entity_source,
            data={"expansion": "Velious"},
        )
        self.db.upsert_entity_detail(
            item,
            source_page_id=detail_source,
            detail_format="mcp-json",
            detail_json={"expansion": "The Serpent's Spine"},
        )

        decision = entity_profile_decision(self.db, item, "p99")

        self.assertIsNone(decision.compatibility)
        self.assertEqual(decision.status, "mixed")
        self.assertIn("disagree", decision.reason)
        self.assertEqual({e.expansion for e in decision.expansion_evidence}, {"Velious", "The Serpent's Spine"})

    def test_live_does_not_treat_expansion_as_retirement_evidence(self):
        source = self._source("modern-live-item")
        item = self.db.upsert_entity(
            kind="item",
            name="Modern Live Token",
            external_id="item:modern-live",
            source_page_id=source,
            data={"expansion": "The Serpent's Spine"},
        )

        lifecycle = entity_lifecycle_decision(self.db, item, "live")
        decision = entity_profile_decision(self.db, item, "live")

        self.assertIsNone(lifecycle.compatibility)
        self.assertIsNone(decision.compatibility)
        self.assertEqual(decision.status, "unknown")
        self.assertEqual(len(decision.expansion_evidence), 1)

    def test_nested_or_prose_expansion_words_are_not_promoted(self):
        source = self._source("unsafe-lifecycle")
        item = self.db.upsert_entity(
            kind="item",
            name="Unsafe Inference Token",
            external_id="item:unsafe",
            source_page_id=source,
            data={
                "description": "Added during The Serpent's Spine expansion",
                "metadata": {"expansion": "The Serpent's Spine"},
            },
        )

        self.assertEqual(entity_expansion_evidence(self.db, item), ())
        self.assertIsNone(entity_profile_decision(self.db, item, "p99").compatibility)


if __name__ == "__main__":
    unittest.main()
