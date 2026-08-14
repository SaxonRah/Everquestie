from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.map_loading_policy import install_map_loading_policy
from eqquest.runtime_policy import install_runtime_policy


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class RuntimeZoneMapUITests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _seed_duplicate_stone_hive(self) -> Path:
        self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            external_id="884",
            external_namespace="allakhazam:zone",
            merge_by_name=False,
        )
        self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            external_id="400",
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )

        local = self.root / "maps" / "Good's Maps"
        local.mkdir(parents=True)
        expected = local / "stonehive.txt"
        expected.write_text("P 1,2,3,255,0,0,2,Test\n", encoding="utf-8")
        return expected

    def _fake_viewer(self, expected: Path, *, packaged: bool):
        from eqquest import mapview as mapview_module

        loaded: list[Path] = []
        status = _Var()
        fake_viewer = SimpleNamespace(
            db=self.db,
            get_zone=lambda: "Stone Hive",
            map_root=_Var(str(expected.parent)),
            map_status=status,
            _base_map_status="Loaded stonehive",
            _packaged_runtime=lambda: packaged,
            load_map=lambda path: loaded.append(Path(path)),
            _refresh_overlay_cache=lambda **_kwargs: None,
            _refresh_marker_list=lambda: None,
        )
        fake_viewer.local_map_readiness = lambda zone: (
            mapview_module.MapViewerFrame.local_map_readiness(fake_viewer, zone)
        )
        return mapview_module, fake_viewer, loaded, status

    def test_packaged_current_zone_loads_client_backed_zone_despite_provider_duplicate(self):
        install_runtime_policy()
        install_map_loading_policy()
        expected = self._seed_duplicate_stone_hive()
        mapview_module, fake_viewer, loaded, status = self._fake_viewer(
            expected,
            packaged=True,
        )

        mapview_module.MapViewerFrame.load_current_zone(fake_viewer)

        self.assertEqual(loaded, [expected])
        self.assertIn("canonical runtime zone identity local map match", status.value)
        self.assertNotIn("canonical zone identity is ambiguous", status.value)

    def test_source_checkout_current_zone_uses_same_duplicate_zone_resolution(self):
        install_runtime_policy()
        install_map_loading_policy()
        expected = self._seed_duplicate_stone_hive()
        mapview_module, fake_viewer, loaded, status = self._fake_viewer(
            expected,
            packaged=False,
        )

        mapview_module.MapViewerFrame.load_current_zone(fake_viewer)

        self.assertEqual(loaded, [expected])
        self.assertIn("canonical runtime zone identity local map match", status.value)
        self.assertNotIn("canonical zone identity is ambiguous", status.value)


if __name__ == "__main__":
    unittest.main()
