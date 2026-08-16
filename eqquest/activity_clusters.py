from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .db import normalize_name


@dataclass(frozen=True, slots=True)
class ActivityClusterCount:
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class ActivityClusterSummary:
    session_after_event_id: int
    segment_after_event_id: int
    zone: str
    relevant_events: int
    mobs_observed_slain: int
    items_looted: int
    top_mobs: tuple[ActivityClusterCount, ...]
    top_items: tuple[ActivityClusterCount, ...]

    @property
    def active(self) -> bool:
        """Whether the current-zone log pattern is strong enough to surface.

        A cluster needs at least three relevant observations and either a repeated
        subject or five total relevant observations. This keeps one-off kills/loot
        from turning the Live tab into notification noise.
        """
        repeated = any(row.count >= 2 for row in (*self.top_mobs, *self.top_items))
        return self.relevant_events >= 3 and (repeated or self.relevant_events >= 5)


def _add(counter: Counter[str], labels: dict[str, str], value: str | None) -> None:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return
    key = normalize_name(text)
    if not key:
        return
    counter[key] += 1
    labels.setdefault(key, text)


def _top(
    counter: Counter[str], labels: dict[str, str], limit: int
) -> tuple[ActivityClusterCount, ...]:
    return tuple(
        ActivityClusterCount(labels.get(key, key), int(count))
        for key, count in sorted(
            counter.items(),
            key=lambda pair: (-int(pair[1]), labels.get(pair[0], pair[0]).casefold()),
        )[: max(0, int(limit))]
    )


def activity_cluster_summary(
    db,
    after_event_id: int,
    *,
    current_zone: str | None = None,
    top_limit: int = 3,
) -> ActivityClusterSummary:
    """Summarize repeated kill/loot activity in the player's current zone segment.

    The monitoring-session boundary comes from Activity Pathways. If the log contains
    a zone transition after that boundary, only kill/loot rows after the *latest* zone
    transition participate. This prevents an old camp/activity pattern from following
    the player into the next zone.

    Generic kill rows remain observations of a mob being slain; they are never labeled
    as guaranteed personal kills here.
    """
    boundary = max(0, int(after_event_id))
    zone = " ".join(str(current_zone or "").split()).strip()
    segment_after = boundary

    latest_zone = db.conn.execute(
        """
        SELECT id, zone
        FROM observed_events
        WHERE id>? AND kind='zone'
        ORDER BY id DESC
        LIMIT 1
        """,
        (boundary,),
    ).fetchone()
    if latest_zone is not None:
        segment_after = int(latest_zone["id"])
        if not zone:
            zone = " ".join(str(latest_zone["zone"] or "").split()).strip()

    rows = db.conn.execute(
        """
        SELECT kind, actor, item
        FROM observed_events
        WHERE id>? AND kind IN ('kill','loot')
        ORDER BY id
        """,
        (segment_after,),
    ).fetchall()

    mob_counts: Counter[str] = Counter()
    mob_labels: dict[str, str] = {}
    item_counts: Counter[str] = Counter()
    item_labels: dict[str, str] = {}
    for row in rows:
        kind = str(row["kind"] or "").casefold()
        if kind == "kill":
            _add(mob_counts, mob_labels, row["actor"])
        elif kind == "loot":
            _add(item_counts, item_labels, row["item"])

    return ActivityClusterSummary(
        session_after_event_id=boundary,
        segment_after_event_id=segment_after,
        zone=zone,
        relevant_events=sum(mob_counts.values()) + sum(item_counts.values()),
        mobs_observed_slain=sum(mob_counts.values()),
        items_looted=sum(item_counts.values()),
        top_mobs=_top(mob_counts, mob_labels, top_limit),
        top_items=_top(item_counts, item_labels, top_limit),
    )


def related_pathway_names(
    summary: ActivityClusterSummary,
    suggestions: Iterable,
    *,
    limit: int = 3,
) -> tuple[str, ...]:
    """Return suggested quest names whose evidence overlaps this activity cluster."""
    mob_keys = {normalize_name(row.label) for row in summary.top_mobs}
    item_keys = {normalize_name(row.label) for row in summary.top_items}
    names: list[str] = []
    seen: set[int] = set()
    for suggestion in suggestions:
        quest_id = int(getattr(suggestion, "quest_id", 0) or 0)
        if quest_id in seen:
            continue
        matched = False
        for evidence in getattr(suggestion, "evidence", ()):
            kind = str(getattr(evidence, "event_kind", "") or "").casefold()
            subject = normalize_name(str(getattr(evidence, "subject", "") or ""))
            if kind == "kill" and subject in mob_keys:
                matched = True
                break
            if kind == "loot" and subject in item_keys:
                matched = True
                break
        if not matched:
            continue
        seen.add(quest_id)
        name = " ".join(str(getattr(suggestion, "quest_name", "") or "").split()).strip()
        if name:
            names.append(name)
        if len(names) >= max(0, int(limit)):
            break
    return tuple(names)


def activity_cluster_text(
    summary: ActivityClusterSummary,
    *,
    pathway_names: Iterable[str] = (),
) -> str:
    if not summary.active:
        return ""

    parts: list[str] = []
    if summary.top_mobs:
        mobs = ", ".join(f"{row.label} ×{row.count:,}" for row in summary.top_mobs)
        parts.append(f"observed slain: {mobs}")
    if summary.top_items:
        items = ", ".join(f"{row.label} ×{row.count:,}" for row in summary.top_items)
        parts.append(f"you looted: {items}")

    prefix = f"{summary.zone} — " if summary.zone else ""
    line = prefix + "; ".join(parts)
    pathways = [" ".join(str(name).split()).strip() for name in pathway_names]
    pathways = [name for name in pathways if name]
    if pathways:
        line += ". Related pathways: " + ", ".join(pathways)
    line += "."
    return (
        line
        + " Log pattern only; generic kill lines mean observed slain, not guaranteed personal kills."
    )
