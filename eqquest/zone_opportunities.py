from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable

from .profile_availability import entity_profile_decision
from .world_profiles import active_world_profile_id
from .zone_authority import prefer_eqclient_zone_resolution
from .zone_identity import ZoneIdentityIndex


@dataclass(frozen=True, slots=True)
class ZoneOpportunityStep:
    step_order: int
    description: str
    source_zone: str
    event_kind: str


@dataclass(frozen=True, slots=True)
class ZoneOpportunity:
    quest_id: int
    quest_name: str
    source_url: str
    zone_entity_id: int
    zone_name: str
    steps: tuple[ZoneOpportunityStep, ...]
    profile_status: str
    profile_reason: str
    activity_match: bool

    @property
    def primary_step_order(self) -> int:
        return int(self.steps[0].step_order)

    @property
    def primary_reason(self) -> str:
        count = len(self.steps)
        base = f"{count} source-backed structured objective{'s' if count != 1 else ''} in {self.zone_name}"
        if self.activity_match:
            return base + "; recent activity also matches this quest"
        return base


def _event_kind(match_json: str | None) -> str:
    try:
        value = json.loads(match_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return ""
    if not isinstance(value, dict):
        return ""
    return str(value.get("event") or "").strip().casefold()


def _resolved_step_zone_tokens(db, index: ZoneIdentityIndex, zone_entity_id: int) -> tuple[str, ...]:
    """Return provenanced quest-step zone strings resolving to one canonical zone.

    Distinct stored zone strings are resolved through the same authoritative identity
    policy used by profile availability/navigation. Ambiguous or unresolved strings are
    never admitted merely because they resemble the current display name, and unsourced
    local/synthetic steps cannot establish a player-facing zone opportunity.
    """
    rows = db.conn.execute(
        """
        SELECT zone
        FROM quest_steps
        WHERE zone IS NOT NULL AND TRIM(zone)<>''
          AND source_page_id IS NOT NULL
        GROUP BY zone COLLATE NOCASE
        ORDER BY zone COLLATE NOCASE
        """
    ).fetchall()
    accepted: list[str] = []
    for row in rows:
        text = " ".join(str(row["zone"] or "").split()).strip()
        if not text:
            continue
        resolution = prefer_eqclient_zone_resolution(index.resolve(text), text)
        if resolution.identity is None:
            continue
        if int(resolution.identity.entity_id) == int(zone_entity_id):
            accepted.append(text)
    return tuple(dict.fromkeys(accepted))


def _runtime_zone_identity_index(db) -> ZoneIdentityIndex:
    """Reuse canonical zone identity data for immutable packaged knowledge.

    Builder databases remain uncached because imports may change identities while the
    process is running. Runtime knowledge is explicitly immutable, so rebuilding the
    same zone index for every live log event only wastes CPU and blocks Tk.
    """
    if getattr(db, "knowledge_writable", True):
        return ZoneIdentityIndex(db)

    cached = getattr(db, "_zone_opportunity_identity_index", None)
    if cached is None:
        cached = ZoneIdentityIndex(db)
        setattr(db, "_zone_opportunity_identity_index", cached)
    return cached


def zone_opportunities(
    db,
    current_zone: str | None,
    *,
    activity_quest_ids: Iterable[int] = (),
    profile_id: str | None = None,
    limit: int = 15,
) -> tuple[ZoneOpportunity, ...]:
    """Project untracked quests with provenanced structured objectives here.

    This is location-triggered discovery, not activity inference. A quest enters this
    projection only because one or more source-backed compiled quest steps contain a zone
    string that resolves authoritatively to the player's current canonical zone. Recent
    activity can rank/contextualize an already-qualified quest but cannot create one.
    """
    text = " ".join(str(current_zone or "").split()).strip()
    if not text or int(limit) <= 0:
        return ()

    index = _runtime_zone_identity_index(db)
    current = prefer_eqclient_zone_resolution(index.resolve(text), text)
    if current.identity is None:
        return ()
    zone_id = int(current.identity.entity_id)
    zone_name = str(current.identity.name or text)

    token_cache = None
    if not getattr(db, "knowledge_writable", True):
        token_cache = getattr(db, "_zone_opportunity_step_tokens", None)
        if token_cache is None:
            token_cache = {}
            setattr(db, "_zone_opportunity_step_tokens", token_cache)

    if token_cache is not None and zone_id in token_cache:
        step_zone_tokens = token_cache[zone_id]
    else:
        step_zone_tokens = _resolved_step_zone_tokens(db, index, zone_id)
        if token_cache is not None:
            token_cache[zone_id] = step_zone_tokens

    if not step_zone_tokens:
        return ()

    placeholders = ",".join("?" for _ in step_zone_tokens)
    rows = db.conn.execute(
        f"""
        SELECT
            qs.quest_entity_id,
            qs.step_order,
            qs.description,
            qs.zone,
            qs.match_json,
            e.name AS quest_name,
            COALESCE(e.source_url,'') AS source_url
        FROM quest_steps qs
        JOIN entities e ON e.id=qs.quest_entity_id
        WHERE e.kind='quest'
          AND qs.source_page_id IS NOT NULL
          AND qs.zone COLLATE NOCASE IN ({placeholders})
        ORDER BY qs.quest_entity_id, qs.step_order
        """,
        list(step_zone_tokens),
    ).fetchall()

    grouped: dict[int, dict] = {}
    for row in rows:
        quest_id = int(row["quest_entity_id"])
        group = grouped.setdefault(
            quest_id,
            {
                "name": str(row["quest_name"] or ""),
                "source_url": str(row["source_url"] or ""),
                "steps": [],
            },
        )
        group["steps"].append(
            ZoneOpportunityStep(
                step_order=int(row["step_order"]),
                description=str(row["description"] or ""),
                source_zone=str(row["zone"] or ""),
                event_kind=_event_kind(row["match_json"]),
            )
        )

    tracked_ids = {int(row["id"]) for row in db.tracked_quests()}
    activity_ids = {int(value) for value in activity_quest_ids}
    selected_profile = profile_id or active_world_profile_id(db)

    opportunities: list[ZoneOpportunity] = []
    for quest_id, group in grouped.items():
        if quest_id in tracked_ids:
            continue
        decision = entity_profile_decision(db, quest_id, selected_profile)
        if decision.blocked:
            continue
        steps = tuple(group["steps"])
        if not steps:
            continue
        opportunities.append(
            ZoneOpportunity(
                quest_id=quest_id,
                quest_name=str(group["name"]),
                source_url=str(group["source_url"]),
                zone_entity_id=zone_id,
                zone_name=zone_name,
                steps=steps,
                profile_status=decision.status,
                profile_reason=decision.reason,
                activity_match=quest_id in activity_ids,
            )
        )

    opportunities.sort(
        key=lambda row: (
            0 if row.activity_match else 1,
            -len(row.steps),
            row.quest_name.casefold(),
            row.quest_id,
        )
    )
    return tuple(opportunities[: max(0, int(limit))])


def zone_opportunity_text(opportunity: ZoneOpportunity) -> str:
    lines = [
        opportunity.quest_name,
        f"Current zone: {opportunity.zone_name}",
        f"Why here: {opportunity.primary_reason}.",
        f"Gameplay profile: {opportunity.profile_status} — {opportunity.profile_reason}",
        "",
        "Source-backed structured objectives in this zone:",
    ]
    for step in opportunity.steps:
        event = f" [{step.event_kind}]" if step.event_kind else ""
        lines.append(f"  • Step {step.step_order}: {step.description}{event}")
    if opportunity.activity_match:
        lines += [
            "",
            "Recent Activity Pathways evidence also supports this quest, but that activity "
            "did not create the zone opportunity.",
        ]
    lines += [
        "",
        "Zone Opportunity means source-backed compiled structured quest data places these "
        "objectives in your current canonical zone. It does not mean the quest is currently owned.",
    ]
    return "\n".join(lines)
