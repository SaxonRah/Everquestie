from __future__ import annotations


_PACKAGED_UI_POLICY_MARKER = "_everquestie_packaged_ui_entrypoint_policy"
_OPEN_SEARCH_BUTTON_TEXT = "Open Search tab"
_KNOWLEDGE_MAP_BUTTON_TEXT = "Map location"
_LIVE_MAP_BUTTON_TEXT = "Map objective"


def _widget_children(widget) -> list:
    try:
        return list(widget.winfo_children())
    except Exception:
        return []


def _hide_button_text(root, text: str) -> int:
    """Hide packed descendants whose visible button text exactly matches ``text``.

    The legacy app builds the Knowledge controls before runtime policy knows whether
    the database is a mutable builder DB or an immutable packaged snapshot, and that
    button was not retained as an attribute. Keep the compatibility boundary narrow:
    match the exact legacy label and hide only that packed control.
    """
    hidden = 0
    stack = _widget_children(root)
    while stack:
        widget = stack.pop()
        stack.extend(_widget_children(widget))
        try:
            label = str(widget.cget("text"))
        except Exception:
            continue
        if label != text:
            continue
        try:
            widget.pack_forget()
        except Exception:
            continue
        hidden += 1
    return hidden


def _packaged_runtime(app) -> bool:
    checker = getattr(app, "_packaged_runtime", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    return not getattr(getattr(app, "db", None), "knowledge_writable", True)


def _install_knowledge_map_button(app) -> bool:
    """Add one normal-user Knowledge action without rebuilding the legacy pane."""
    if not _packaged_runtime(app):
        return False
    if getattr(app, "knowledge_map_location_button", None) is not None:
        return False
    tree = getattr(app, "entity_tree", None)
    parent = getattr(tree, "master", None)
    if parent is None:
        return False

    from tkinter import ttk

    button = ttk.Button(
        parent,
        text=_KNOWLEDGE_MAP_BUTTON_TEXT,
        command=app._map_selected_knowledge_location,
    )
    # The legacy Knowledge left pane owns row 0 (tree), row 1 (horizontal scroll),
    # and row 2 (track/untrack/source actions). Keep this packaged-only action on its
    # own row so we do not need to copy or reinterpret the base UI builder.
    button.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
    app.knowledge_map_location_button = button
    return True


def _install_live_map_button(app) -> bool:
    """Add an explicit Live objective action beside the tracked-quest surface."""
    if not _packaged_runtime(app):
        return False
    if getattr(app, "live_map_objective_button", None) is not None:
        return False
    tree = getattr(app, "tracked_tree", None)
    parent = getattr(tree, "master", None)
    if parent is None:
        return False

    from tkinter import ttk

    button = ttk.Button(
        parent,
        text=_LIVE_MAP_BUTTON_TEXT,
        command=app._map_selected_live_objective,
    )
    # Base Live uses rows 0-5 in the right pane. Keep the packaged action additive
    # instead of copying/rebuilding the legacy control row.
    button.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
    app.live_map_objective_button = button
    return True


def apply_packaged_ui_visibility(app) -> int:
    """Remove normal-user entry points to hidden builder/developer tabs."""
    if not _packaged_runtime(app):
        return 0

    hidden = _hide_button_text(app.knowledge_tab, _OPEN_SEARCH_BUTTON_TEXT)
    # Re-assert the hidden-tab policy as well. ttk.Notebook.select(hidden_child)
    # makes that page visible again, so hiding the button alone would leave a future
    # accidental caller able to resurrect builder/developer UI.
    for tab_name in ("search_tab", "import_tab"):
        tab = getattr(app, tab_name, None)
        if tab is None:
            continue
        try:
            app.notebook.hide(tab)
        except Exception:
            pass
    return hidden


def guard_packaged_notebook_selection(app, _event=None) -> bool:
    """Return hidden developer tabs to Knowledge if code selects them in user mode."""
    if not _packaged_runtime(app):
        return False
    try:
        selected = str(app.notebook.select())
    except Exception:
        return False

    hidden_tabs = {
        str(tab)
        for tab in (getattr(app, "search_tab", None), getattr(app, "import_tab", None))
        if tab is not None
    }
    if selected not in hidden_tabs:
        return False

    # Redirect before re-hiding because select(hidden_tab) itself unhides the page.
    fallback = getattr(app, "knowledge_tab", None) or getattr(app, "live_tab", None)
    if fallback is not None:
        try:
            app.notebook.select(fallback)
        except Exception:
            pass
    apply_packaged_ui_visibility(app)
    return True


def install_packaged_ui_policy() -> None:
    """Install final normal-user visibility and map-action guards."""
    from . import app as app_module
    from .knowledge_map_choices import knowledge_map_choices
    from .live_quest_map import live_quest_map_choices

    current_app = app_module.EverQuestieApp
    current_build_ui = current_app._build_ui
    current_tracked_tree_selected = current_app._tracked_tree_selected
    if getattr(current_build_ui, _PACKAGED_UI_POLICY_MARKER, False):
        return

    # Preserve the runtime-policy closure convention used by existing policy tests.
    from .route_guidance_ui import RouteGuidanceFrame as TravelFrame

    def _on_packaged_notebook_tab_changed(self, event=None) -> None:
        guard_packaged_notebook_selection(self, event)

    def _map_selected_knowledge_location(self) -> None:
        entity_id = self._selected_entity_id()
        if entity_id is None:
            self.status.set("Select a Knowledge entity first.")
            return
        result = knowledge_map_choices(
            self.db,
            entity_id,
            self.state_model.current_zone,
        )
        if not result.ready:
            self.status.set(result.reason)
            return

        if len(result.choices) == 1:
            choice = result.choices[0]
        else:
            from .knowledge_location_ui import ask_knowledge_map_choice

            choice = ask_knowledge_map_choice(
                self,
                result.selected_entity_name,
                result.current_zone_name,
                result.choices,
            )
            if choice is None:
                self.status.set("Map location selection cancelled.")
                return

        # The runtime Map owner remains responsible for local-map readiness, local
        # variant selection, tab focus, coordinate conversion, and rendering. The
        # chooser receives only canonical current-zone, game-space choices.
        self._focus_navigation_map_target(
            choice.zone_name,
            choice.x,
            choice.y,
            choice.z,
            choice.map_label,
        )

    def _map_selected_live_objective(self) -> None:
        selected_step = self._tracked_selected_step()
        if selected_step is not None:
            quest_id, step_order = selected_step
        else:
            quest_id = self._tracked_selected_quest_id()
            step_order = None
        if quest_id is None:
            self.status.set("Select a tracked quest or objective first.")
            return

        result = live_quest_map_choices(
            self.db,
            quest_id,
            self.state_model.current_zone,
            selected_step_order=step_order,
        )
        if not result.ready or result.objective is None or result.choice_set is None:
            self.status.set(result.reason)
            return

        choices = result.choice_set.choices
        if len(choices) == 1:
            choice = choices[0]
        else:
            from .knowledge_location_ui import ask_knowledge_map_choice

            title = (
                f"{result.objective.quest_name} — step {result.objective.step_order}: "
                f"{result.objective.target_name}"
            )
            choice = ask_knowledge_map_choice(
                self,
                title,
                result.choice_set.current_zone_name,
                choices,
            )
            if choice is None:
                self.status.set("Map objective selection cancelled.")
                return

        self._focus_navigation_map_target(
            choice.zone_name,
            choice.x,
            choice.y,
            choice.z,
            choice.map_label,
        )

    def _tracked_tree_selected(self, event=None) -> None:
        # The legacy handler resolves names and calls MapViewer.focus_entity()
        # directly. Preserve it for source-checkout/builder mode, but packaged users
        # use the explicit Map objective action so every location passes through the
        # canonical provider-zone/current-zone safety projection first.
        if not _packaged_runtime(self):
            current_tracked_tree_selected(self, event)

    def _build_ui(self) -> None:
        _ = TravelFrame
        current_build_ui(self)
        if not _packaged_runtime(self):
            return
        _install_knowledge_map_button(self)
        _install_live_map_button(self)
        apply_packaged_ui_visibility(self)
        self.notebook.bind(
            "<<NotebookTabChanged>>",
            self._on_packaged_notebook_tab_changed,
            add="+",
        )

    setattr(_build_ui, _PACKAGED_UI_POLICY_MARKER, True)
    current_app._on_packaged_notebook_tab_changed = _on_packaged_notebook_tab_changed
    current_app._map_selected_knowledge_location = _map_selected_knowledge_location
    current_app._map_selected_live_objective = _map_selected_live_objective
    current_app._tracked_tree_selected = _tracked_tree_selected
    current_app._build_ui = _build_ui
