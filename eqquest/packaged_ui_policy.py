from __future__ import annotations


_PACKAGED_UI_POLICY_MARKER = "_everquestie_packaged_ui_entrypoint_policy"
_OPEN_SEARCH_BUTTON_TEXT = "Open Search tab"
_KNOWLEDGE_MAP_BUTTON_TEXT = "Map location"
_KNOWLEDGE_ROUTE_BUTTON_TEXT = "Route to location"
_LIVE_OBJECTIVE_BUTTON_TEXT = "Navigate objective"


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


def _knowledge_action_parent(app):
    tree = getattr(app, "entity_tree", None)
    return getattr(tree, "master", None)


def _live_objective_parent(app):
    tree = getattr(app, "tracked_tree", None)
    return getattr(tree, "master", None)


def _install_knowledge_map_button(app) -> bool:
    """Add one normal-user Knowledge map action without rebuilding the legacy pane."""
    if not _packaged_runtime(app):
        return False
    if getattr(app, "knowledge_map_location_button", None) is not None:
        return False
    parent = _knowledge_action_parent(app)
    if parent is None:
        return False

    from tkinter import ttk

    button = ttk.Button(
        parent,
        text=_KNOWLEDGE_MAP_BUTTON_TEXT,
        command=app._map_selected_knowledge_location,
    )
    # The legacy Knowledge left pane owns row 0 (tree), row 1 (horizontal scroll),
    # and row 2 (track/untrack/source actions). Keep packaged-only actions below it
    # so we do not need to copy or reinterpret the base UI builder.
    button.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
    app.knowledge_map_location_button = button
    return True


def _install_knowledge_route_button(app) -> bool:
    """Add a cross-zone Knowledge→Travel handoff beside the current-zone map action."""
    if not _packaged_runtime(app):
        return False
    if getattr(app, "knowledge_route_location_button", None) is not None:
        return False
    parent = _knowledge_action_parent(app)
    if parent is None:
        return False

    from tkinter import ttk

    button = ttk.Button(
        parent,
        text=_KNOWLEDGE_ROUTE_BUTTON_TEXT,
        command=app._route_selected_knowledge_location,
    )
    button.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
    app.knowledge_route_location_button = button
    return True


