from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog
from eqquest.route_guidance_ui import RouteGuidanceFrame


_MAP_TEXT = "P 50,50,0,0,255,0,2,To_Blightfire_Moors\n"


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class TravelNavigationRefreshUITests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(self, name: str, external_id: str, namespace: str) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=external_id,
            external_namespace=namespace,
            merge_by_name=False,
        )

    def test_find_route_repairs_stale_builder_catalog_in_same_action(self):
        self._zone("Stone Hive", "884", "allakhazam:zone")
        stone = self._zone("Stone Hive", "396", "eqclient:zone")
        self._zone("Blightfire Moors", "999", "allakhazam:zone")
        blight = self._zone("Blightfire Moors", "395", "eqclient:zone")

        maps = self.root / "Good's Maps"
        maps.mkdir()
        (maps / "stonehive.txt").write_text(_MAP_TEXT, encoding="utf-8")
        MapCatalog(self.db).index_root(maps, source_name="Good's Maps")

        # No ZoneMapCatalog/ZoneTravelCatalog build is invoked here. This models the
        # real long-lived builder DB after the authority-policy upgrade.
        captured = {"text": "", "cleared": False}
        fake = SimpleNamespace(
            db=self.db,
            from_var=_Var("Stone Hive"),
            to_var=_Var("Blightfire Moors"),
            status_var=_Var(),
            _route_guidance=None,
            _clear_nearby_points=lambda: captured.__setitem__("cleared", True),
            _set_result=lambda text: captured.__setitem__("text", text),
            use_current_zone=lambda: None,
        )

        RouteGuidanceFrame.find_route(fake)

        self.assertTrue(captured["cleared"])
        self.assertIsNotNone(fake._route_guidance)
        self.assertTrue(fake._route_guidance.ok)
        self.assertEqual(fake._route_guidance.route.path, (stone, blight))
        self.assertIn("Route: Stone Hive", captured["text"])
        self.assertIn("Blightfire Moors", captured["text"])
        self.assertIn("Confirmed canonical route found", fake.status_var.get())


if __name__ == "__main__":
    unittest.main()
