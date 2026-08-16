from __future__ import annotations

from dataclasses import dataclass

from .db import normalize_name
from .personal_observations import personal_observation_summary
from .profile_availability import entity_profile_decision
from .world_entity_detail import build_world_entity_context_for_id
from .world_profiles import active_world_profile_id


_TARGET_BOUNDARY_KINDS = ("target_npc", "target_player", "consider", "zone", "welcome")


@dataclass(frozen=True, slots=True)
class TargetRelationshipSummary:
    label: str
    other_kind: str
    count: int
    examples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetIntelligence:
    status: str
    observed_name: str
    observed_event_kind: str
    event_id: int
    entity_id: int | None
    canonical_name: str
    resolution_kind: str
    level_min: int | None
    level_max: int | None
    profile_status: str
    profile_reason: str
    relationships: tuple[TargetRelationshipSummary, ...]
    known_zones: tuple[str, ...]
    personal_observed_slain: int
    personal_targeted: int

    @property
    def resolved(self) -> bool:
        return self.entity_id is not None and self.status == "resolved"


def _latest_target_boundary(db, after_event_id: int):
    placeholders = ",".join("?" for _ in _TARGET_BOUNDARY_KINDS)
    return db.conn.execute(
        f"""
        SELECT id,kind,target
        FROM observed_events
        WHERE id>? AND kind IN ({placeholders})
        ORDER BY id DESC
        LIMIT 1
        """,
        [max(0, int(after_event_id)), *_TARGET_BOUNDARY_KINDS],
    ).fetchone()


def _resolve_exact_npc(db, observed_name: str):
    norm = normalize_name(observed_name)
    if not norm:
        return None, "missing"

    exact = db.conn.execute(
        """
        SELECT * FROM entities
        WHERE kind='npc' AND normalized_name=?
        ORDER BY id
        LIMIT 3
        """,
        (norm,),
    ).fetchall()
    if len(exact) == 1:
        return exact[0], "exact"
    if len(exact) > 1:
        return None, "ambiguous"

    aliases = db.conn.execute(
        """
        SELECT DISTINCT e.*
        FROM entity_aliases a
        JOIN entities e ON e.id=a.entity_id
        WHERE e.kind='npc' AND a.normalized_alias=?
        ORDER BY e.id
        LIMIT 3
        """,
        (norm,),
    ).fetchall()
    if len(aliases) == 1:
        return aliases[0], "alias"
    if len(aliases) > 1:
        return None, "ambiguous"
    return None, "missing"


def _relationship_summaries(context, *, limit: int = 6) -> tuple[TargetRelationshipSummary, ...]:
    # One relationship can legitimately have multiple source/evidence rows. The live
    # count means distinct related canonical entities, not number of provenance records.
    groups: dict[tuple[str, str], dict[int, str]] = {}
    for fact in context.relationships:
        # Only source-backed relationships qualify for the compact live strip. Full
        # Knowledge remains the place to inspect all relationships and provenance.
        if fact.source_page_id is None:
            continue
        key = (fact.label, fact.other_kind)
        related = groups.setdefault(key, {})
        name = " ".join(str(fact.display_other_name or fact.other_name or "").split()).strip()
        related.setdefault(int(fact.display_other_entity_id), name)

    rows: list[TargetRelationshipSummary] = []
    for (label, other_kind), related in groups.items():
        examples = tuple(
            name
            for _entity_id, name in sorted(
                related.items(),
                key=lambda pair: (pair[1].casefold(), int(pair[0])),
            )
            if name
        )[:3]
        rows.append(
            TargetRelationshipSummary(
                label=label,
                other_kind=other_kind,
                count=len(related),
                examples=examples,
            )
        )
    rows.sort(
        key=lambda row: (
            0 if row.other_kind == "quest" else 1 if row.other_kind == "item" else 2,
            row.label.casefold(),
            row.other_kind.casefold(),
        )
    )
    return tuple(rows[: max(0, int(limit))])


def _known_zones(context, *, limit: int = 4) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for location in context.locations:
        # Candidate/unresolved provider geography is evidence, but it must not be
        # presented as a compact gameplay location. Require canonical/linked projection.
        if location.gameplay_zone_entity_id is None:
            continue
        zone = " ".join(str(location.gameplay_zone_name or "").split()).strip()
        key = normalize_name(zone)
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(zone)
        if len(names) >= max(0, int(limit)):
            break
    return tuple(names)


def _personal_count(summary, label: str) -> int:
    if summary is None:
        return 0
    for row in summary.counts:
        if row.label == label:
            return int(row.count)
    return 0


