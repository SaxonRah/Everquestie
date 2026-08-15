from __future__ import annotations

from dataclasses import dataclass
import json

from .db import Database
from .knowledge_map_choices import (
    KnowledgeMapChoice,
    KnowledgeMapChoiceSet,
    KnowledgeRouteChoice,
    knowledge_route_choices,
)
from .locations import location_evidence_for_entity
from .world_entity_detail import build_world_entity_context_for_id
from .zone_authority import resolve_authoritative_zone


_OBJECTIVE_RELATION_LABELS = {
    "objective_kill": "kill target",
    "objective_source_creature": "loot source",
    "objective_turn_in_to": "turn-in NPC",
    "objective_speak": "speak target",
}

_OBJECTIVE_NPC_RELATIONS = frozenset(_OBJECTIVE_RELATION_LABELS)


@dataclass(frozen=True, slots=True)
class QuestObjectiveNavigationResult:
    status: str
    reason: str
    quest_id: int
    quest_name: str
    step_order: int | None
    objective_text: str
    current_zone_entity_id: int | None
    current_zone_name: str
    map_choices: tuple[KnowledgeMapChoice, ...] = ()
    route_choices: tuple[KnowledgeRouteChoice, ...] = ()

    @property
    def map_ready(self) -> bool:
        return self.status == "map_ready" and bool(self.map_choices)

    @property
    def route_ready(self) -> bool:
        return self.status == "route_ready" and bool(self.route_choices)


@dataclass(frozen=True, slots=True)
class _TargetSpec:
    entity_id: int
    entity_name: str
    relation: str
    relation_label: str
    source_labels: tuple[str, ...]


def _normalized(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def _source_tuple(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if value))


def _active_step_order(db: Database, quest_id: int) -> int | None:
    for tracked in db.tracked_quests():
        if int(tracked["id"]) == int(quest_id):
            return int(tracked["active_step"])
    for step in db.quest_steps(int(quest_id)):
        if not bool(int(step["complete"] or 0)):
            return int(step["step_order"])
    return None


def _step_for_quest(db: Database, quest_id: int, step_order: int | None):
    order = int(step_order) if step_order is not None else _active_step_order(db, quest_id)
    if order is None:
        return None
    return next(
        (step for step in db.quest_steps(int(quest_id)) if int(step["step_order"]) == order),
        None,
    )


