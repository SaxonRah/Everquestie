from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.loot_source_navigation import loot_source_navigation


class LootSourceNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")
        self.current_zone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.remote_zone = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="202",
            external_namespace="eqclient:zone",
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _page(self, key: str, title: str, entity_type: str) -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/{key}",
            title=title,
            entity_type=entity_type,
            sha256=f"sha-{key}",
            plain_text=title,
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=key,
            source_version="loot-source-test",
        )

    def _item(self, name: str = "Stone Hive Resin") -> int:
        page = self._page("item/resin", name, "item")
        return self.db.upsert_entity(
            kind="item",
            name=name,
            external_id=f"item:{name}",
            source_page_id=page,
        )

    def _npc(
        self,
        name: str,
        external_id: str,
        zone_id: int | None,
        *,
        y: float = 10.0,
        x: float = 20.0,
    ) -> tuple[int, int]:
        page = self._page(external_id, name, "npc")
        npc = self.db.upsert_entity(
            kind="npc",
            name=name,
            external_id=external_id,
            source_page_id=page,
        )
        if zone_id is not None:
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

    def test_current_zone_maps_only_reviewed_drop_source(self):
        item = self._item()
        source, source_page = self._npc(
            "a stone hive worker", "npc/source", self.current_zone, y=31.0, x=41.0
        )
        turnin, turnin_page = self._npc(
            "Resin Collector", "npc/turnin", self.current_zone, y=5.0, x=6.0
        )
        self.db.upsert_relationship(
            item,
            source,
            "drops_from",
            source_page_id=source_page,
            evidence="Stone Hive Resin drops from a stone hive worker.",
        )
        self.db.upsert_relationship(
            item,
            turnin,
            "turn_in_to",
            source_page_id=turnin_page,
            evidence="Give Stone Hive Resin to Resin Collector.",
        )

        result = loot_source_navigation(self.db, item, "The Stone Hive")

        self.assertEqual(result.status, "map_ready")
        self.assertTrue(result.map_ready)
        self.assertEqual(result.source_npc_ids, (source,))
        self.assertEqual(len(result.map_choices), 1)
        choice = result.map_choices[0]
        self.assertEqual(choice.location_entity_id, source)
        self.assertEqual(choice.relation, "drops_from")
        self.assertEqual(choice.relation_label, "drops from")
        self.assertEqual((choice.y, choice.x), (31.0, 41.0))
        self.assertNotEqual(choice.location_entity_id, turnin)

    def test_remote_source_becomes_canonical_route_destination(self):
        item = self._item("Remote Resin")
        source, page = self._npc("a remote worker", "npc/remote", self.remote_zone)
        self.db.upsert_relationship(
            item,
            source,
            "drops_from",
            source_page_id=page,
            evidence="Remote Resin drops from a remote worker.",
        )

        result = loot_source_navigation(self.db, item, "The Stone Hive")

        self.assertEqual(result.status, "route_ready")
        self.assertFalse(result.map_ready)
        self.assertTrue(result.route_ready)
        self.assertEqual(len(result.route_choices), 1)
        route = result.route_choices[0]
        self.assertEqual(route.zone_entity_id, self.remote_zone)
        self.assertEqual(route.zone_name, "Blightfire Moors")
        self.assertEqual(route.target_labels, ("a remote worker (drops from)",))

    def test_unprovenanced_drop_relationship_is_not_navigation_evidence(self):
        item = self._item("Rumored Resin")
        source, _page = self._npc("a rumored worker", "npc/rumor", self.current_zone)
        self.db.upsert_relationship(
            item,
            source,
            "drops_from",
            source_page_id=None,
            evidence="Unreviewed rumor.",
        )

        result = loot_source_navigation(self.db, item, "The Stone Hive")

        self.assertEqual(result.status, "no_reviewed_source")
        self.assertFalse(result.navigable)
        self.assertIn("knowledge gap", result.reason)

    def test_reviewed_source_without_safe_location_stays_non_actionable(self):
        item = self._item("Hidden Resin")
        source, page = self._npc("a hidden worker", "npc/hidden", None)
        self.db.upsert_relationship(
            item,
            source,
            "drops_from",
            source_page_id=page,
            evidence="Hidden Resin drops from a hidden worker.",
        )

        result = loot_source_navigation(self.db, item, "The Stone Hive")

        self.assertEqual(result.status, "source_location_unavailable")
        self.assertFalse(result.navigable)
        self.assertIn("a hidden worker", result.reason)
        self.assertIn("safe canonical Map/Travel location", result.reason)

    def test_missing_current_zone_does_not_guess_map_or_route(self):
        item = self._item("Located Resin")
        source, page = self._npc("a located worker", "npc/located", self.remote_zone)
        self.db.upsert_relationship(
            item,
            source,
            "drops_from",
            source_page_id=page,
            evidence="Located Resin drops from a located worker.",
        )

        result = loot_source_navigation(self.db, item, None)

        self.assertEqual(result.status, "no_current_zone")
        self.assertFalse(result.navigable)
        self.assertIn("Current zone", result.reason)

    def test_non_item_input_is_rejected(self):
        npc, _page = self._npc("Not an item", "npc/not-item", self.current_zone)
        result = loot_source_navigation(self.db, npc, "The Stone Hive")
        self.assertEqual(result.status, "missing_item")
        self.assertFalse(result.navigable)


if __name__ == "__main__":
    unittest.main()
