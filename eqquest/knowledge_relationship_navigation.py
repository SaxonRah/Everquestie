from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .world_entity_detail import build_world_entity_context_for_id


@dataclass(frozen=True, slots=True)
class KnowledgeRelatedEntityChoice:
    selected_entity_id: int
    entity_id: int
    entity_name: str
    entity_kind: str
    relation_labels: tuple[str, ...]
    source_labels: tuple[str, ...]
    relationship_ids: tuple[int, ...]
    preview_fact_count: int

    @property
    def fact_count(self) -> int:
        return len(self.relationship_ids)

    @property
    def relation_text(self) -> str:
        return ", ".join(self.relation_labels)

    @property
    def source_text(self) -> str:
        return ", ".join(self.source_labels)


def _unique_text(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def knowledge_related_entity_choices(
    db: Database,
    entity_id: int,
) -> tuple[KnowledgeRelatedEntityChoice, ...]:
    """Return exact entity-ID navigation targets from normalized world relationships.

    This is a Knowledge graph projection, not a gameplay/navigation projection. It may
    expose provider-only entities as knowledge. For safely linked provider-zone facts,
    ``display_other_entity_id`` already points at the canonical gameplay-zone entity.

    No display name is re-resolved and no reverse relationship row is synthesized.
    Multiple facts that point at the same display target are aggregated into one choice.
    """
    selected = db.entity(int(entity_id))
    if selected is None:
        return ()
    context = build_world_entity_context_for_id(db, int(entity_id))
    if context is None:
        return ()

    grouped: dict[int, list] = {}
    for fact in context.relationships:
        target_id = int(fact.display_other_entity_id)
        if target_id == int(entity_id):
            continue
        if db.entity(target_id) is None:
            continue
        grouped.setdefault(target_id, []).append(fact)

    choices: list[KnowledgeRelatedEntityChoice] = []
    for target_id, facts in grouped.items():
        target = db.entity(target_id)
        if target is None:
            continue
        choices.append(
            KnowledgeRelatedEntityChoice(
                selected_entity_id=int(entity_id),
                entity_id=target_id,
                entity_name=str(target["name"] or facts[0].display_other_name or ""),
                entity_kind=str(target["kind"] or facts[0].other_kind or ""),
                relation_labels=_unique_text(fact.label for fact in facts),
                source_labels=_unique_text(fact.source_label for fact in facts),
                relationship_ids=tuple(dict.fromkeys(int(fact.relationship_id) for fact in facts)),
                preview_fact_count=sum(1 for fact in facts if fact.preview),
            )
        )

    choices.sort(
        key=lambda choice: (
            choice.entity_kind.casefold(),
            choice.entity_name.casefold(),
            choice.entity_id,
        )
    )
    return tuple(choices)


def open_knowledge_entity_id(app, entity_id: int, *, record_history: bool = True) -> bool:
    """Open one exact Knowledge entity ID without using the hidden Search tab.

    The normal Knowledge filter/tree is reused so every existing action (track quest,
    source, packaged Map location) naturally follows the newly selected row.
    """
    row = app.db.entity(int(entity_id))
    if row is None:
        return False

    current = app._selected_entity_id()
    if record_history and current is not None and int(current) != int(entity_id):
        history = getattr(app, "_knowledge_relationship_history", None)
        if history is None:
            history = []
            app._knowledge_relationship_history = history
        history.append(int(current))
        if len(history) > 100:
            del history[:-100]

    app.search_var.set(str(row["name"] or ""))
    app.kind_var.set(str(row["kind"] or "all"))
    app._search_knowledge()

    iid = f"entity:{int(entity_id)}"
    tree = app.entity_tree
    if not tree.exists(iid):
        kind = str(row["kind"] or "")
        kind_node = getattr(app, "_knowledge_kind_nodes", {}).get(kind)
        if kind_node and tree.exists(kind_node):
            app._populate_knowledge_kind(kind, kind_node)
    if not tree.exists(iid):
        return False

    tree.selection_set(iid)
    tree.focus(iid)
    tree.see(iid)
    app._show_entity()
    try:
        app.notebook.select(app.knowledge_tab)
    except Exception:
        pass
    return True


def knowledge_relationship_back(app) -> bool:
    history = getattr(app, "_knowledge_relationship_history", None)
    if not history:
        return False
    while history:
        entity_id = int(history.pop())
        if open_knowledge_entity_id(app, entity_id, record_history=False):
            return True
    return False
