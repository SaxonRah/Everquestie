from __future__ import annotations


_PACKAGED_UI_POLICY_MARKER = "_everquestie_packaged_ui_entrypoint_policy"
_OPEN_SEARCH_BUTTON_TEXT = "Open Search tab"


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
    """Install final normal-user visibility guards after the runtime UI policies."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    current_build_ui = current_app._build_ui
    if getattr(current_build_ui, _PACKAGED_UI_POLICY_MARKER, False):
        return

    # Preserve the runtime-policy closure convention used by existing policy tests.
    from .route_guidance_ui import RouteGuidanceFrame as TravelFrame

    def _on_packaged_notebook_tab_changed(self, event=None) -> None:
        guard_packaged_notebook_selection(self, event)

    def _build_ui(self) -> None:
        _ = TravelFrame
        current_build_ui(self)
        if not _packaged_runtime(self):
            return
        apply_packaged_ui_visibility(self)
        self.notebook.bind(
            "<<NotebookTabChanged>>",
            self._on_packaged_notebook_tab_changed,
            add="+",
        )

    setattr(_build_ui, _PACKAGED_UI_POLICY_MARKER, True)
    current_app._on_packaged_notebook_tab_changed = _on_packaged_notebook_tab_changed
    current_app._build_ui = _build_ui
