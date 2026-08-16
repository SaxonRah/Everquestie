from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .locations import location_evidence_for_entity
from .quest_engine import Guidance, QuestEngine
from .world_profiles import (
    active_world_profile_id,
    world_profile,
    zone_profile_decision,
)
from .zone_authority import resolve_authoritative_zone


@dataclass(frozen=True, slots=True)
class ProfileZoneEvidence:
    zone_entity_id: int
    zone_name: str
    source: str
    allowed: bool
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class EntityProfileDecision:
    entity_id: int
    entity_kind: str
    entity_name: str
    profile_id: str
    compatibility: bool | None
    status: str
    reason: str
    zones: tuple[ProfileZoneEvidence, ...] = ()

    @property
    def available(self) -> bool:
        return self.compatibility is True

    @property
    def blocked(self) -> bool:
        return self.compatibility is False


_DIRECT_ZONE_RELATIONS = ("occurs_in", "starts_in", "found_in")
_ZONE_DEFINING_KINDS = {"quest", "npc"}


def _canonical_zone_id(db: Database, token: str | None) -> int | None:
    text = " ".join(str(token or "").split()).strip()
    if not text:
        return None
    resolution = resolve_authoritative_zone(db, text)
    if resolution.identity is None:
        return None
    return int(resolution.identity.entity_id)


def _zone_evidence_ids(db: Database, entity_id: int, kind: str) -> dict[int, set[str]]:
    result: dict[int, set[str]] = {}

    def add(zone_id: int | None, source: str) -> None:
        if zone_id is None:
            return
        result.setdefault(int(zone_id), set()).add(source)

    entity = db.entity(int(entity_id))
    if entity is None:
        return result

    # Entity.zone is source-normalized text, so it is actionable only when it resolves
    # through the same authoritative canonical-zone policy used elsewhere at runtime.
    add(_canonical_zone_id(db, entity["zone"]), "entity zone field")

    # Unified location evidence has already projected linked provider zones into safe
    # canonical gameplay identities and leaves ambiguous/unresolved provider zones
    # without a zone_entity_id. Do not reinterpret those weaker rows here.
    for location in location_evidence_for_entity(db, int(entity_id)):
        add(location.zone_entity_id, f"{location.evidence_type} location")

    # Only explicit normalized relationships whose semantic target is a zone are used.
    # Relationship names do not become availability facts by themselves; the target
    # still has to resolve to one authoritative gameplay zone.
    for relation in _DIRECT_ZONE_RELATIONS:
        for target in db.relationship_targets(int(entity_id), relation):
            if str(target["kind"] or "") != "zone":
                continue
            zone_id = _canonical_zone_id(db, str(target["name"] or ""))
            add(zone_id, f"{relation} relationship")

    if kind == "quest":
        # Quest-step zone strings are structured source facts, but again only exact
        # authoritative resolution can promote them into gameplay availability.
        for step in db.quest_steps(int(entity_id)):
            add(_canonical_zone_id(db, step["zone"]), "quest step zone")

    return result


def entity_profile_decision(
    db: Database,
    entity_id: int,
    profile_id: str | None = None,
) -> EntityProfileDecision:
    """Project one knowledge entity through the active gameplay profile.

    This is intentionally conservative. Zone identities use the definitive zone
    profile policy. Quests and NPCs may be marked outside-profile only when every
    directly evidenced canonical zone is blocked. Other entity kinds (items, spells,
    etc.) are not declared nonexistent merely because their currently known locations
    are outside the selected profile; their compatibility remains undetermined until
    stronger lifecycle/expansion evidence is compiled.
    """
    entity = db.entity(int(entity_id))
    profile = world_profile(profile_id or active_world_profile_id(db))
    if entity is None:
        return EntityProfileDecision(
            int(entity_id),
            "",
            f"entity {entity_id}",
            profile.profile_id,
            None,
            "missing",
            "entity is not present in local knowledge",
            (),
        )

    entity_id = int(entity["id"])
    kind = str(entity["kind"] or "")
    name = str(entity["name"] or "")

    if profile.profile_id == "unrestricted":
        return EntityProfileDecision(
            entity_id,
            kind,
            name,
            profile.profile_id,
            True,
            "available",
            "unrestricted/custom profile retains all compiled knowledge",
            (),
        )

    if kind == "zone":
        decision = zone_profile_decision(db, entity_id, profile.profile_id)
        zone = ProfileZoneEvidence(
            decision.zone_entity_id,
            decision.zone_name,
            "zone identity",
            decision.allowed,
            decision.status,
            decision.reason,
        )
        return EntityProfileDecision(
            entity_id,
            kind,
            name,
            profile.profile_id,
            bool(decision.allowed),
            "available" if decision.allowed else "blocked",
            decision.reason,
            (zone,),
        )

    sources = _zone_evidence_ids(db, entity_id, kind)
    zones: list[ProfileZoneEvidence] = []
    for zone_id in sorted(sources):
        decision = zone_profile_decision(db, zone_id, profile.profile_id)
        source_text = ", ".join(sorted(sources[zone_id], key=str.casefold))
        zones.append(
            ProfileZoneEvidence(
                zone_id,
                decision.zone_name,
                source_text,
                bool(decision.allowed),
                decision.status,
                decision.reason,
            )
        )

    if not zones:
        return EntityProfileDecision(
            entity_id,
            kind,
            name,
            profile.profile_id,
            None,
            "unknown",
            "no direct canonical zone evidence currently proves profile availability",
            (),
        )

    allowed = [zone for zone in zones if zone.allowed]
    blocked = [zone for zone in zones if not zone.allowed]

    if allowed and not blocked:
        return EntityProfileDecision(
            entity_id,
            kind,
            name,
            profile.profile_id,
            True,
            "available",
            "all directly evidenced canonical zones are available in this profile",
            tuple(zones),
        )

    if allowed and blocked:
        return EntityProfileDecision(
            entity_id,
            kind,
            name,
            profile.profile_id,
            None,
            "mixed",
            "direct world evidence spans both available and blocked zones; entity-era compatibility is not inferred",
            tuple(zones),
        )

    # All known direct canonical zones are blocked. For quests/NPCs, those world ties
    # define where the content is acted on strongly enough to mark it outside-profile.
    # For portable entity kinds such as items/spells, that would be overclaiming: the
    # corpus may simply be missing another acquisition/source path.
    if kind in _ZONE_DEFINING_KINDS:
        return EntityProfileDecision(
            entity_id,
            kind,
            name,
            profile.profile_id,
            False,
            "blocked",
            "all directly evidenced canonical zones are outside the selected gameplay profile",
            tuple(zones),
        )

    return EntityProfileDecision(
        entity_id,
        kind,
        name,
        profile.profile_id,
        None,
        "unknown",
        "known direct zone evidence is outside the profile, but that does not prove this entity kind is unavailable",
        tuple(zones),
    )


