from __future__ import annotations

from unittest import mock
import unittest

from eqquest.map_loading_policy import _canvas_ready_for_initial_fit, install_map_loading_policy
from eqquest.runtime_policy import install_runtime_policy


class _Canvas:
    def __init__(self, *, mapped: bool, width: int, height: int):
        self.mapped = mapped
        self.width = width
        self.height = height

    def winfo_ismapped(self):
        return int(self.mapped)

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height


class _Notebook:
    def __init__(self, selected):
        self.selected = selected

    def select(self):
        return self.selected


class MapInitialFitTests(unittest.TestCase):
    def test_hidden_or_placeholder_canvas_is_not_ready_for_fit(self):
        self.assertFalse(_canvas_ready_for_initial_fit(_Canvas(mapped=False, width=900, height=700)))
        self.assertFalse(_canvas_ready_for_initial_fit(_Canvas(mapped=True, width=1, height=1)))
        self.assertTrue(_canvas_ready_for_initial_fit(_Canvas(mapped=True, width=900, height=700)))

    def test_new_map_never_restores_stale_camera_before_first_fit(self):
        install_runtime_policy()
        install_map_loading_policy()
        from eqquest import mapview as mapview_module

        viewer_class = mapview_module.MapViewerFrame
        viewer = object.__new__(viewer_class)
        self.assertFalse(viewer_class._restore_view(viewer))

    def test_fit_stays_pending_until_map_tab_has_real_visible_size(self):
        install_runtime_policy()
        install_map_loading_policy()
        from eqquest import mapview as mapview_module

        viewer_class = mapview_module.MapViewerFrame
        viewer = object.__new__(viewer_class)
        viewer.zone_map = object()
        viewer.canvas = _Canvas(mapped=False, width=1, height=1)
        viewer._fit_pending = False

        viewer_class.fit(viewer)

        self.assertTrue(viewer._fit_pending)

    def test_visible_canvas_delegates_to_normal_vector_fit(self):
        install_runtime_policy()
        install_map_loading_policy()
        from eqquest import mapview as mapview_module

        viewer_class = mapview_module.MapViewerFrame
        viewer = object.__new__(viewer_class)
        viewer.zone_map = object()
        viewer.canvas = _Canvas(mapped=True, width=900, height=700)
        viewer._fit_pending = True
        parent = viewer_class.__mro__[1]

        with mock.patch.object(parent, "fit", autospec=True, return_value=None) as parent_fit:
            viewer_class.fit(viewer)

        parent_fit.assert_called_once_with(viewer)

    def test_map_tab_selection_schedules_pending_fit_even_without_configure_event(self):
        install_runtime_policy()
        install_map_loading_policy()
        from eqquest import mapview as mapview_module

        viewer_class = mapview_module.MapViewerFrame
        viewer = object.__new__(viewer_class)
        viewer.zone_map = object()
        viewer._fit_pending = True
        viewer.fit = mock.Mock()
        viewer.after_idle = mock.Mock(side_effect=lambda callback: callback())

        viewer_class.present_map_tab(viewer)

        viewer.after_idle.assert_called_once()
        viewer.fit.assert_called_once_with()

    def test_notebook_handler_only_presents_map_page(self):
        install_runtime_policy()
        install_map_loading_policy()
        from eqquest import app as app_module

        app_class = app_module.EverQuestieApp
        app = object.__new__(app_class)
        app.map_tab = "map-page"
        app.map_view = mock.Mock()
        app.notebook = _Notebook("map-page")

        app_class._on_map_notebook_tab_changed(app)
        app.map_view.present_map_tab.assert_called_once_with()

        app.map_view.reset_mock()
        app.notebook.selected = "live-page"
        app_class._on_map_notebook_tab_changed(app)
        app.map_view.present_map_tab.assert_not_called()


if __name__ == "__main__":
    unittest.main()
