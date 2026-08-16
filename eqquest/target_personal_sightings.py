from __future__ import annotations

from dataclasses import dataclass

from .personal_observations import personal_observation_summary
from .zone_authority import resolve_authoritative_zone


@dataclass(frozen=True, slots=True)
class TargetPersonalSightingAction:
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class TargetPersonalSighting:
    observed_zone_name: str
    total_count: int
    actions: tuple[TargetPersonalSightingAction, ...]
    resolution_status: str
    resolution_kind: str
    canonical_zone_entity_id: int | None
    canonical_zone_name: str
    resolution_reason: str

    @property
    def actionable(self) -> bool:
        return self.canonical_zone_entity_id is not None

    @property
    def action_summary(self) -> str:
        return ", ".join(f"{row.label} x{row.count}" for row in self.actions)

    @property
    def identity_label(self) -> str:
        if self.actionable:
            if self.observed_zone_name.casefold() == self.canonical_zone_name.casefold():
                return f"canonical zone: {self.canonical_zone_name}"
            return f"{self.observed_zone_name} -> {self.canonical_zone_name}"
        if self.resolution_status == "ambiguous":
            return f"ambiguous zone: {self.observed_zone_name}"
        return f"unresolved zone: {self.observed_zone_name}"


def target_personal_sightings(
    db,
    npc_entity_id: int,
    *,
    limit: int = 12,
) -> tuple[TargetPersonalSighting, ...]:
    """Project explicit personal NPC observations into conservatively resolved zones.

    Geography comes only from the player's observation history, which in turn groups an
    NPC action under the most recent explicit logged zone entry and hard-resets context
    at `Welcome to EverQuest!`. The zone token is then resolved through EverQuestie's
    authoritative canonical zone policy.

    A resolved sighting can be used as a *personal-history destination*. It is never
    converted into a canonical NPC spawn/location row and contains no implied /loc.
    Ambiguous or unresolved zone tokens remain visible but non-actionable.
    """
    npc = db.entity(int(npc_entity_id))
    if npc is None or str(npc["kind"] or "") != "npc":
        return ()

    summary = personal_observation_summary(db, int(npc_entity_id))
    if summary is None or not summary.zone_context:
        return ()

    sightings: list[TargetPersonalSighting] = []
    for zone in summary.zone_context:
        observed_name = " ".join(str(zone.zone or "").split()).strip()
        if not observed_name:
            continue
        resolution = resolve_authoritative_zone(db, observed_name)
        zone_id: int | None = None
        canonical_name = ""
        if resolution.identity is not None:
            zone_id = int(resolution.identity.entity_id)
            canonical_name = str(resolution.identity.name)

        actions = tuple(
            TargetPersonalSightingAction(
                label=str(row.label),
                count=int(row.count),
            )
            for row in zone.counts
            if int(row.count) > 0
        )
        sightings.append(
            TargetPersonalSighting(
                observed_zone_name=observed_name,
                total_count=int(zone.total),
                actions=actions,
                resolution_status=str(resolution.status or "missing"),
                resolution_kind=str(resolution.match_kind or ""),
                canonical_zone_entity_id=zone_id,
                canonical_zone_name=canonical_name,
                resolution_reason=str(resolution.reason or ""),
            )
        )

    sightings.sort(
        key=lambda row: (
            0 if row.actionable else 1,
            -row.total_count,
            row.observed_zone_name.casefold(),
        )
    )
    return tuple(sightings[: max(0, int(limit))])


def target_personal_sighting_text(target_name: str, row: TargetPersonalSighting) -> str:
    lines = [
        f"Personal sighting history — {target_name}",
        f"Logged zone context: {row.observed_zone_name}",
        f"Observed actions: {row.action_summary or 'none'}",
        f"Total zone-context observations: {row.total_count:,}",
        f"Zone identity: {row.identity_label}",
    ]
    if row.resolution_reason:
        lines.append(f"Identity reason: {row.resolution_reason}")
    if row.actionable:
        lines += [
            "",
            "This canonical zone can be handed to Travel as a destination because the "
            "logged zone token resolved conservatively. The destination is still labeled "
            "personal history: it is not being written into canonical NPC spawn knowledge.",
        ]
    else:
        lines += [
            "",
            "This personal observation remains visible, but EverQuestie will not route to "
            "an ambiguous or unresolved zone token.",
        ]
    lines += [
        "",
        "Zone context comes from explicit logged zone-entry boundaries. A Welcome event "
        "resets geography, and no exact NPC /loc is inferred from being observed somewhere "
        "in the zone.",
    ]
    return "\n".join(lines)
