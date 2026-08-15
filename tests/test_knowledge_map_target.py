from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_map_target import select_knowledge_map_target
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.packaged_ui_policy import install_packaged_ui_policy
from eqquest.runtime import RuntimeDatabase
from eqquest.runtime_policy import install_runtime_policy
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class KnowledgeMapTargetTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="202",
            external_namespace="eqclient:zone",
        )
        self.mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="397",
            external_namespace="eqclient:zone",
        )
        self.npc = self.db.upsert_entity(kind="npc", name="Scout Fana", external_id="npc:1001")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _page(self, key: str, title: str, entity_type: str) -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/{key.replace(':', '/')}",
            title=title,
            entity_type=entity_type,
            sha256=key,
            plain_text=title,
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=key,
            source_version="mirror-2026-08-14",
        )

    def _add_location(self, *, zone_id: int, y: float, x: float, z: float | None = None, label: str = "spawn"):
        self.db.add_location(
            self.npc,
            zone_entity_id=zone_id,
            y=y,
            x=x,
            z=z,
            label=label,
            evidence=f"{label} at {y}, {x}",
        )

    def test_one_current_zone_coordinate_is_ready(self):
        self._add_location(zone_id=self.stone, y=125.0, x=-42.0, z=7.0)
        result = select_knowledge_map_target(self.db, self.npc, "The Stone Hive")
        self.assertTrue(result.ready)
        self.assertIsNotNone(result.target)
        assert result.target is not None
        self.assertEqual(result.target.zone_entity_id, self.stone)
        self.assertEqual(result.target.zone_name, "The Stone Hive")
        self.assertEqual((result.target.x, result.target.y, result.target.z), (-42.0, 125.0, 7.0))
        self.assertEqual(result.target.label, "Scout Fana")

    def test_same_coordinate_from_multiple_sources_deduplicates_to_one_target(self):
        page_a = self._page("npc:source-a", "Source A", "npc")
        page_b = self._page("npc:source-b", "Source B", "npc")
        for page, label in ((page_a, "provider spawn"), (page_b, "second confirmation")):
            self.db.add_location(
                self.npc,
                zone_entity_id=self.stone,
                y=50.0,
                x=25.0,
                z=3.0,
                label=label,
                source_page_id=page,
                evidence=label,
            )
        result = select_knowledge_map_target(self.db, self.npc, "The Stone Hive")
        self.assertTrue(result.ready)
        assert result.target is not None
        self.assertEqual(result.target.evidence_count, 2)
        self.assertEqual(len(result.target.source_labels), 1)
        self.assertIn("Allakhazam", result.target.source_labels[0])

    def test_distinct_current_zone_coordinates_are_not_guessed(self):
        self._add_location(zone_id=self.stone, y=10.0, x=20.0, label="north spawn")
        self._add_location(zone_id=self.stone, y=30.0, x=40.0, label="south spawn")
        result = select_knowledge_map_target(self.db, self.npc, "The Stone Hive")
        self.assertFalse(result.ready)
        self.assertEqual(result.status, "multiple_current_zone_locations")
        self.assertEqual(result.current_zone_candidate_count, 2)
        self.assertIn("will not choose one automatically", result.reason)

    def test_safe_location_in_other_zone_does_not_move_current_map(self):
        self._add_location(zone_id=self.blight, y=10.0, x=20.0)
        result = select_knowledge_map_target(self.db, self.npc, "The Stone Hive")
        self.assertEqual(result.status, "not_in_current_zone")
        self.assertEqual(result.other_zone_candidate_count, 1)
        self.assertFalse(result.ready)

    def test_candidate_provider_coordinate_is_never_eligible(self):
        mesa_page = self._page("zone:397", "Goru'kar Mesa", "zone")
        provider_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            source_page_id=mesa_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=397",
            external_id="zone:397",
        )
        self._add_location(zone_id=provider_mesa, y=10.0, x=20.0)
        ProviderZoneReconciliationCatalog(self.db).reconcile()
        result = select_knowledge_map_target(self.db, self.npc, "Goru'kar Mesa")
        self.assertEqual(result.status, "no_navigable_location")
        self.assertFalse(result.ready)

    def test_missing_current_zone_and_missing_location_are_distinct(self):
        missing_zone = select_knowledge_map_target(self.db, self.npc, "")
        self.assertEqual(missing_zone.status, "no_current_zone")
        missing_location = select_knowledge_map_target(self.db, self.npc, "The Stone Hive")
        self.assertEqual(missing_location.status, "no_location")

    def test_finalized_runtime_selects_same_target_read_only(self):
        self._add_location(zone_id=self.stone, y=125.0, x=-42.0, z=7.0)
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="knowledge-map-target-test",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            result = select_knowledge_map_target(runtime, self.npc, "The Stone Hive")
            self.assertTrue(result.ready)
            assert result.target is not None
            self.assertEqual(result.target.zone_entity_id, self.stone)
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entity_locations SET x=999")
        finally:
            runtime.close()

    def test_packaged_app_method_hands_only_ready_target_to_map_owner(self):
        self._add_location(zone_id=self.stone, y=125.0, x=-42.0, z=7.0)
        install_runtime_policy()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        status = _Status()
        emitted: list[tuple] = []
        fake = SimpleNamespace(
            db=self.db,
            state_model=SimpleNamespace(current_zone="The Stone Hive"),
            status=status,
            _selected_entity_id=lambda: self.npc,
            _focus_navigation_map_target=lambda *args: emitted.append(args),
        )
        app_module.EverQuestieApp._map_selected_knowledge_location(fake)
        self.assertEqual(emitted, [("The Stone Hive", -42.0, 125.0, 7.0, "Scout Fana")])

        self._add_location(zone_id=self.stone, y=5.0, x=6.0, z=1.0, label="alternate")
        emitted.clear()
        app_module.EverQuestieApp._map_selected_knowledge_location(fake)
        self.assertEqual(emitted, [])
        self.assertIn("will not choose one automatically", status.value)


if __name__ == "__main__":
    unittest.main()
