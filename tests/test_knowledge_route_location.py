from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_location_ui import knowledge_route_choice_labels
from eqquest.knowledge_map_choices import knowledge_map_choices, knowledge_route_choices
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


class KnowledgeRouteLocationTests(unittest.TestCase):
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

    def _located_npc(
        self,
        name: str,
        key: str,
        zone_id: int,
        *,
        y: float = 10.0,
        x: float = 20.0,
    ) -> tuple[int, int]:
        page = self._page(key, name, "npc")
        npc = self.db.upsert_entity(
            kind="npc",
            name=name,
            external_id=key,
            source_page_id=page,
        )
        self.db.add_location(
            npc,
            zone_entity_id=zone_id,
            y=y,
            x=x,
            z=5.0,
            label="known location",
            source_page_id=page,
            evidence=f"{name} at {y}, {x}",
        )
        return npc, page

    def test_multiple_remote_points_collapse_to_one_route_destination(self):
        npc, page = self._located_npc(
            "Remote Scout", "npc:5001", self.blight, y=10.0, x=20.0
        )
        self.db.add_location(
            npc,
            zone_entity_id=self.blight,
            y=30.0,
            x=40.0,
            z=5.0,
            label="second spawn",
            source_page_id=page,
            evidence="second confirmed spawn",
        )

        mapped = knowledge_map_choices(self.db, npc, "The Stone Hive")
        self.assertEqual(mapped.status, "not_in_current_zone")
        self.assertEqual(mapped.other_zone_choice_count, 2)
        self.assertEqual(len(mapped.other_zone_choices), 2)

        routes = knowledge_route_choices(mapped)
        self.assertEqual(len(routes), 1)
        route = routes[0]
        self.assertEqual(route.zone_entity_id, self.blight)
        self.assertEqual(route.zone_name, "Blightfire Moors")
        self.assertEqual(route.location_choice_count, 2)
        self.assertEqual(route.target_labels, ("Remote Scout",))
        labels = knowledge_route_choice_labels(routes)
        self.assertIn("Blightfire Moors", labels[0])
        self.assertIn("2 mapped locations", labels[0])

    def test_related_npcs_in_two_remote_zones_produce_explicit_zone_choices(self):
        dropper, drop_page = self._located_npc("Blight Worker", "npc:5101", self.blight)
        vendor, vendor_page = self._located_npc("Mesa Merchant", "npc:5102", self.mesa)
        item = self.db.upsert_entity(
            kind="item", name="Remote Sample", external_id="item:8101"
        )
        self.db.upsert_relationship(
            item,
            dropper,
            "drops_from",
            source_page_id=drop_page,
            evidence="Dropped by Blight Worker",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            vendor,
            item,
            "sells",
            source_page_id=vendor_page,
            evidence="Sold by Mesa Merchant",
            data={"confidence": "structured"},
        )

        mapped = knowledge_map_choices(self.db, item, "The Stone Hive")
        routes = knowledge_route_choices(mapped)
        self.assertEqual(
            [choice.zone_name for choice in routes],
            ["Blightfire Moors", "Goru'kar Mesa"],
        )
        by_zone = {choice.zone_name: choice for choice in routes}
        self.assertIn("Blight Worker (drops from)", by_zone["Blightfire Moors"].target_labels)
        self.assertIn("Mesa Merchant (vendor)", by_zone["Goru'kar Mesa"].target_labels)

    def test_candidate_provider_remote_location_never_becomes_route_choice(self):
        provider_page = self._page("zone:9001", "Goru'kar Mesa", "zone")
        provider_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="zone:9001",
            source_page_id=provider_page,
        )
        npc, _page = self._located_npc(
            "Candidate Scout", "npc:5201", provider_mesa
        )
        stats = ProviderZoneReconciliationCatalog(self.db).reconcile()
        self.assertGreaterEqual(stats.candidate, 1)
        binding = ProviderZoneReconciliationCatalog(self.db).binding_for_provider_zone(provider_mesa)
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.status, "candidate")

        mapped = knowledge_map_choices(self.db, npc, "The Stone Hive")
        self.assertEqual(mapped.status, "no_navigable_location")
        self.assertEqual(mapped.other_zone_choices, ())
        self.assertEqual(knowledge_route_choices(mapped), ())

    def test_finalized_runtime_preserves_remote_route_choices_read_only(self):
        npc, _page = self._located_npc(
            "Runtime Scout", "npc:5301", self.blight, y=55.0, x=-22.0
        )
        builder = knowledge_route_choices(
            knowledge_map_choices(self.db, npc, "The Stone Hive")
        )
        self.assertEqual(len(builder), 1)

        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="knowledge-route-location-test",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            packaged = knowledge_route_choices(
                knowledge_map_choices(runtime, npc, "The Stone Hive")
            )
            self.assertEqual(packaged, builder)
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entity_locations SET x=999")
        finally:
            runtime.close()

    def test_packaged_action_hands_one_canonical_remote_zone_to_travel(self):
        npc, _page = self._located_npc("Travel Scout", "npc:5401", self.blight)
        install_runtime_policy()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        status = _Status()
        routed: list[str] = []
        selected_tabs: list[object] = []
        travel_tab = SimpleNamespace(
            route_to_zone=lambda zone: routed.append(str(zone)) or True,
        )
        notebook = SimpleNamespace(select=lambda tab: selected_tabs.append(tab))
        fake = SimpleNamespace(
            db=self.db,
            state_model=SimpleNamespace(current_zone="The Stone Hive"),
            status=status,
            _selected_entity_id=lambda: npc,
            travel_tab=travel_tab,
            notebook=notebook,
        )

        app_module.EverQuestieApp._route_selected_knowledge_location(fake)
        self.assertEqual(routed, ["Blightfire Moors"])
        self.assertEqual(selected_tabs, [travel_tab])
        self.assertIn("travel route opened", status.value.casefold())

    def test_packaged_action_uses_explicit_destination_choice_for_multiple_remote_zones(self):
        first, first_page = self._located_npc("Blight Worker", "npc:5501", self.blight)
        second, second_page = self._located_npc("Mesa Worker", "npc:5502", self.mesa)
        item = self.db.upsert_entity(
            kind="item", name="Split Sample", external_id="item:8501"
        )
        self.db.upsert_relationship(
            item,
            first,
            "drops_from",
            source_page_id=first_page,
            evidence="Blight dropper",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            item,
            second,
            "turn_in_to",
            source_page_id=second_page,
            evidence="Mesa turn-in",
            data={"confidence": "structured"},
        )
        choices = knowledge_route_choices(
            knowledge_map_choices(self.db, item, "The Stone Hive")
        )
        self.assertEqual(len(choices), 2)
        chosen = next(choice for choice in choices if choice.zone_name == "Goru'kar Mesa")

        install_runtime_policy()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        status = _Status()
        routed: list[str] = []
        travel_tab = SimpleNamespace(
            route_to_zone=lambda zone: routed.append(str(zone)) or True,
        )
        fake = SimpleNamespace(
            db=self.db,
            state_model=SimpleNamespace(current_zone="The Stone Hive"),
            status=status,
            _selected_entity_id=lambda: item,
            travel_tab=travel_tab,
            notebook=SimpleNamespace(select=lambda _tab: None),
        )
        with patch(
            "eqquest.knowledge_location_ui.ask_knowledge_route_choice",
            return_value=chosen,
        ):
            app_module.EverQuestieApp._route_selected_knowledge_location(fake)
        self.assertEqual(routed, ["Goru'kar Mesa"])

    def test_current_zone_location_points_route_action_back_to_map(self):
        npc, _page = self._located_npc("Local Scout", "npc:5601", self.stone)
        install_runtime_policy()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        status = _Status()
        routed: list[str] = []
        fake = SimpleNamespace(
            db=self.db,
            state_model=SimpleNamespace(current_zone="The Stone Hive"),
            status=status,
            _selected_entity_id=lambda: npc,
            travel_tab=SimpleNamespace(
                route_to_zone=lambda zone: routed.append(str(zone)) or True
            ),
            notebook=SimpleNamespace(select=lambda _tab: None),
        )
        app_module.EverQuestieApp._route_selected_knowledge_location(fake)
        self.assertEqual(routed, [])
        self.assertIn("use map location", status.value.casefold())


if __name__ == "__main__":
    unittest.main()