def current_target_intelligence(
    db,
    *,
    after_event_id: int = 0,
    profile_id: str | None = None,
) -> TargetIntelligence:
    """Project exact knowledge for the latest still-current NPC target observation.

    The newest target/zone/session boundary wins. `target_player`, `zone`, and `welcome`
    intentionally clear an older NPC target. `consider` and `target_npc` can establish an
    NPC target because both log lines name the exact observed NPC text.
    """
    boundary = _latest_target_boundary(db, after_event_id)
    if boundary is None:
        return TargetIntelligence(
            "none", "", "", 0, None, "", "", None, None, "", "", (), (), 0, 0
        )

    kind = str(boundary["kind"] or "").casefold()
    event_id = int(boundary["id"])
    if kind not in {"target_npc", "consider"}:
        return TargetIntelligence(
            "cleared", "", kind, event_id, None, "", "", None, None, "", "", (), (), 0, 0
        )

    observed = " ".join(str(boundary["target"] or "").split()).strip()
    entity, resolution = _resolve_exact_npc(db, observed)
    if entity is None:
        return TargetIntelligence(
            resolution,
            observed,
            kind,
            event_id,
            None,
            "",
            resolution,
            None,
            None,
            "",
            "",
            (),
            (),
            0,
            0,
        )

    entity_id = int(entity["id"])
    context = build_world_entity_context_for_id(db, entity_id)
    selected_profile = profile_id or active_world_profile_id(db)
    decision = entity_profile_decision(db, entity_id, selected_profile)
    personal = personal_observation_summary(db, entity_id)
    return TargetIntelligence(
        status="resolved",
        observed_name=observed,
        observed_event_kind=kind,
        event_id=event_id,
        entity_id=entity_id,
        canonical_name=str(entity["name"] or observed),
        resolution_kind=resolution,
        level_min=(int(entity["level_min"]) if entity["level_min"] is not None else None),
        level_max=(int(entity["level_max"]) if entity["level_max"] is not None else None),
        profile_status=decision.status,
        profile_reason=decision.reason,
        relationships=_relationship_summaries(context) if context is not None else (),
        known_zones=_known_zones(context) if context is not None else (),
        personal_observed_slain=_personal_count(personal, "Observed slain"),
        personal_targeted=_personal_count(personal, "Targeted"),
    )


def target_intelligence_compact_text(value: TargetIntelligence) -> str:
    if value.status == "none":
        return "Target or consider an NPC to see exact source-backed relevance here."
    if value.status == "cleared":
        return "No current NPC target in the log context. Target or consider an NPC to inspect it."
    if value.status == "ambiguous":
        return (
            f"Observed NPC target: {value.observed_name}. Multiple canonical NPCs share that exact "
            "name/alias, so EverQuestie will not choose one."
        )
    if value.status == "missing":
        return (
            f"Observed NPC target: {value.observed_name}. No exact canonical NPC identity is in the "
            "current shipped knowledge snapshot yet."
        )
    if not value.resolved:
        return "No exact NPC target intelligence is available."

    parts = [f"Target: {value.canonical_name}"]
    if value.level_min is not None or value.level_max is not None:
        if value.level_min == value.level_max and value.level_min is not None:
            parts.append(f"known level {value.level_min}")
        else:
            low = "?" if value.level_min is None else str(value.level_min)
            high = "?" if value.level_max is None else str(value.level_max)
            parts.append(f"known levels {low}–{high}")

    for row in value.relationships[:3]:
        examples = f" ({', '.join(row.examples)})" if row.examples else ""
        parts.append(f"{row.label}: {row.count}{examples}")
    if value.known_zones:
        parts.append("known location: " + ", ".join(value.known_zones))
    if value.personal_observed_slain or value.personal_targeted:
        history: list[str] = []
        if value.personal_observed_slain:
            history.append(f"observed slain ×{value.personal_observed_slain:,}")
        if value.personal_targeted:
            history.append(f"targeted ×{value.personal_targeted:,}")
        parts.append("your log: " + ", ".join(history))
    if value.profile_status not in {"", "available"}:
        parts.append(f"profile {value.profile_status}")
    return " | ".join(parts)


def target_intelligence_detail_text(value: TargetIntelligence) -> str:
    compact = target_intelligence_compact_text(value)
    if not value.resolved:
        return compact

    lines = [
        value.canonical_name,
        f"Observed from log: {value.observed_event_kind} — {value.observed_name}",
        f"Identity: exact canonical NPC via {value.resolution_kind}",
        f"Gameplay profile: {value.profile_status} — {value.profile_reason}",
    ]
    if value.relationships:
        lines += ["", "Source-backed relevance:"]
        for row in value.relationships:
            examples = f" — {', '.join(row.examples)}" if row.examples else ""
            lines.append(f"  • {row.label} [{row.other_kind}]: {row.count}{examples}")
    if value.known_zones:
        lines += ["", "Known canonical/location evidence:"]
        lines.extend(f"  • {zone}" for zone in value.known_zones)
    if value.personal_observed_slain or value.personal_targeted:
        lines += ["", "Your log history:"]
        if value.personal_observed_slain:
            lines.append(f"  • Observed slain: {value.personal_observed_slain:,}")
        if value.personal_targeted:
            lines.append(f"  • Targeted: {value.personal_targeted:,}")
    lines += [
        "",
        "Target Intelligence uses only exact NPC identity and source-backed normalized relationships. "
        "It does not infer rarity, named status, drop rates, or quest importance.",
    ]
    return "\n".join(lines)
