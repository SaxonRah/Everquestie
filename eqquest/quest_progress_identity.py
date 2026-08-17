from __future__ import annotations

from dataclasses import dataclass

from .db import normalize_name


_QUEST_PROGRESS_IDENTITY_MARKER = "_everquestie_quest_progress_identity_policy"


@dataclass(frozen=True, slots=True)
class ExactEntityCandidates:
    kind: str
    observed_name: str
    match_kind: str
    entity_ids: tuple[int, ...]

    @property
    def unique_entity_id(self) -> int | None:
        return self.entity_ids[0] if len(self.entity_ids) == 1 else None


def exact_entity_name_candidates(db, kind: str, observed_name: str | None) -> ExactEntityCandidates:
    """Resolve only exact canonical-name or exact-alias candidates.

    Canonical exact names have precedence over aliases, matching Target Intelligence's
    fail-closed identity semantics. This function intentionally never falls through to
    substring/FTS/unique-search heuristics: log text must itself prove the displayed name.
    """
    observed = " ".join(str(observed_name or "").split()).strip()
    norm = normalize_name(observed)
    if not norm:
        return ExactEntityCandidates(str(kind), observed, "missing", ())

    exact = db.conn.execute(
        """
        SELECT id
        FROM entities
        WHERE kind=? AND normalized_name=?
        ORDER BY id
        """,
        (str(kind), norm),
    ).fetchall()
    if exact:
        return ExactEntityCandidates(
            str(kind),
            observed,
            "exact",
            tuple(int(row["id"]) for row in exact),
        )

    aliases = db.conn.execute(
        """
        SELECT DISTINCT e.id
        FROM entity_aliases a
        JOIN entities e ON e.id=a.entity_id
        WHERE e.kind=? AND a.normalized_alias=?
        ORDER BY e.id
        """,
        (str(kind), norm),
    ).fetchall()
    if aliases:
        return ExactEntityCandidates(
            str(kind),
            observed,
            "alias",
            tuple(int(row["id"]) for row in aliases),
        )
    return ExactEntityCandidates(str(kind), observed, "missing", ())


def known_entity_zone_names(db, entity_id: int) -> tuple[str, ...]:
    """Return provenanced geography for one entity without inferring missing zones."""
    names: dict[str, str] = {}
    row = db.conn.execute(
        "SELECT zone,source_page_id FROM entities WHERE id=?",
        (int(entity_id),),
    ).fetchone()
    if row is not None and row["source_page_id"] is not None:
        zone = " ".join(str(row["zone"] or "").split()).strip()
        if zone:
            names.setdefault(normalize_name(zone), zone)

    locations = db.conn.execute(
        """
        SELECT DISTINCT z.name AS zone_name
        FROM entity_locations l
        JOIN entities z ON z.id=l.zone_entity_id
        WHERE l.entity_id=?
          AND z.kind='zone'
          AND l.source_page_id IS NOT NULL
        ORDER BY z.name
        """,
        (int(entity_id),),
    ).fetchall()
    for location in locations:
        zone = " ".join(str(location["zone_name"] or "").split()).strip()
        if zone:
            names.setdefault(normalize_name(zone), zone)
    return tuple(names[key] for key in sorted(names))


def unique_npc_candidate_in_zone(
    engine,
    candidate_ids: tuple[int, ...],
    zone: str | None,
) -> int | None:
    """Resolve duplicate NPC text only through complete provenanced geography.

    Every competing identity must have source-backed geography. Missing geography is
    unresolved evidence, never evidence that a candidate cannot occur in the observed
    zone. Exactly one candidate must be known in the requested zone.
    """
    observed = engine._clean_zone(zone)
    if not observed or len(candidate_ids) < 2:
        return None

    matching: list[int] = []
    for candidate_id in candidate_ids:
        zones = known_entity_zone_names(engine.db, candidate_id)
        if not zones:
            return None
        if any(engine._zones_match(candidate_zone, observed) for candidate_zone in zones):
            matching.append(int(candidate_id))

    return matching[0] if len(matching) == 1 else None


def _event_npc_name(event) -> str | None:
    kind = str(event.kind or "").casefold()
    if kind == "kill":
        return event.actor
    if kind == "consider":
        return event.target
    return event.actor or event.target


def _unique_npc_for_objective_zone(
    engine,
    candidate_ids: tuple[int, ...],
    target_entity_id: int,
    objective_zone: str | None,
    observed_zone: str | None,
) -> bool:
    """Use geography only when it actually eliminates every competing NPC identity."""
    objective = engine._clean_zone(objective_zone)
    observed = engine._clean_zone(observed_zone)
    if not objective or not observed or not engine._zones_match(observed, objective):
        return False
    return unique_npc_candidate_in_zone(engine, candidate_ids, objective) == int(target_entity_id)