def entity_profile_lines(
    db: Database,
    entity_id: int,
    profile_id: str | None = None,
) -> list[str]:
    decision = entity_profile_decision(db, entity_id, profile_id)
    profile = world_profile(decision.profile_id)
    if decision.compatibility is True:
        state = "AVAILABLE"
    elif decision.compatibility is False:
        state = "OUTSIDE PROFILE"
    elif decision.status == "mixed":
        state = "MIXED / UNDETERMINED"
    else:
        state = "UNDETERMINED"

    lines = [
        "",
        "Gameplay profile availability:",
        f"  Profile: {profile.label}",
        f"  Status: {state}",
        f"  Reason: {decision.reason}",
    ]
    for zone in decision.zones:
        state_text = "available" if zone.allowed else "blocked"
        lines.append(
            f"  • {zone.zone_name}: {state_text} | {zone.source} | {zone.reason}"
        )
    return lines


def profiled_entity_detail_text(
    db: Database,
    entity_id: int,
    *,
    include_source_text: bool = False,
) -> str:
    """Render normal Knowledge detail plus non-destructive profile availability."""
    from .knowledge import entity_detail_text

    text = entity_detail_text(db, entity_id, include_source_text=include_source_text)
    if text == "Entity not found.":
        return text
    return text + "\n" + "\n".join(entity_profile_lines(db, entity_id))


def _step_zone_decision(db: Database, zone_text: str | None, profile_id: str):
    zone_id = _canonical_zone_id(db, zone_text)
    if zone_id is None:
        return None
    return zone_profile_decision(db, zone_id, profile_id)


class ProfileAwareQuestEngine(QuestEngine):
    """Keep quest progress intact while making guidance profile-aware."""

    def guidance(self, current_zone: str | None) -> list[Guidance]:
        base = super().guidance(current_zone)
        profile = world_profile(active_world_profile_id(self.db))
        if profile.profile_id == "unrestricted" or not base:
            return base

        tracked = list(self.db.tracked_quests())
        out: list[Guidance] = []
        for index, guide in enumerate(base):
            if index >= len(tracked):
                out.append(guide)
                continue

            quest = tracked[index]
            quest_id = int(quest["id"])
            quest_decision = entity_profile_decision(self.db, quest_id, profile.profile_id)
            steps = list(self.db.quest_steps(quest_id))
            active_step = int(quest["active_step"])
            pending = next(
                (step for step in steps if int(step["step_order"]) == active_step),
                None,
            )

            text = guide.text
            warning = ""
            if pending is not None and pending["zone"]:
                step_zone = str(pending["zone"])
                zone_decision = _step_zone_decision(self.db, step_zone, profile.profile_id)
                if zone_decision is not None and not zone_decision.allowed:
                    # The base engine emits this travel prefix from structured step-zone
                    # evidence. Remove only that exact prefix; objective/progress text
                    # remains unchanged and no tracking state is touched.
                    if current_zone:
                        prefix = f"Travel from {current_zone} to {step_zone}. "
                    else:
                        prefix = f"Destination zone: {step_zone}. "
                    if text.startswith(prefix):
                        text = text[len(prefix):]
                    warning = (
                        f"Gameplay profile: {profile.label}. {zone_decision.zone_name} is outside this profile; "
                        f"EverQuestie will keep tracking observed progress but will not recommend travel there. "
                        f"Reason: {zone_decision.reason}"
                    )

            if not warning and quest_decision.blocked:
                warning = (
                    f"Gameplay profile: {profile.label}. Known quest world evidence is outside this profile. "
                    "EverQuestie will keep tracking observed progress rather than discarding player state. "
                    f"Reason: {quest_decision.reason}"
                )

            if warning:
                text = warning + "\n" + text
            out.append(Guidance(guide.title, text, guide.source_url))

        return out
