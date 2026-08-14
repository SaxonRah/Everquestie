from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog
from eqquest.runtime import RuntimeDatabase
from eqquest.runtime_policy import (
    _draw_runtime_navigation_target,
    _focus_runtime_navigation_target,
    _same_canonical_zone,
    install_runtime_policy,
)


class _StatusRecorder:
    def __init__(self):
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class _CanvasRecorder:
    def __init__(self):
        self.deleted: list[str] = []
        self.ovals: list[tuple[tuple, dict]] = []
        self.lines: list[tuple[tuple, dict]] = []
        self.texts: list[tuple[tuple, dict]] = []

    def delete(self, tag):
        self.deleted.append(str(tag))

    def create_oval(self, *args, **kwargs):
        self.ovals.append((args, kwargs))
        return len(self.ovals)

    def create_line(self, *args, **kwargs):
        self.lines.append((args, kwargs))
        return len(self.lines)

    def create_text(self, *args, **kwargs):
        self.texts.append((args, kwargs))
        return len(self.texts)


class RuntimeMapPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.maps = self.root / "maps"
        self.maps.mkdir()
        (self.maps / "stonehive.txt").write_text(
            "P 1,2,3,255,0,0,2,Test_Label\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def test_packaged_runtime_blocks_catalog_rebuild_but_builder_remains_writable(self):
        working = self.root / "working.sqlite3"
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        state = self.root / "everquestie-user.sqlite3"

        builder = Database(working)
        try:
            stats = MapCatalog(builder).index_root(self.maps, source_name="Builder Pack")
            self.assertEqual(stats.base_maps, 1)
        finally:
            builder.close()
        create_knowledge_snapshot(
            working,
            snapshot,
            snapshot_version="runtime-map-policy-test",
        )
        before = self._digest(snapshot)

        install_runtime_policy()
        install_runtime_policy()  # policy installation is intentionally idempotent

        runtime = RuntimeDatabase(snapshot, state)
        try:
            catalog = MapCatalog(runtime)
            with self.assertRaisesRegex(RuntimeError, "builder-only"):
                catalog.index_root(self.maps, source_name="Must Not Build")
        finally:
            runtime.close()

        self.assertEqual(self._digest(snapshot), before)
        self.assertFalse(Path(str(snapshot) + "-wal").exists())
        self.assertFalse(Path(str(snapshot) + "-shm").exists())

        # The guard is lifecycle-sensitive, not a global removal of builder tooling.
        second_builder_path = self.root / "second-builder.sqlite3"
        second_builder = Database(second_builder_path)
        try:
            stats = MapCatalog(second_builder).index_root(
                self.maps,
                source_name="Builder Still Works",
            )
            self.assertEqual(stats.base_maps, 1)
            self.assertGreaterEqual(stats.labels, 1)
        finally:
            second_builder.close()

    def test_packaged_app_policy_blocks_fts_rebuild_method_before_builder_db_open(self):
        install_runtime_policy()
        from eqquest import app as app_module

        status = _StatusRecorder()
        fake_app = SimpleNamespace(
            db=SimpleNamespace(knowledge_writable=False),
            status=status,
            _packaged_runtime=lambda: True,
        )
        # Call the patched method unbound so no Tk display is required in CI.
        app_module.EverQuestieApp._rebuild_search_index(fake_app)
        self.assertIn("shipped knowledge snapshot", status.value)
        self.assertIn("read-only", status.value)
        self.assertTrue(
            getattr(app_module.EverQuestieApp, "_everquestie_packaged_app_policy", False)
        )

    def test_runtime_policy_routes_where_through_unified_location_projection(self):
        install_runtime_policy()
        from eqquest import app as app_module
        from eqquest.locations import where_text as unified_where_text

        self.assertIs(app_module.where_text, unified_where_text)

    def test_navigation_target_converts_game_coordinates_and_draws_without_tk(self):
        db = Database(self.root / "navigation.sqlite3")
        try:
            db.upsert_entity(
                kind="zone",
                name="Stone Hive",
                merge_by_name=True,
                data={"map_short_name": "stonehive"},
            )
            canvas = _CanvasRecorder()
            centered: list[tuple[float, float]] = []
            status = _StatusRecorder()
            fake = SimpleNamespace(
                db=db,
                get_zone=lambda: "Stone Hive",
                zone_map=object(),
                canvas=canvas,
                coord_status=status,
                _navigation_target=None,
                _world_to_screen=lambda x, y: (x * 2.0, y * 2.0),
                _center_map_point=lambda x, y: centered.append((x, y)),
            )

            focused = _focus_runtime_navigation_target(
                fake,
                "stonehive",
                10.0,
                20.0,
                3.0,
                "A Stone Worker",
            )
            self.assertTrue(focused)
            self.assertEqual(centered, [(-10.0, -20.0)])
            self.assertEqual(fake._navigation_target[:4], ("stonehive", 10.0, 20.0, 3.0))
            self.assertEqual(len(canvas.ovals), 1)
            self.assertEqual(len(canvas.lines), 2)
            self.assertEqual(len(canvas.texts), 1)
            self.assertIn("A Stone Worker", canvas.texts[0][1]["text"])
            self.assertIn("Y=20", status.value)
            self.assertIn("X=10", status.value)
            self.assertIn("Z=3", status.value)

            # Redraw remains deterministic and still uses native map-space signs.
            canvas.ovals.clear()
            canvas.lines.clear()
            canvas.texts.clear()
            _draw_runtime_navigation_target(fake)
            self.assertEqual(len(canvas.ovals), 1)
            oval = canvas.ovals[0][0]
            # world_to_screen doubles native (-10,-20) to (-20,-40); radius is 10.
            self.assertEqual(oval[:4], (-30.0, -50.0, -10.0, -30.0))
        finally:
            db.close()

    def test_navigation_target_rejects_wrong_zone_and_hides_after_zone_change(self):
        db = Database(self.root / "navigation-zone.sqlite3")
        try:
            stone = db.upsert_entity(kind="zone", name="Stone Hive", merge_by_name=True)
            blight = db.upsert_entity(kind="zone", name="Blightfire Moors", merge_by_name=True)
            self.assertNotEqual(stone, blight)
            current = {"zone": "Stone Hive"}
            canvas = _CanvasRecorder()
            centered: list[tuple[float, float]] = []
            status = _StatusRecorder()
            fake = SimpleNamespace(
                db=db,
                get_zone=lambda: current["zone"],
                zone_map=object(),
                canvas=canvas,
                coord_status=status,
                _navigation_target=None,
                _world_to_screen=lambda x, y: (x, y),
                _center_map_point=lambda x, y: centered.append((x, y)),
            )

            self.assertTrue(_same_canonical_zone(db, "Stone Hive", "Stone Hive"))
            self.assertFalse(_same_canonical_zone(db, "Stone Hive", "Blightfire Moors"))
            focused = _focus_runtime_navigation_target(
                fake,
                "Blightfire Moors",
                1.0,
                2.0,
                3.0,
                "Wrong-zone target",
            )
            self.assertFalse(focused)
            self.assertEqual(centered, [])
            self.assertEqual(canvas.ovals, [])
            self.assertIn("different current zone", status.value)

            # A valid target draws now, but automatically disappears from redraws once
            # the live zone changes; no stale coordinate is rendered on another map.
            self.assertTrue(
                _focus_runtime_navigation_target(
                    fake,
                    "Stone Hive",
                    4.0,
                    5.0,
                    6.0,
                    "Valid target",
                )
            )
            self.assertEqual(len(canvas.ovals), 1)
            current["zone"] = "Blightfire Moors"
            canvas.ovals.clear()
            canvas.lines.clear()
            canvas.texts.clear()
            _draw_runtime_navigation_target(fake)
            self.assertEqual(canvas.ovals, [])
            self.assertEqual(canvas.lines, [])
            self.assertEqual(canvas.texts, [])
            self.assertIn("eqquest_navigation_target", canvas.deleted)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