def _entity_bound_step_is_identified(engine, step, rule: dict, event, current_zone: str | None) -> bool:
    if "item_entity_id" in rule:
        candidates = exact_entity_name_candidates(engine.db, "item", event.item)
        return (
            candidates.unique_entity_id is not None
            and int(candidates.unique_entity_id) == int(rule["item_entity_id"])
        )

    if "npc_entity_id" in rule:
        observed_name = _event_npc_name(event)
        candidates = exact_entity_name_candidates(engine.db, "npc", observed_name)
        target_id = int(rule["npc_entity_id"])
        if candidates.unique_entity_id is not None:
            return int(candidates.unique_entity_id) == target_id
        if len(candidates.entity_ids) < 2 or target_id not in candidates.entity_ids:
            return False

        objective_zone = step["zone"]
        observed_zone = getattr(event, "zone", None) or current_zone
        return _unique_npc_for_objective_zone(
            engine,
            candidates.entity_ids,
            target_id,
            objective_zone,
            observed_zone,
        )

    if "quest_entity_id" in rule:
        candidates = exact_entity_name_candidates(engine.db, "quest", event.text)
        return (
            candidates.unique_entity_id is not None
            and int(candidates.unique_entity_id) == int(rule["quest_entity_id"])
        )

    return True


def hail_target_text(text: str | None) -> str | None:
    """Return the target from the explicit EQ player-say form ``Hail, Name`` only."""
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned.casefold().startswith("hail,"):
        return None
    target = cleaned.split(",", 1)[1].strip()
    return target or None


def _strict_reconcile_boundary(engine, quest_id: int, events: list):
    """Find a replay boundary without letting ambiguous names reset player progress."""
    quest_id = int(quest_id)
    zone_contexts = engine._zone_contexts(events)

    # A modern task-assignment line is the strongest boundary, but only when its logged
    # name uniquely identifies the tracked quest. If a later assignment could refer to
    # this quest *or* a same-name sibling, do not search behind that ambiguity for an
    # older assignment. A safe starter hail after the ambiguous assignment may still
    # establish a lower-confidence boundary.
    ambiguous_assignment_floor = -1
    for i in range(len(events) - 1, -1, -1):
        event = events[i]
        if str(event.kind or "").casefold() != "task_assigned" or not event.text:
            continue
        candidates = exact_entity_name_candidates(engine.db, "quest", event.text)
        if candidates.unique_entity_id == quest_id:
            return i, "task assignment", "high"
        if quest_id in candidates.entity_ids and len(candidates.entity_ids) > 1:
            ambiguous_assignment_floor = i
            break

    starters = set(engine._quest_starter_ids(quest_id))
    if not starters:
        return None, "none", "none"

    for i in range(len(events) - 1, ambiguous_assignment_floor, -1):
        event = events[i]
        if str(event.kind or "").casefold() != "say":
            continue
        hail_target = hail_target_text(event.text)
        if not hail_target:
            continue

        candidates = exact_entity_name_candidates(engine.db, "npc", hail_target)
        resolved: int | None = None
        if candidates.unique_entity_id is not None:
            resolved = int(candidates.unique_entity_id)
        elif len(candidates.entity_ids) > 1:
            resolved = unique_npc_candidate_in_zone(
                engine,
                candidates.entity_ids,
                zone_contexts[i],
            )
        if resolved is None or resolved not in starters:
            continue

        if any(
            engine._event_matches_any_count_objective(
                quest_id,
                events[later_index],
                current_zone=zone_contexts[later_index],
            )
            for later_index in range(i + 1, len(events))
        ):
            return i, "starter NPC hail", "medium"

    return None, "none", "none"


def install_quest_progress_identity_policy() -> None:
    """Make quest progress and replay boundaries fail closed on name ambiguity.

    `name_matches_entity()` remains useful elsewhere as a permissive "could be this
    entity" check. Player-state mutation has a stronger contract: log text must uniquely
    establish a canonical identity, or complete provenanced NPC geography must eliminate
    every competing same-name identity. Reconciliation uses the same identity policy
    before it is allowed to reset and replay progress.
    """
    from .quest_engine import QuestEngine

    if getattr(QuestEngine, _QUEST_PROGRESS_IDENTITY_MARKER, False):
        return

    current_step_match = QuestEngine._step_match

    def _step_match(self, step, rule, event, *, current_zone=None):
        if not _entity_bound_step_is_identified(
            self,
            step,
            rule,
            event,
            current_zone,
        ):
            return False, 0
        return current_step_match(
            self,
            step,
            rule,
            event,
            current_zone=current_zone,
        )

    def _find_reconcile_boundary(self, quest_id, events):
        return _strict_reconcile_boundary(self, int(quest_id), list(events))

    QuestEngine._step_match = _step_match
    QuestEngine._find_reconcile_boundary = _find_reconcile_boundary
    setattr(QuestEngine, _QUEST_PROGRESS_IDENTITY_MARKER, True)
