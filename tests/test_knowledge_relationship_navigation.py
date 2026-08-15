from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest import app as app_module
from eqquest.db import Database
from eqquest.knowledge_relationship_navigation import (
    knowledge_related_entity_choices,
    knowledge_relationship_back,
    open_knowledge_entity_id,
)
from eqquest.knowledge_relationship_ui import (
    install_knowledge_relationship_navigation_ui,
    knowledge_related_choice_labels,
)
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class _Var:
    def __init__(self, value=""):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class _Tree:
    def __init__(self):
        self.items: set[str] = set()
        self.selected: tuple[str, ...] = ()
        self.focused = ""
        self.seen = ""

    def exists(self, iid):
        return iid in self.items

    def insert(self, _parent, _index, *, iid, text=""):
        _ = text
        self.items.add(iid)
        return iid

    def selection(self):
        return self.selected

    def selection_set(self, iid):
        self.selected = (iid,)

    def focus(self, iid=None):
        if iid is not None:
            self.focused = iid
        return self.focused

    def see(self, iid):
        self.seen = iid


class _Notebook:
    def __init__(self):
        self.selected = None

    def select(self, value=None):
        if value is not None:
            self.selected = value
        return self.selected


class KnowledgeRelationshipNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

        self.client_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.client_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="202",
            external_namespace="eqclient:zone",
        )
        stone_page = self._source("zone:351", "The Stone Hive", "zone")
        blight_page = self._source("zone:202", "Blightfire Moors", "zone")
        self.provider_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            source_page_id=stone_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=351",
            external_id="zone:351",
        )
        self.provider_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            source_page_id=blight_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=202",
            external_id="zone:202",
        )
        self.db.upsert_relationship(
            self.provider_stone,
            self.provider_blight,
            "connected_to",
            source_page_id=stone_page,
            evidence="Blightfire Moors / south",
            data={"confidence": "structured"},
        )
        ProviderZoneReconciliationCatalog(self.db).reconcile()

        quest_page = self._source("quest:5001", "A Hive Inquiry", "quest")
        self.quest = self.db.upsert_entity(
            kind="quest",
            name="A Hive Inquiry",
            source_page_id=quest_page,
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=5001",
            external_id="quest:5001",
        )
        npc1_page = self._source("npc:1001", "Bixie Scout", "npc")
        npc2_page = self._source("npc:1002", "Bixie Scout", "npc")
        self.npc1 = self.db.upsert_entity(
            kind="npc",
            name="Bixie Scout",
            source_page_id=npc1_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1001",
            external_id="npc:1001",
        )
        self.npc2 = self.db.upsert_entity(
            kind="npc",
            name="Bixie Scout",
            source_page_id=npc2_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1002",
            external_id="npc:1002",
        )
        item_page = self._source("item:7001", "Hive Token", "item")
        self.item = self.db.upsert_entity(
            kind="item",
            name="Hive Token",
            source_page_id=item_page,
            source_url="https://everquest.allakhazam.com/db/item.html?item=7001",
            external_id="item:7001",
        )

        self.db.upsert_relationship(
            self.quest,
            self.npc1,
            "started_by",
            source_page_id=quest_page,
            evidence="Quest Started By: Bixie Scout",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            self.quest,
            self.npc1,
            "objective_speak",
            source_page_id=quest_page,
            evidence="Speak with Bixie Scout",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            self.quest,
            self.npc2,
            "objective_kill",
            quantity=3,
            source_page_id=quest_page,
            evidence="Kill three Bixie Scout",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            self.quest,
            self.item,
            "quest_item",
            source_page_id=quest_page,
            evidence="Quest Items: Hive Token",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            self.npc1,
            self.provider_stone,
            "found_in",
            source_page_id=npc1_page,
            evidence="Known Habitats: The Stone Hive",
            data={"confidence": "structured"},
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _source(self, key: str, title: str, entity_type: str) -> int:
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

    def _fake_app(self, selected_entity_id: int):
        app = type("FakeApp", (), {})()
        app.db = self.db
        app.search_var = _Var()
        app.kind_var = _Var("all")
        app.entity_tree = _Tree()
        app.notebook = _Notebook()
        app.knowledge_tab = "knowledge"
        app._knowledge_kind_nodes = {}
        app._knowledge_entity_by_item = {}
        app._knowledge_relationship_history = []
        app.shown = []

        def selected():
            if not app.entity_tree.selected:
                return selected_entity_id
            iid = app.entity_tree.selected[0]
            return int(iid.split(":", 1)[1]) if iid.startswith("entity:") else None

        app._selected_entity_id = selected

        def search():
            name = app.search_var.get()
            kind = app.kind_var.get()
            rows = app.db.conn.execute(
                "SELECT id FROM entities WHERE name=? AND kind=? ORDER BY id",
                (name, kind),
            ).fetchall()
            app.entity_tree.items = {f"entity:{int(row['id'])}" for row in rows}
            app._knowledge_entity_by_item = {
                f"entity:{int(row['id'])}": int(row["id"]) for row in rows
            }

        app._search_knowledge = search
        app._populate_knowledge_kind = lambda _kind, _node: None
        app._show_entity = lambda: app.shown.append(app._selected_entity_id())
        return app

    def test_same_target_facts_aggregate_but_duplicate_names_keep_exact_ids(self):
        choices = knowledge_related_entity_choices(self.db, self.quest)
        npc_choices = [choice for choice in choices if choice.entity_kind == "npc"]
        self.assertEqual(len(npc_choices), 2)
        by_id = {choice.entity_id: choice for choice in npc_choices}
        self.assertEqual(set(by_id), {self.npc1, self.npc2})
        self.assertEqual(by_id[self.npc1].fact_count, 2)
        self.assertEqual(
            set(by_id[self.npc1].relation_labels),
            {"Started by", "Speak with"},
        )
        self.assertEqual(by_id[self.npc2].fact_count, 1)
        self.assertEqual(by_id[self.npc2].relation_labels, ("Kill objective",))

        labels = knowledge_related_choice_labels(tuple(npc_choices))
        self.assertTrue(any("Started by" in label and "Speak with" in label for label in labels))
        self.assertTrue(all("Allakhazam mirror-2026-08-14" in label for label in labels))

    def test_linked_provider_zone_relationship_opens_canonical_gameplay_zone(self):
        choices = knowledge_related_entity_choices(self.db, self.npc1)
        zone = next(choice for choice in choices if choice.entity_kind == "zone")
        self.assertEqual(zone.entity_id, self.client_stone)
        self.assertEqual(zone.entity_name, "The Stone Hive")
        self.assertEqual(zone.relation_labels, ("Found in",))
        self.assertNotEqual(zone.entity_id, self.provider_stone)

    def test_open_exact_id_selects_correct_duplicate_and_back_restores_previous(self):
        app = self._fake_app(self.quest)
        self.assertTrue(open_knowledge_entity_id(app, self.npc2))
        self.assertEqual(app._selected_entity_id(), self.npc2)
        self.assertEqual(app.entity_tree.focused, f"entity:{self.npc2}")
        self.assertEqual(app.entity_tree.seen, f"entity:{self.npc2}")
        self.assertEqual(app.notebook.selected, "knowledge")
        self.assertEqual(app._knowledge_relationship_history, [self.quest])
        self.assertEqual(app.shown[-1], self.npc2)

        self.assertTrue(knowledge_relationship_back(app))
        self.assertEqual(app._selected_entity_id(), self.quest)
        self.assertEqual(app._knowledge_relationship_history, [])
        self.assertEqual(app.shown[-1], self.quest)

    def test_exact_id_is_injected_when_lazy_child_limit_omits_target(self):
        app = self._fake_app(self.quest)

        def limited_search():
            app.entity_tree.items = {"kind:npc", f"entity:{self.npc1}"}
            app._knowledge_kind_nodes = {"npc": "kind:npc"}
            app._knowledge_entity_by_item = {f"entity:{self.npc1}": self.npc1}

        app._search_knowledge = limited_search
        app._populate_knowledge_kind = lambda _kind, _node: None

        self.assertTrue(open_knowledge_entity_id(app, self.npc2))
        self.assertTrue(app.entity_tree.exists(f"entity:{self.npc2}"))
        self.assertEqual(app._knowledge_entity_by_item[f"entity:{self.npc2}"], self.npc2)
        self.assertEqual(app._selected_entity_id(), self.npc2)
        self.assertEqual(app._knowledge_relationship_history, [self.quest])

    def test_finalized_runtime_projects_same_relationship_choices_read_only(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="knowledge-relationship-navigation-test",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            builder = knowledge_related_entity_choices(self.db, self.quest)
            packaged = knowledge_related_entity_choices(runtime, self.quest)
            self.assertEqual(
                [(c.entity_id, c.relation_labels, c.relationship_ids) for c in packaged],
                [(c.entity_id, c.relation_labels, c.relationship_ids) for c in builder],
            )
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entity_relationships SET relation='mutated'")
        finally:
            runtime.close()

    def test_installer_subclasses_current_app_without_replacing_parent_behavior(self):
        original = app_module.EverQuestieApp

        class FakeBase:
            def _build_ui(self):
                self.parent_built = True

        try:
            app_module.EverQuestieApp = FakeBase
            install_knowledge_relationship_navigation_ui()
            installed = app_module.EverQuestieApp
            self.assertTrue(issubclass(installed, FakeBase))
        finally:
            app_module.EverQuestieApp = original


if __name__ == "__main__":
    unittest.main()
