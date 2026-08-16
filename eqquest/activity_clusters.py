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
class ActivityFactionSignal:
    label: str
    better: int
    worse: int

    @property
    def total(self) -> int:
        return int(self.better) + int(self.worse)


@dataclass(frozen=True, slots=True)
class ActivityClusterSummary:
    session_after_event_id: int
    segment_after_event_id: int
    zone: str
    relevant_events: int
    mobs_observed_slain: int
    items_looted: int
    faction_messages: int
    top_mobs: tuple[ActivityClusterCount, ...]
    top_items: tuple[ActivityClusterCount, ...]
    top_factions: tuple[ActivityFactionSignal, ...]

    @property
    def active(self) -> bool:
        """Whether the current-zone log pattern is strong enough to surface.

        A cluster needs at least three kill/loot observations and either a repeated
        subject or five total kill/loot observations. Faction messages provide context
        only; they never make an otherwise quiet activity pattern active by themselves.
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


def _top_factions(
    better: Counter[str],
    worse: Counter[str],
    labels: dict[str, str],
    limit: int,
) -> tuple[ActivityFactionSignal, ...]:
    keys = set(better) | set(worse)
    ordered = sorted(
        keys,
        key=lambda key: (
            -(int(better.get(key, 0)) + int(worse.get(key, 0))),
            labels.get(key, key).casefold(),
        ),
    )
    return tuple(
        ActivityFactionSignal(
            label=labels.get(key, key),
            better=int(better.get(key, 0)),
            worse=int(worse.get(key, 0)),
        )
        for key in ordered[: max(0, int(limit))]
    )


def activity_cluster_summary(
    db,
    after_event_id: int,
    *,
    current_zone: str | None = None,
    top_limit: int = 3,
) -> ActivityClusterSummary:
    """Summarize repeated activity in the player's current log-geography segment.

    The monitoring-session boundary comes from Activity Pathways. After that boundary,
    both explicit zone entries and ``Welcome to EverQuest!`` are hard geography
    boundaries. Only rows after the latest such boundary participate. A zone entry names
    the new segment; Welcome clears zone ownership until a later explicit zone entry.
    This prevents post-login activity from being mislabeled as the zone from the prior
    login/session.

    Generic kill rows remain observations of a mob being slain; they are never labeled
    as guaranteed personal kills here. Faction changes are contemporaneous context only:
    their timing does not prove which mob, item, quest, or action caused the change.
    """
    boundary = max(0, int(after_event_id))
    zone = " ".join(str(current_zone or "").split()).strip()
    segment_after = boundary

    latest_boundary = db.conn.execute(
        """
        SELECT id, kind, zone
        FROM observed_events
        WHERE id>? AND kind IN ('zone','welcome')
        ORDER BY id DESC
        LIMIT 1
        """,
        (boundary,),
    ).fetchone()
    if latest_boundary is not None:
        segment_after = int(latest_boundary["id"])
        kind = str(latest_boundary["kind"] or "").casefold()
        if kind == "zone":
            zone = " ".join(str(latest_boundary["zone"] or "").split()).strip()
        else:
            # Welcome is an explicit loss of authoritative zone context. Do not trust
            # a stale caller-side current_zone value across this boundary.
            zone = ""

    rows = db.conn.execute(
        """
        SELECT kind, actor, target, item
        FROM observed_events
        WHERE id>? AND kind IN ('kill','loot','faction_up','faction_down')
        ORDER BY id
        """,
        (segment_after,),
    ).fetchall()

    mob_counts: Counter[str] = Counter()
    mob_labels: dict[str, str] = {}
    item_counts: Counter[str] = Counter()
    item_labels: dict[str, str] = {}
    faction_better: Counter[str] = Counter()
    faction_worse: Counter[str] = Counter()
    faction_labels: dict[str, str] = {}

    for row in rows:
        kind = str(row["kind"] or "").casefold()
        if kind == "kill":
            _add(mob_counts, mob_labels, row["actor"])
        elif kind == "loot":
            _add(item_counts, item_labels, row["item"])
        elif kind == "faction_up":
            _add(faction_better, faction_labels, row["target"])
        elif kind == "faction_down":
            _add(faction_worse, faction_labels, row["target"])

    faction_messages = sum(faction_better.values()) + sum(faction_worse.values())
    return ActivityClusterSummary(
        session_after_event_id=boundary,
        segment_after_event_id=segment_after,
        zone=zone,
        relevant_events=sum(mob_counts.values()) + sum(item_counts.values()),
        mobs_observed_slain=sum(mob_counts.values()),
        items_looted=sum(item_counts.values()),
        faction_messages=faction_messages,
        top_mobs=_top(mob_counts, mob_labels, top_limit),
        top_items=_top(item_counts, item_labels, top_limit),
        top_factions=_top_factions(
            faction_better,
            faction_worse,
            faction_labels,
            top_limit,
        ),
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


def _faction_signal_text(signal: ActivityFactionSignal) -> str:
    parts: list[str] = []
    if signal.better:
        parts.append(f"better ×{signal.better:,}")
    if signal.worse:
        parts.append(f"worse ×{signal.worse:,}")
    return f"{signal.label} " + ", ".join(parts)


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

    if summary.top_factions:
        faction_text = "; ".join(_faction_signal_text(row) for row in summary.top_factions)
        line += f" Faction messages in this same activity segment: {faction_text}."
        line += " Timing only; EverQuestie does not infer which activity caused them."

    return (
        line
        + " Log pattern only; generic kill lines mean observed slain, not guaranteed personal kills."
    )
