import inspect
import unittest

from eqquest.allakhazam import AllakhazamImporter
from eqquest.app import EverQuestieApp
from eqquest.mapview import MapViewerFrame


class RuntimeSourcePolicyTests(unittest.TestCase):
    def test_startup_does_not_rebuild_allakhazam_knowledge(self):
        init_source = inspect.getsource(EverQuestieApp.__init__)
        self.assertNotIn("rebuild_imported_pages(", init_source)

    def test_tracked_quest_history_replay_is_not_in_blocking_constructor(self):
        init_source = inspect.getsource(EverQuestieApp.__init__)
        reconcile_source = inspect.getsource(
            EverQuestieApp._maybe_reconcile_tracked_quests_async
        )

        self.assertNotIn("reconcile_quest_from_history(", init_source)
        self.assertIn(
            "self.after(0, self._maybe_reconcile_tracked_quests_async)",
            init_source,
        )
        self.assertIn("runtime_split", reconcile_source)
        self.assertIn("open_worker_connection()", reconcile_source)
        self.assertIn("observed_event_history()", reconcile_source)
        self.assertIn("TRACKED_RECONCILE_META_KEY", reconcile_source)
        self.assertIn("threading.Thread(", reconcile_source)

    def test_startup_defers_full_source_provenance_summary(self):
        build_source = inspect.getsource(EverQuestieApp._build_ui)
        self.assertNotIn("self._refresh_source_summary()", build_source)

    def test_legacy_allakhazam_rebuild_remains_explicitly_available(self):
        self.assertTrue(callable(AllakhazamImporter.rebuild_imported_pages))

    def test_manual_db_mirror_uses_canonical_mirror_importer_only(self):
        init_source = inspect.getsource(EverQuestieApp.__init__)
        mirror_source = inspect.getsource(EverQuestieApp._import_db_mirror)
        saved_source = inspect.getsource(EverQuestieApp._import_saved_html)

        self.assertIn("self.mirror_importer = AllakhazamMirrorImporter(self.db)", init_source)
        self.assertIn("worker_db = Database(db_path)", mirror_source)
        self.assertIn(
            "AllakhazamMirrorImporter(worker_db).import_mirror(",
            mirror_source,
        )
        self.assertNotIn("self.importer.import_mirror(", mirror_source)
        self.assertIn("self.importer.import_saved_html(", saved_source)

    def test_packaged_runtime_guards_every_builder_mutation_entrypoint(self):
        guarded = (
            EverQuestieApp._rebuild_search_index,
            EverQuestieApp._import_eq_client,
            EverQuestieApp._compile_eq_client_via_mcp,
            EverQuestieApp._import_db_mirror,
            EverQuestieApp._import_wiki_mirror,
            EverQuestieApp._import_saved_html,
            EverQuestieApp._import_html_folder,
        )
        for method in guarded:
            with self.subTest(method=method.__name__):
                source = inspect.getsource(method)
                self.assertIn("knowledge_writable", source)
                self.assertIn("builder-only", source)

    def test_packaged_map_catalog_is_read_only_shipped_knowledge(self):
        ensure_source = inspect.getsource(MapViewerFrame.ensure_map_catalog)
        index_source = inspect.getsource(MapViewerFrame.index_map_catalog)

        self.assertIn("knowledge_writable", ensure_source)
        self.assertIn("knowledge_writable", index_source)
        self.assertIn("shipped immutable knowledge", index_source)

    def test_mcp_compiler_is_scoped_to_explicit_worker_action(self):
        init_source = inspect.getsource(EverQuestieApp.__init__)
        compile_source = inspect.getsource(EverQuestieApp._compile_eq_client_via_mcp)

        self.assertNotIn("self.mcp_local_compiler", init_source)
        self.assertIn("worker_db = Database(db_path)", compile_source)
        self.assertIn("MCPLocalSnapshotCompiler(worker_db).compile_installation(", compile_source)
        self.assertNotIn("self.mcp_local_compiler", compile_source)


if __name__ == "__main__":
    unittest.main()
