from __future__ import annotations


_COVERAGE_UI_MARKER = "_everquestie_knowledge_coverage_ui"


def diagnostic_text_with_coverage(db, base_text: str) -> str:
    """Append the read-only normalization projection to existing DB diagnostics."""
    from .knowledge_coverage import normalization_coverage_text

    base = str(base_text or "").rstrip()
    coverage = normalization_coverage_text(db)
    return f"{base}\n\n{coverage}" if base else coverage


def _append_source_summary_coverage(app) -> None:
    widget = getattr(app, "source_summary_text", None)
    if widget is None:
        return
    from .knowledge_coverage import normalization_coverage_text

    widget.configure(state="normal")
    try:
        current = str(widget.get("1.0", "end-1c") or "").rstrip()
        if current:
            widget.insert("end", "\n\n")
        widget.insert("end", normalization_coverage_text(app.db))
    finally:
        widget.configure(state="disabled")


def install_knowledge_coverage_ui() -> None:
    """Augment the already-installed app class with read-only coverage diagnostics.

    Call this after :func:`runtime_policy.install_runtime_policy`. The resulting class
    therefore preserves every packaged-runtime storage/import guard and only extends
    text rendering. Builder/source-checkout and packaged launches receive the same DB
    interpretation without introducing a second importer or mirror scanner.
    """
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _COVERAGE_UI_MARKER, False):
        return

    class KnowledgeCoverageEverQuestieApp(current_app):
        def _database_diagnostic_text(self) -> str:
            return diagnostic_text_with_coverage(
                self.db,
                super()._database_diagnostic_text(),
            )

        def _refresh_source_summary(self) -> None:
            super()._refresh_source_summary()
            _append_source_summary_coverage(self)

    setattr(KnowledgeCoverageEverQuestieApp, _COVERAGE_UI_MARKER, True)
    app_module.EverQuestieApp = KnowledgeCoverageEverQuestieApp
