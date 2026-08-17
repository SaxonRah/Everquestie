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
    """Return source-known geography for one entity without inferring missing zones."""
    names: dict[str, str] = {}
    row = db.conn.execute(
        "SELECT zone FROM entities WHERE id=?",
        (int(entity_id),),
    ).fetchone()
    if row is not None:
        zone = " ".join(str(row["zone"] or "").split()).strip()
        if zone:
            names.setdefault(normalize_name(zone), zone)

    locations = db.conn.execute(
        """
        SELECT DISTINCT z.name AS zone_name
        FROM entity_locations l
        JOIN entities z ON z.id=l.zone_entity_id
        WHERE l.entity_id=? AND z.kind='zone'
        ORDER BY z.name
        """,
        (int(entity_id),),
    ).fetchall()
    for location in locations:
        zone = " ".join(str(location["zone_name"] or "").split()).strip()
        if zone:
            names.setdefault(normalize_name(zone), zone)
    return tuple(names[key] for key in sorted(names))


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

    matching: list[int] = []
    for candidate_id in candidate_ids:
        zones = known_entity_zone_names(engine.db, candidate_id)
        # Unknown geography is unresolved evidence, not evidence that this identity
        # cannot occur in the objective zone.
        if not zones:
            return False
        if any(engine._zones_match(zone, objective) for zone in zones):
            matching.append(int(candidate_id))

    return len(matching) == 1 and matching[0] == int(target_entity_id)


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

    return True


def install_quest_progress_identity_policy() -> None:
    """Make canonical entity-bound quest progress fail closed on name ambiguity.

    `name_matches_entity()` remains useful elsewhere as a permissive "could be this
    entity" check. Quest progress has a stronger mutation contract: the log text must
    uniquely establish the bound canonical identity, or source-known NPC geography must
    eliminate every competing same-name identity.
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

    QuestEngine._step_match = _step_match
    setattr(QuestEngine, _QUEST_PROGRESS_IDENTITY_MARKER, True)
