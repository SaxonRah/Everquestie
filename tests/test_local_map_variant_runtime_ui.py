from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from eqquest.db import Database
from eqquest.local_map_readiness import LocalMapReadiness, resolve_local_map_readiness
from eqquest.map_catalog import MapCatalog
from eqquest.mapview import _binding_key
from eqquest.runtime_policy import _choose_runtime_local_map_variant, install_runtime_policy
from eqquest.zone_catalog import ZoneMapCatalog


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = str(value)


class LocalMapVariantRuntimeUITests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    @staticmethod
    def _write_map(root: Path, stem: str) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{stem}.txt"
        path.write_text("P 1,2,3,255,0,0,2,Test\n", encoding="utf-8")
        return path

    def _catalog(self) -> tuple[Path, Path, Path]:
        zone = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            external_id="202",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self.db.add_alias(zone, "poknowledge", alias_type="provider_short_name")
        self.db.add_alias(zone, "planeofknowledge", alias_type="provider_short_name")
        good = self.root / "builder-good"
        brewall = self.root / "builder-brewall"
        self._write_map(good, "poknowledge")
        self._write_map(brewall, "planeofknowledge")
        MapCatalog(self.db).index_root(good, source_name="Good", source_version="1")
        ZoneMapCatalog(self.db).reconcile(source_name="Good")
        MapCatalog(self.db).index_root(brewall, source_name="Brewall", source_version="1")
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall")
        local = self.root / "player-pack"
        first = self._write_map(local, "poknowledge")
        second = self._write_map(local, "planeofknowledge")
        return local, first, second

    def _viewer(self, local: Path):
        loaded: list[Path] = []
        status = _Var()
        viewer = SimpleNamespace(
            db=self.db,
            get_zone=lambda: "The Plane of Knowledge",
            map_root=_Var(str(local)),
            map_status=status,
            _base_map_status="Loaded",
            load_map=lambda path: loaded.append(Path(path)),
        )
        return viewer, loaded, status

    def test_safe_dialog_choice_binds_and_loads_verified_candidate(self):
        local, first, second = self._catalog()
        viewer, loaded, status = self._viewer(local)

        with patch(
            "eqquest.local_map_variant_ui.ask_local_map_variant",
            return_value=second,
        ) as chooser:
            ok = _choose_runtime_local_map_variant(viewer)

        self.assertTrue(ok)
        chooser.assert_called_once()
        called_candidates = tuple(chooser.call_args.args[2])
        self.assertEqual(set(called_candidates), {first, second})
        self.assertEqual(loaded, [second])
        self.assertEqual(
            self.db.get_meta(_binding_key("The Plane of Knowledge"), ""),
            "planeofknowledge",
        )
        self.assertIn("user map binding", status.value)
        self.assertIn("planeofknowledge.txt", status.value)

    def test_stale_dialog_choice_is_rejected_after_candidate_disappears(self):
        local, first, second = self._catalog()
        viewer, loaded, status = self._viewer(local)

        def stale_choice(_parent, _zone, _candidates):
            second.unlink()
            return second

        with patch(
            "eqquest.local_map_variant_ui.ask_local_map_variant",
            side_effect=stale_choice,
        ):
            ok = _choose_runtime_local_map_variant(viewer)

        self.assertFalse(ok)
        self.assertEqual(loaded, [])
        self.assertEqual(self.db.get_meta(_binding_key("The Plane of Knowledge"), ""), "")
        self.assertIn("candidate set changed", status.value)

    def test_cancel_does_not_write_or_load(self):
        local, first, second = self._catalog()
        viewer, loaded, status = self._viewer(local)
        with patch(
            "eqquest.local_map_variant_ui.ask_local_map_variant",
            return_value=None,
        ):
            ok = _choose_runtime_local_map_variant(viewer)
        self.assertFalse(ok)
        self.assertEqual(loaded, [])
        self.assertEqual(self.db.get_meta(_binding_key("The Plane of Knowledge"), ""), "")
        self.assertIn("choice canceled", status.value)

    def test_ambiguous_zone_identity_never_opens_variant_dialog(self):
        north = self.db.upsert_entity(kind="zone", name="North Freeport", merge_by_name=True)
        south = self.db.upsert_entity(kind="zone", name="South Freeport", merge_by_name=True)
        self.db.add_alias(north, "Freeport", alias_type="provider_alias")
        self.db.add_alias(south, "Freeport", alias_type="provider_alias")
        local = self.root / "maps"
        self._write_map(local, "freeport")
        viewer = SimpleNamespace(
            db=self.db,
            get_zone=lambda: "Freeport",
            map_root=_Var(str(local)),
            map_status=_Var(),
        )
        with patch("eqquest.local_map_variant_ui.ask_local_map_variant") as chooser:
            ok = _choose_runtime_local_map_variant(viewer)
        self.assertFalse(ok)
        chooser.assert_not_called()
        self.assertIn("will not offer local map variants", viewer.map_status.value)

    def test_packaged_load_current_zone_invokes_variant_flow_only_for_map_ambiguity(self):
        install_runtime_policy()
        from eqquest import mapview as mapview_module

        readiness = LocalMapReadiness(
            zone_token="The Plane of Knowledge",
            canonical_zone_entity_id=202,
            canonical_zone_name="The Plane of Knowledge",
            status="map_ambiguous",
            reason="multiple shipped canonical map variants exist in the selected pack",
            path=None,
            candidates=(Path("poknowledge.txt"), Path("planeofknowledge.txt")),
            bound_stem="",
            hinted_stem="",
        )
        calls: list[str] = []
        fake = SimpleNamespace(
            db=self.db,
            get_zone=lambda: "The Plane of Knowledge",
            _packaged_runtime=lambda: True,
            local_map_readiness=lambda zone: readiness,
            choose_local_map_variant=lambda: calls.append("choose") or True,
            map_status=_Var(),
            _refresh_overlay_cache=lambda **_kwargs: calls.append("overlay"),
            _refresh_marker_list=lambda: calls.append("markers"),
        )

        mapview_module.MapViewerFrame.load_current_zone(fake)
        self.assertEqual(calls, ["choose"])

    def test_after_choice_normal_readiness_is_user_binding(self):
        local, first, second = self._catalog()
        viewer, loaded, status = self._viewer(local)
        with patch(
            "eqquest.local_map_variant_ui.ask_local_map_variant",
            return_value=first,
        ):
            self.assertTrue(_choose_runtime_local_map_variant(viewer))

        readiness = resolve_local_map_readiness(
            self.db,
            "The Plane of Knowledge",
            local,
            bound_stem=self.db.get_meta(_binding_key("The Plane of Knowledge"), ""),
        )
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.path, first)
        self.assertEqual(readiness.reason, "user map binding")


if __name__ == "__main__":
    unittest.main()
