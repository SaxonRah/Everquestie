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
from eqquest.runtime_policy import install_runtime_policy


class _StatusRecorder:
    def __init__(self):
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


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


if __name__ == "__main__":
    unittest.main()
