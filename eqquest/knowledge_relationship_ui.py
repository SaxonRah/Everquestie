from __future__ import annotations

import tkinter as tk
from tkinter import simpledialog, ttk

from .knowledge_relationship_navigation import (
    KnowledgeRelatedEntityChoice,
    knowledge_related_entity_choices,
    knowledge_relationship_back,
    open_knowledge_entity_id,
)


_KNOWLEDGE_RELATIONSHIP_UI_MARKER = "_everquestie_knowledge_relationship_navigation_ui"


def knowledge_related_choice_labels(
    choices: tuple[KnowledgeRelatedEntityChoice, ...],
) -> tuple[str, ...]:
    labels: list[str] = []
    for choice in choices:
        relation = choice.relation_text or "related"
        source = choice.source_text or "EverQuestie knowledge"
        facts = f"{choice.fact_count} fact" + ("s" if choice.fact_count != 1 else "")
        preview = (
            f" — {choice.preview_fact_count} preview fact"
            + ("s" if choice.preview_fact_count != 1 else "")
            if choice.preview_fact_count
            else ""
        )
        labels.append(
            f"[{choice.entity_kind}] {choice.entity_name} — {relation} — {source} — {facts}{preview}"
        )
    return tuple(labels)


class _KnowledgeRelatedEntityDialog(simpledialog.Dialog):
    def __init__(
        self,
        parent,
        *,
        entity_name: str,
        choices: tuple[KnowledgeRelatedEntityChoice, ...],
    ):
        self.entity_name = str(entity_name)
        self.choices = tuple(choices)
        self.result: KnowledgeRelatedEntityChoice | None = None
        self._listbox = None
        super().__init__(parent, title=f"Open related knowledge — {self.entity_name}")

    def body(self, master):
        ttk.Label(
            master,
            text=(
                f"Choose an evidence-backed entity related to {self.entity_name}.\n"
                "EverQuestie will open the exact stored entity ID in Knowledge."
            ),
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._listbox = tk.Listbox(
            master,
            exportselection=False,
            width=110,
            height=min(14, max(4, len(self.choices))),
        )
        self._listbox.grid(row=1, column=0, sticky="nsew")
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        for label in knowledge_related_choice_labels(self.choices):
            self._listbox.insert("end", label)
        if self.choices:
            self._listbox.selection_set(0)
            self._listbox.activate(0)
        self._listbox.bind("<Double-1>", lambda _event: self.ok())
        return self._listbox

    def validate(self) -> bool:
        return bool(self._listbox is not None and self._listbox.curselection())

    def apply(self) -> None:
        if self._listbox is None:
            return
        selected = self._listbox.curselection()
        if not selected:
            return
        index = int(selected[0])
        if 0 <= index < len(self.choices):
            self.result = self.choices[index]


def ask_knowledge_related_entity(
    parent,
    entity_name: str,
    choices: tuple[KnowledgeRelatedEntityChoice, ...],
) -> KnowledgeRelatedEntityChoice | None:
    ordered = tuple(
        sorted(
            choices,
            key=lambda choice: (
                choice.entity_kind.casefold(),
                choice.entity_name.casefold(),
                choice.entity_id,
            ),
        )
    )
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    return _KnowledgeRelatedEntityDialog(
        parent,
        entity_name=entity_name,
        choices=ordered,
    ).result


def _packaged_runtime(app) -> bool:
    checker = getattr(app, "_packaged_runtime", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    return not getattr(getattr(app, "db", None), "knowledge_writable", True)


def _set_back_button_state(app) -> None:
    button = getattr(app, "knowledge_relationship_back_button", None)
    if button is None:
        return
    state = "normal" if getattr(app, "_knowledge_relationship_history", []) else "disabled"
    try:
        button.configure(state=state)
    except Exception:
        pass


def install_knowledge_relationship_navigation_ui() -> None:
    """Install packaged-only exact-ID relationship navigation in Knowledge."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _KNOWLEDGE_RELATIONSHIP_UI_MARKER, False):
        return

    class KnowledgeRelationshipNavigationApp(current_app):
        def _build_ui(self) -> None:
            super()._build_ui()
            self._knowledge_relationship_history: list[int] = []

            # Runtime policy constructs Travel inside super(). The outer composed app
            # already owns the exact-ID opener, so connect that callback here instead
            # of teaching runtime policy or Travel how Knowledge tree selection works.
            travel = getattr(self, "travel_tab", None)
            if travel is not None:
                travel.on_knowledge_entity = self._open_knowledge_entity_exact

            if not _packaged_runtime(self):
                return

            tree = getattr(self, "entity_tree", None)
            parent = getattr(tree, "master", None)
            if parent is None:
                return
            controls = ttk.Frame(parent)
            controls.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
            self.knowledge_open_related_button = ttk.Button(
                controls,
                text="Open related…",
                command=self._open_related_knowledge_entity,
            )
            self.knowledge_open_related_button.pack(side="left")
            self.knowledge_relationship_back_button = ttk.Button(
                controls,
                text="Back",
                command=self._knowledge_relationship_back,
                state="disabled",
            )
            self.knowledge_relationship_back_button.pack(side="left", padx=(6, 0))

        def _open_knowledge_entity_exact(self, entity_id: int) -> bool:
            """Shared exact-ID Knowledge handoff for other composed player surfaces."""
            opened = open_knowledge_entity_id(self, int(entity_id), record_history=True)
            _set_back_button_state(self)
            if opened:
                row = self.db.entity(int(entity_id))
                if row is not None:
                    self.status.set(f"Knowledge: [{row['kind']}] {row['name']}")
                return True
            self.status.set("Knowledge entity could not be opened by exact ID.")
            return False

        def _open_related_knowledge_entity(self) -> bool:
            entity_id = self._selected_entity_id()
            if entity_id is None:
                self.status.set("Select a Knowledge entity first.")
                return False
            entity = self.db.entity(entity_id)
            if entity is None:
                self.status.set("Selected Knowledge entity no longer exists.")
                return False
            choices = knowledge_related_entity_choices(self.db, entity_id)
            if not choices:
                self.status.set(f"No evidence-backed related entities are known for {entity['name']}.")
                return False

            choice = ask_knowledge_related_entity(
                self,
                str(entity["name"] or ""),
                choices,
            )
            if choice is None:
                self.status.set("Related entity selection cancelled.")
                return False
            opened = self._open_knowledge_entity_exact(choice.entity_id)
            if opened:
                self.status.set(
                    f"Knowledge: [{choice.entity_kind}] {choice.entity_name} — {choice.relation_text or 'related'}"
                )
                return True
            self.status.set("Related entity could not be opened in Knowledge.")
            return False

        def _knowledge_relationship_back(self) -> bool:
            opened = knowledge_relationship_back(self)
            _set_back_button_state(self)
            if opened:
                selected = self._selected_entity_id()
                row = self.db.entity(selected) if selected is not None else None
                if row is not None:
                    self.status.set(f"Knowledge: [{row['kind']}] {row['name']}")
                return True
            self.status.set("No previous related Knowledge entity.")
            return False

    setattr(KnowledgeRelationshipNavigationApp, _KNOWLEDGE_RELATIONSHIP_UI_MARKER, True)
    app_module.EverQuestieApp = KnowledgeRelationshipNavigationApp