def _install_live_objective_navigation(app) -> bool:
    """Add one smart Map/Travel action below tracked quest guidance."""
    if not _packaged_runtime(app):
        return False
    if getattr(app, "navigate_objective_button", None) is not None:
        return False
    parent = _live_objective_parent(app)
    if parent is None:
        return False

    import tkinter as tk
    from tkinter import ttk

    action = ttk.Frame(parent)
    action.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(6, 0))
    button = ttk.Button(
        action,
        text=_LIVE_OBJECTIVE_BUTTON_TEXT,
        command=app._navigate_selected_tracked_objective,
    )
    button.pack(side="left")
    app.objective_navigation_status_var = tk.StringVar(
        value="Select a tracked quest or objective to inspect navigation."
    )
    ttk.Label(
        parent,
        textvariable=app.objective_navigation_status_var,
        wraplength=390,
        justify="left",
    ).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    app.navigate_objective_button = button
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
    """Install final normal-user visibility and Knowledge/actionability guards."""
    from . import app as app_module
    from .knowledge_map_choices import knowledge_map_choices, knowledge_route_choices
    from .quest_objective_navigation import tracked_quest_objective_navigation

    current_app = app_module.EverQuestieApp
    current_build_ui = current_app._build_ui
    if getattr(current_build_ui, _PACKAGED_UI_POLICY_MARKER, False):
        return

    current_tracked_tree_selected = current_app._tracked_tree_selected
    current_refresh_guidance = current_app._refresh_guidance

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

    def _route_selected_knowledge_location(self) -> None:
        entity_id = self._selected_entity_id()
        if entity_id is None:
            self.status.set("Select a Knowledge entity first.")
            return
        result = knowledge_map_choices(
            self.db,
            entity_id,
            self.state_model.current_zone,
        )
        route_choices = knowledge_route_choices(result)
        if not route_choices:
            if result.ready:
                self.status.set(
                    f"{result.selected_entity_name} has a safe location in the current zone; use Map location."
                )
            else:
                self.status.set(result.reason)
            return

        if len(route_choices) == 1:
            choice = route_choices[0]
        else:
            from .knowledge_location_ui import ask_knowledge_route_choice

            choice = ask_knowledge_route_choice(
                self,
                result.selected_entity_name,
                result.current_zone_name,
                route_choices,
            )
            if choice is None:
                self.status.set("Route destination selection cancelled.")
                return

        travel = getattr(self, "travel_tab", None)
        if travel is None or not hasattr(travel, "route_to_zone"):
            self.status.set("Travel routing is not connected in this application surface.")
            return

        # Knowledge hands only the canonical remote destination to Travel. Travel owns
        # the live start zone, route computation, evidence rendering and next-hop map.
        self.notebook.select(self.travel_tab)
        routed = bool(self.travel_tab.route_to_zone(choice.zone_name))
        if routed:
            self.status.set(
                f"Travel route opened to {choice.zone_name} for {choice.route_label}."
            )
        else:
            self.status.set(
                f"No confirmed route to {choice.zone_name} is currently available; see Travel for details."
            )

    def _selected_tracked_objective(self):
        selected_step = self._tracked_selected_step()
        if selected_step:
            return int(selected_step[0]), int(selected_step[1])
        selected_quest = self._tracked_selected_quest_id()
        if selected_quest is not None:
            return int(selected_quest), None
        tracked = list(self.db.tracked_quests())
        if len(tracked) == 1:
            return int(tracked[0]["id"]), None
        return None

    def _selected_objective_navigation(self):
        selected = self._selected_tracked_objective()
        if selected is None:
            return None
        quest_id, step_order = selected
        return tracked_quest_objective_navigation(
            self.db,
            quest_id,
            self.state_model.current_zone,
            step_order=step_order,
        )

    def _refresh_objective_navigation_status(self) -> None:
        status_var = getattr(self, "objective_navigation_status_var", None)
        if status_var is None:
            return
        result = self._selected_objective_navigation()
        if result is None:
            status_var.set("Select a tracked quest/objective; with one tracked quest its active step is used automatically.")
            return
        prefix = f"Step {result.step_order}: " if result.step_order is not None else ""
        status_var.set(prefix + result.reason)

    def _navigate_selected_tracked_objective(self) -> None:
        result = self._selected_objective_navigation()
        if result is None:
            self.status.set("Select a tracked quest/objective first.")
            self._refresh_objective_navigation_status()
            return

        if result.map_ready:
            if len(result.map_choices) == 1:
                choice = result.map_choices[0]
            else:
                from .knowledge_location_ui import ask_knowledge_map_choice

                choice = ask_knowledge_map_choice(
                    self,
                    result.quest_name,
                    result.current_zone_name,
                    result.map_choices,
                )
                if choice is None:
                    self.status.set("Objective map location selection cancelled.")
                    return
            self._focus_navigation_map_target(
                choice.zone_name,
                choice.x,
                choice.y,
                choice.z,
                choice.map_label,
            )
            return

        if result.route_ready:
            if len(result.route_choices) == 1:
                choice = result.route_choices[0]
            else:
                from .knowledge_location_ui import ask_knowledge_route_choice

                choice = ask_knowledge_route_choice(
                    self,
                    result.quest_name,
                    result.current_zone_name,
                    result.route_choices,
                )
                if choice is None:
                    self.status.set("Objective route destination selection cancelled.")
                    return

            travel = getattr(self, "travel_tab", None)
            if travel is None or not hasattr(travel, "route_to_zone"):
                self.status.set("Travel routing is not connected in this application surface.")
                return
            self.notebook.select(self.travel_tab)
            routed = bool(self.travel_tab.route_to_zone(choice.zone_name))
            if routed:
                self.status.set(
                    f"Travel route opened to {choice.zone_name} for active objective: {result.objective_text}"
                )
            else:
                self.status.set(
                    f"No confirmed route to {choice.zone_name} is currently available; see Travel graph diagnostics."
                )
            return

        self.status.set(result.reason)
        self._refresh_objective_navigation_status()

    def _tracked_tree_selected(self, event=None) -> None:
        current_tracked_tree_selected(self, event)
        if _packaged_runtime(self):
            self._refresh_objective_navigation_status()

    def _refresh_guidance(self) -> None:
        current_refresh_guidance(self)
        if _packaged_runtime(self):
            self._refresh_objective_navigation_status()

    def _build_ui(self) -> None:
        _ = TravelFrame
        current_build_ui(self)
        if not _packaged_runtime(self):
            return
        _install_knowledge_map_button(self)
        _install_knowledge_route_button(self)
        _install_live_objective_navigation(self)
        self._refresh_objective_navigation_status()
        apply_packaged_ui_visibility(self)
        self.notebook.bind(
            "<<NotebookTabChanged>>",
            self._on_packaged_notebook_tab_changed,
            add="+",
        )

    setattr(_build_ui, _PACKAGED_UI_POLICY_MARKER, True)
    current_app._on_packaged_notebook_tab_changed = _on_packaged_notebook_tab_changed
    current_app._map_selected_knowledge_location = _map_selected_knowledge_location
    current_app._route_selected_knowledge_location = _route_selected_knowledge_location
    current_app._selected_tracked_objective = _selected_tracked_objective
    current_app._selected_objective_navigation = _selected_objective_navigation
    current_app._refresh_objective_navigation_status = _refresh_objective_navigation_status
    current_app._navigate_selected_tracked_objective = _navigate_selected_tracked_objective
    current_app._tracked_tree_selected = _tracked_tree_selected
    current_app._refresh_guidance = _refresh_guidance
    current_app._build_ui = _build_ui