def _rule(step) -> dict:
    try:
        value = json.loads(step["match_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _fallback_relation_label(step_rule: dict, description: str) -> tuple[str, str]:
    event = str(step_rule.get("event") or "").casefold()
    lowered = description.casefold()
    if event == "kill":
        return "objective_kill", "kill target"
    if event in {"npc_say", "say"}:
        if any(token in lowered for token in ("hand in", "give ", "bring back", "turn in")):
            return "objective_turn_in_to", "turn-in NPC"
        return "objective_speak", "speak target"
    return "objective", "objective target"


def _quest_objective_target_specs(db: Database, quest_id: int, step) -> tuple[_TargetSpec, ...]:
    context = build_world_entity_context_for_id(db, int(quest_id))
    if context is None:
        return ()

    description = str(step["description"] or "")
    description_key = _normalized(description)
    rule = _rule(step)
    npc_entity_id = (
        int(rule["npc_entity_id"])
        if rule.get("npc_entity_id") is not None
        else None
    )

    exact = []
    matching_id = []
    for fact in context.relationships:
        if (
            fact.direction != "out"
            or fact.other_kind != "npc"
            or fact.relation not in _OBJECTIVE_NPC_RELATIONS
        ):
            continue
        spec = _TargetSpec(
            entity_id=int(fact.other_entity_id),
            entity_name=str(fact.other_name),
            relation=str(fact.relation),
            relation_label=_OBJECTIVE_RELATION_LABELS[str(fact.relation)],
            source_labels=_source_tuple((fact.source_label,)),
        )
        if description_key and _normalized(fact.evidence) == description_key:
            exact.append(spec)
        if npc_entity_id is not None and int(fact.other_entity_id) == npc_entity_id:
            matching_id.append(spec)

    specs = exact or matching_id

    # A loot objective may identify the item in the match rule while the exact source
    # creature is represented by item -> NPC : drops_from. Restrict this fallback to
    # quest-derived evidence from the same source page when available so a global item
    # drop table cannot silently redefine the active quest objective.
    if not specs and rule.get("item_entity_id") is not None:
        item_id = int(rule["item_entity_id"])
        item_context = build_world_entity_context_for_id(db, item_id)
        step_page_id = (
            int(step["source_page_id"])
            if step["source_page_id"] is not None
            else None
        )
        if item_context is not None:
            item_specs: list[_TargetSpec] = []
            for fact in item_context.relationships:
                if (
                    fact.direction != "out"
                    or fact.relation != "drops_from"
                    or fact.other_kind != "npc"
                ):
                    continue
                if str(fact.data.get("derived_from") or "") != "quest_objective":
                    continue
                if step_page_id is not None and fact.source_page_id != step_page_id:
                    continue
                item_specs.append(
                    _TargetSpec(
                        entity_id=int(fact.other_entity_id),
                        entity_name=str(fact.other_name),
                        relation="objective_source_creature",
                        relation_label="loot source",
                        source_labels=_source_tuple((fact.source_label,)),
                    )
                )
            specs = item_specs

    # Last safe fallback: an explicit canonical NPC entity ID in the compiled step.
    # This does not infer a target from prose; the importer already resolved identity.
    if not specs and npc_entity_id is not None:
        entity = db.entity(npc_entity_id)
        if entity is not None and str(entity["kind"] or "") == "npc":
            relation, label = _fallback_relation_label(rule, description)
            specs = [
                _TargetSpec(
                    entity_id=npc_entity_id,
                    entity_name=str(entity["name"] or ""),
                    relation=relation,
                    relation_label=label,
                    source_labels=(),
                )
            ]

    unique: dict[tuple[int, str], _TargetSpec] = {}
    for spec in specs:
        key = (spec.entity_id, spec.relation)
        previous = unique.get(key)
        if previous is None:
            unique[key] = spec
        else:
            unique[key] = _TargetSpec(
                entity_id=spec.entity_id,
                entity_name=spec.entity_name,
                relation=spec.relation,
                relation_label=spec.relation_label,
                source_labels=_source_tuple((*previous.source_labels, *spec.source_labels)),
            )
    return tuple(unique.values())


def _step_zone_identity(db: Database, step):
    text = " ".join(str(step["zone"] or "").split()).strip()
    if not text:
        return None, ""
    resolution = resolve_authoritative_zone(db, text)
    if resolution.identity is None:
        return None, text
    return resolution.identity, str(resolution.identity.name or text)


def _location_choices(
    db: Database,
    quest_id: int,
    specs: tuple[_TargetSpec, ...],
    *,
    step_zone_entity_id: int | None,
) -> tuple[KnowledgeMapChoice, ...]:
    grouped: dict[
        tuple[int, str, str, int, str, float, float, float | None],
        tuple[list, list[str]],
    ] = {}
    for spec in specs:
        for row in location_evidence_for_entity(db, spec.entity_id):
            if not row.navigable:
                continue
            assert row.zone_entity_id is not None and row.x is not None and row.y is not None
            if (
                step_zone_entity_id is not None
                and int(row.zone_entity_id) != int(step_zone_entity_id)
            ):
                continue
            zone = db.entity(int(row.zone_entity_id))
            zone_name = str(row.zone_name or (zone["name"] if zone is not None else ""))
            key = (
                spec.entity_id,
                spec.relation,
                spec.relation_label,
                int(row.zone_entity_id),
                zone_name,
                float(row.x),
                float(row.y),
                float(row.z) if row.z is not None else None,
            )
            evidence_rows, sources = grouped.setdefault(key, ([], []))
            evidence_rows.append(row)
            sources.extend(spec.source_labels)
            sources.append(row.source_label)

    choices: list[KnowledgeMapChoice] = []
    for (
        target_id,
        relation,
        relation_label,
        zone_id,
        zone_name,
        x,
        y,
        z,
    ), (evidence_rows, sources) in grouped.items():
        target = db.entity(target_id)
        target_name = str(target["name"] or "") if target is not None else f"entity {target_id}"
        choices.append(
            KnowledgeMapChoice(
                selected_entity_id=int(quest_id),
                location_entity_id=target_id,
                location_entity_name=target_name,
                origin="quest_objective",
                relation=relation,
                relation_label=relation_label,
                zone_entity_id=zone_id,
                zone_name=zone_name,
                x=x,
                y=y,
                z=z,
                evidence_count=len(evidence_rows),
                source_labels=_source_tuple(sources),
            )
        )
    choices.sort(
        key=lambda choice: (
            choice.zone_name.casefold(),
            choice.relation_label.casefold(),
            choice.location_entity_name.casefold(),
            choice.y,
            choice.x,
            choice.z if choice.z is not None else 0.0,
        )
    )
    return tuple(choices)


def tracked_quest_objective_navigation(
    db: Database,
    quest_id: int,
    current_zone: str | None,
    *,
    step_order: int | None = None,
) -> QuestObjectiveNavigationResult:
    """Project one tracked quest objective into safe Map or Travel actionability.

    Progress ownership stays in QuestEngine. This function is a pure read projection
    over the compiled active step, explicit objective relationships, canonical location
    evidence and authoritative zone identity. It never guesses an NPC from prose and
    never turns provider candidate/unresolved coordinates into gameplay targets.
    """
    quest = db.entity(int(quest_id))
    quest_name = str(quest["name"] or "") if quest is not None else ""
    if quest is None or str(quest["kind"] or "") != "quest":
        return QuestObjectiveNavigationResult(
            "missing_quest",
            "Tracked quest no longer exists in packaged knowledge.",
            int(quest_id),
            quest_name,
            step_order,
            "",
            None,
            "",
        )

    step = _step_for_quest(db, int(quest_id), step_order)
    if step is None:
        return QuestObjectiveNavigationResult(
            "no_active_step",
            "All locally defined quest steps are complete or no active step is available.",
            int(quest_id),
            quest_name,
            step_order,
            "",
            None,
            "",
        )

    order = int(step["step_order"])
    objective = str(step["description"] or "")
    zone_text = " ".join(str(current_zone or "").split()).strip()
    if not zone_text:
        return QuestObjectiveNavigationResult(
            "no_current_zone",
            f"Current zone is unknown; {quest_name} objective navigation needs the live zone.",
            int(quest_id),
            quest_name,
            order,
            objective,
            None,
            "",
        )

    current_resolution = resolve_authoritative_zone(db, zone_text)
    if current_resolution.identity is None:
        status = (
            "current_zone_ambiguous"
            if current_resolution.status == "ambiguous"
            else "current_zone_unresolved"
        )
        reason = (
            f"Current canonical zone identity is ambiguous for {zone_text}; EverQuestie will not guess objective navigation."
            if status == "current_zone_ambiguous"
            else f"Current canonical zone identity is not known for {zone_text}."
        )
        return QuestObjectiveNavigationResult(
            status,
            reason,
            int(quest_id),
            quest_name,
            order,
            objective,
            None,
            zone_text,
        )

    current_zone_id = int(current_resolution.identity.entity_id)
    current_zone_name = str(current_resolution.identity.name or zone_text)
    step_zone_identity, step_zone_name = _step_zone_identity(db, step)
    step_zone_id = (
        int(step_zone_identity.entity_id)
        if step_zone_identity is not None
        else None
    )

    specs = _quest_objective_target_specs(db, int(quest_id), step)
    choices = _location_choices(
        db,
        int(quest_id),
        specs,
        step_zone_entity_id=step_zone_id,
    )
    current_choices = tuple(
        choice for choice in choices if int(choice.zone_entity_id) == current_zone_id
    )
    remote_choices = tuple(
        choice for choice in choices if int(choice.zone_entity_id) != current_zone_id
    )

    if current_choices:
        return QuestObjectiveNavigationResult(
            "map_ready",
            f"Active objective has {len(current_choices)} safe location choice(s) in {current_zone_name}; map the objective directly.",
            int(quest_id),
            quest_name,
            order,
            objective,
            current_zone_id,
            current_zone_name,
            current_choices,
            (),
        )

    if remote_choices:
        choice_set = KnowledgeMapChoiceSet(
            "not_in_current_zone",
            "",
            int(quest_id),
            quest_name,
            current_zone_id,
            current_zone_name,
            (),
            len(remote_choices),
            remote_choices,
        )
        routes = knowledge_route_choices(choice_set)
        return QuestObjectiveNavigationResult(
            "route_ready",
            (
                f"Active objective is outside {current_zone_name}; "
                f"{len(routes)} safe canonical destination zone choice(s) can be routed through Travel."
            ),
            int(quest_id),
            quest_name,
            order,
            objective,
            current_zone_id,
            current_zone_name,
            (),
            routes,
        )

    # Coordinates are optional for cross-zone guidance. A canonical step-zone identity
    # is enough to route the player there; Map targeting still waits for actual X/Y.
    if step_zone_id is not None and step_zone_id != current_zone_id:
        route = KnowledgeRouteChoice(
            selected_entity_id=int(quest_id),
            selected_entity_name=quest_name,
            zone_entity_id=step_zone_id,
            zone_name=step_zone_name,
            target_labels=(objective,),
            source_labels=(),
            location_choice_count=0,
            evidence_count=0,
        )
        return QuestObjectiveNavigationResult(
            "route_ready",
            (
                f"Active objective names canonical destination zone {step_zone_name}; "
                "no exact objective coordinate is known yet, but Travel can route to the zone."
            ),
            int(quest_id),
            quest_name,
            order,
            objective,
            current_zone_id,
            current_zone_name,
            (),
            (route,),
        )

    if step_zone_id == current_zone_id:
        return QuestObjectiveNavigationResult(
            "current_zone_no_coordinate",
            (
                f"Active objective is in the current zone {current_zone_name}, "
                "but no safe exact objective coordinate is known."
            ),
            int(quest_id),
            quest_name,
            order,
            objective,
            current_zone_id,
            current_zone_name,
        )

    if step_zone_name and step_zone_id is None:
        return QuestObjectiveNavigationResult(
            "step_zone_unresolved",
            (
                f"Objective zone {step_zone_name} is present in quest knowledge but has no unique canonical gameplay identity."
            ),
            int(quest_id),
            quest_name,
            order,
            objective,
            current_zone_id,
            current_zone_name,
        )

    return QuestObjectiveNavigationResult(
        "no_actionable_location",
        "No safe canonical objective location or destination zone is known for the active step.",
        int(quest_id),
        quest_name,
        order,
        objective,
        current_zone_id,
        current_zone_name,
    )
