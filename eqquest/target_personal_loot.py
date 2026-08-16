from __future__ import annotations

from dataclasses import dataclass

from .personal_observations import personal_observation_summary
from .world_entity_context import build_world_entity_context


@dataclass(frozen=True, slots=True)
class TargetPersonalLoot:
    observed_item_name: str
    observed_count: int
    resolution_status: str
    item_id: int | None
    canonical_item_name: str
    reviewed_drop_known: bool

    @property
    def resolved(self) -> bool:
        return self.item_id is not None

    @property
    def identity_label(self) -> str:
        if self.resolved:
            if self.resolution_status == "alias":
                return f"exact alias -> {self.canonical_item_name}"
            return f"exact item -> {self.canonical_item_name}"
        if self.resolution_status == "ambiguous":
            return "ambiguous canonical item"
        return "unresolved canonical item"

    @property
    def evidence_label(self) -> str:
        if self.reviewed_drop_known:
            return "personal observation + reviewed drop graph"
        return "personal observation only"


def _reviewed_drop_known(db, item_id: int, npc_entity_id: int) -> bool:
    row = db.conn.execute(
        """
        SELECT 1
        FROM entity_relationships
        WHERE source_entity_id=?
          AND target_entity_id=?
          AND relation='drops_from'
          AND source_page_id IS NOT NULL
        LIMIT 1
        """,
        (int(item_id), int(npc_entity_id)),
    ).fetchone()
    return row is not None


def target_personal_loot(
    db,
    npc_entity_id: int,
    *,
    limit: int = 20,
) -> tuple[TargetPersonalLoot, ...]:
    """Return explicit corpse-loot history for one exact canonical NPC target.

    Player history and canonical knowledge stay deliberately separate:

    * the NPC is supplied by exact Target Intelligence identity;
    * only loot events whose log line explicitly named this NPC/corpse as ``actor`` are
      accepted, via ``personal_observation_summary``;
    * each observed item string is resolved conservatively by exact canonical name or
      exact unique alias; ambiguous/missing observations stay visible but non-actionable;
    * an independently reviewed canonical ``item -> NPC : drops_from`` edge is reported
      as corroboration, never inferred from the player's observation.

    Personal observations are not filtered out by gameplay profile: they record what the
    player's own log said happened. Profile availability remains canonical knowledge and
    is intentionally not allowed to erase local history.
    """
    npc = db.entity(int(npc_entity_id))
    if npc is None or str(npc["kind"] or "") != "npc":
        return ()

    summary = personal_observation_summary(db, int(npc_entity_id))
    if summary is None or not summary.direct_loot:
        return ()

    result: list[TargetPersonalLoot] = []
    for observed in summary.direct_loot:
        raw_name = " ".join(str(observed.label or "").split()).strip()
        if not raw_name:
            continue

        context, status = build_world_entity_context(db, raw_name, "item")
        item_id: int | None = None
        canonical_name = ""
        reviewed = False
        if context is not None:
            item_id = int(context.entity_id)
            canonical_name = str(context.name)
            reviewed = _reviewed_drop_known(db, item_id, int(npc_entity_id))

        result.append(
            TargetPersonalLoot(
                observed_item_name=raw_name,
                observed_count=int(observed.count),
                resolution_status=str(status or "missing"),
                item_id=item_id,
                canonical_item_name=canonical_name,
                reviewed_drop_known=reviewed,
            )
        )

    result.sort(
        key=lambda row: (
            0 if row.reviewed_drop_known else 1,
            0 if row.resolved else 1,
            -row.observed_count,
            row.observed_item_name.casefold(),
        )
    )
    return tuple(result[: max(0, int(limit))])


def target_personal_loot_text(target_name: str, row: TargetPersonalLoot) -> str:
    lines = [
        row.observed_item_name,
        f"Your log explicitly recorded this item from {target_name}'s corpse/source: "
        f"{row.observed_count:,} time(s).",
        f"Canonical item resolution: {row.identity_label}",
        f"Evidence boundary: {row.evidence_label}",
    ]
    if row.reviewed_drop_known:
        lines.append(
            "The current knowledge snapshot independently contains reviewed source-backed "
            "item -> NPC drop evidence for the same exact canonical item and NPC."
        )
    else:
        lines.append(
            "No reviewed canonical drop edge is being claimed here. The observation stays "
            "useful as your personal history without being promoted into the global loot graph."
        )
    lines += [
        "",
        "This is explicit personal log history, not a calculated drop rate, rarity estimate, "
        "guaranteed drop, or complete loot-table claim. Generic loot lines that did not name "
        "this corpse/source are excluded.",
    ]
    return "\n".join(lines)
