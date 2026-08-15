from __future__ import annotations

from types import SimpleNamespace
import unittest

from eqquest.knowledge_coverage_ui import install_knowledge_coverage_ui
from eqquest.map_loading_policy import install_map_loading_policy
from eqquest.packaged_ui_policy import (
    _OPEN_SEARCH_BUTTON_TEXT,
    apply_packaged_ui_visibility,
    guard_packaged_notebook_selection,
    install_packaged_ui_policy,
)
from eqquest.route_guidance_ui import RouteGuidanceFrame
from eqquest.runtime_policy import install_runtime_policy


class _Widget:
    def __init__(self, name: str, *, text: str | None = None, children=()):
        self.name = name
        self.text = text
        self.children = list(children)
        self.hidden = False

    def __str__(self) -> str:
        return self.name

    def winfo_children(self):
        return list(self.children)

    def cget(self, key: str):
        if key != "text" or self.text is None:
            raise KeyError(key)
        return self.text

    def pack_forget(self):
        self.hidden = True


class _Notebook:
    def __init__(self, selected):
        self.selected = str(selected)
        self.hidden: list[str] = []
        self.bindings: list[tuple[str, object, str | None]] = []

    def select(self, tab=None):
        if tab is None:
            return self.selected
        self.selected = str(tab)
        return self.selected

    def hide(self, tab):
        value = str(tab)
        if value not in self.hidden:
            self.hidden.append(value)

    def bind(self, event, callback, add=None):
        self.bindings.append((event, callback, add))


class PackagedUiPolicyTests(unittest.TestCase):
    def _app(self, *, packaged: bool):
        open_search = _Widget("open-search", text=_OPEN_SEARCH_BUTTON_TEXT)
        local_search = _Widget("local-search", text="Search local")
        controls = _Widget("controls", children=(open_search, local_search))
        knowledge = _Widget("knowledge", children=(controls,))
        search = _Widget("search")
        sources = _Widget("sources")
        notebook = _Notebook(knowledge)
        app = SimpleNamespace(
            knowledge_tab=knowledge,
            search_tab=search,
            import_tab=sources,
            live_tab=_Widget("live"),
            notebook=notebook,
            _packaged_runtime=lambda: packaged,
        )
        return app, open_search, local_search

    def test_packaged_visibility_removes_open_search_and_reasserts_hidden_tabs(self):
        app, open_search, local_search = self._app(packaged=True)

        hidden = apply_packaged_ui_visibility(app)

        self.assertEqual(hidden, 1)
        self.assertTrue(open_search.hidden)
        self.assertFalse(local_search.hidden)
        self.assertEqual(set(app.notebook.hidden), {"search", "sources"})

    def test_builder_mode_keeps_search_entrypoint_and_tabs_untouched(self):
        app, open_search, _ = self._app(packaged=False)

        hidden = apply_packaged_ui_visibility(app)

        self.assertEqual(hidden, 0)
        self.assertFalse(open_search.hidden)
        self.assertEqual(app.notebook.hidden, [])

    def test_programmatic_selection_cannot_resurrect_packaged_search_or_sources(self):
        app, _, _ = self._app(packaged=True)
        app.notebook.select(app.search_tab)

        redirected = guard_packaged_notebook_selection(app)

        self.assertTrue(redirected)
        self.assertEqual(app.notebook.select(), "knowledge")
        self.assertIn("search", app.notebook.hidden)
        self.assertIn("sources", app.notebook.hidden)

    def test_normal_packaged_tab_selection_is_left_alone(self):
        app, _, _ = self._app(packaged=True)
        app.notebook.select(app.knowledge_tab)
        self.assertFalse(guard_packaged_notebook_selection(app))
        self.assertEqual(app.notebook.select(), "knowledge")

    def test_installer_preserves_runtime_travel_closure_and_is_idempotent(self):
        install_runtime_policy()
        install_map_loading_policy()
        install_knowledge_coverage_ui()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        first = app_module.EverQuestieApp._build_ui
        closure = {
            name: cell.cell_contents
            for name, cell in zip(first.__code__.co_freevars, first.__closure__ or ())
        }
        self.assertIs(closure.get("TravelFrame"), RouteGuidanceFrame)

        install_packaged_ui_policy()
        self.assertIs(app_module.EverQuestieApp._build_ui, first)


if __name__ == "__main__":
    unittest.main()
