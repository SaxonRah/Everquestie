from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .db import normalize_name


@dataclass(frozen=True, slots=True)
class SessionCount:
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class SessionActivitySummary:
    after_event_id: int
    event_count: int
    zones: tuple[str, ...]
    starting_zone: str
    current_zone: str
    mobs_observed_slain: int
    unique_mobs_observed_slain: int
    top_mobs: tuple[SessionCount, ...]
    items_looted: int
    unique_items_looted: int
    top_items: tuple[SessionCount, ...]
    faction_up: int
    faction_down: int
    factions_touched: tuple[str, ...]
    deaths: int
    levels_gained: int
    levels_lost: int
    tasks_assigned: int
    task_updates: int
    merchant_sales: int
    pathway_count: int = 0

    @property
    def empty(self) -> bool:
        return self.event_count == 0


def _counter_add(counter: Counter[str], labels: dict[str, str], value: str | None) -> None:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return
    key = normalize_name(text)
    if not key:
        return
    counter[key] += 1
    labels.setdefault(key, text)


def _top(counter: Counter[str], labels: dict[str, str], limit: int) -> tuple[SessionCount, ...]:
    return tuple(
        SessionCount(labels.get(key, key), int(count))
        for key, count in sorted(
            counter.items(),
            key=lambda pair: (-int(pair[1]), labels.get(pair[0], pair[0]).casefold()),
        )[: max(0, int(limit))]
    )


def _append_zone(zones: list[str], seen: set[str], value: str | None) -> None:
    zone = " ".join(str(value or "").split()).strip()
    if not zone:
        return
    key = normalize_name(zone)
    if not key or key in seen:
        return
    seen.add(key)
    zones.append(zone)


def session_activity_summary(
    db,
    after_event_id: int,
    *,
    starting_zone: str | None = None,
    current_zone: str | None = None,
    pathway_count: int = 0,
    top_limit: int = 5,
) -> SessionActivitySummary:
    """Summarize one monitoring session from writable observed-event history.

    The summary reports only what the log says. In particular, generic kill events are
    counted as mobs *observed slain*, not personal kills, and faction messages are not
    causally attributed to nearby combat unless canonical knowledge says so elsewhere.
    """
    rows = db.conn.execute(
        """
        SELECT id, kind, actor, target, zone, item
        FROM observed_events
        WHERE id>?
        ORDER BY id
        """,
        (int(after_event_id),),
    ).fetchall()

    mob_counts: Counter[str] = Counter()
    mob_labels: dict[str, str] = {}
    item_counts: Counter[str] = Counter()
    item_labels: dict[str, str] = {}
    faction_counts: Counter[str] = Counter()
    faction_labels: dict[str, str] = {}

    zones: list[str] = []
    seen_zones: set[str] = set()
    start = " ".join(str(starting_zone or "").split()).strip()
    _append_zone(zones, seen_zones, start)

    faction_up = 0
    faction_down = 0
    deaths = 0
    levels_gained = 0
    levels_lost = 0
    tasks_assigned = 0
    task_updates = 0
    merchant_sales = 0

    for row in rows:
        kind = str(row["kind"] or "").casefold()
        if kind == "zone":
            _append_zone(zones, seen_zones, row["zone"])
        elif kind == "kill":
            _counter_add(mob_counts, mob_labels, row["actor"])
        elif kind == "loot":
            _counter_add(item_counts, item_labels, row["item"])
        elif kind == "faction_up":
            faction_up += 1
            _counter_add(faction_counts, faction_labels, row["target"])
        elif kind == "faction_down":
            faction_down += 1
            _counter_add(faction_counts, faction_labels, row["target"])
        elif kind == "death":
            deaths += 1
        elif kind == "level_gain":
            levels_gained += 1
        elif kind == "level_loss":
            levels_lost += 1
        elif kind == "task_assigned":
            tasks_assigned += 1
        elif kind == "task_update":
            task_updates += 1
        elif kind == "merchant_sale":
            merchant_sales += 1

    current = " ".join(str(current_zone or "").split()).strip()
    _append_zone(zones, seen_zones, current)

    factions = tuple(
        faction_labels.get(key, key)
        for key, _count in sorted(
            faction_counts.items(),
            key=lambda pair: faction_labels.get(pair[0], pair[0]).casefold(),
        )
    )
    return SessionActivitySummary(
        after_event_id=int(after_event_id),
        event_count=len(rows),
        zones=tuple(zones),
        starting_zone=start,
        current_zone=current,
        mobs_observed_slain=sum(mob_counts.values()),
        unique_mobs_observed_slain=len(mob_counts),
        top_mobs=_top(mob_counts, mob_labels, top_limit),
        items_looted=sum(item_counts.values()),
        unique_items_looted=len(item_counts),
        top_items=_top(item_counts, item_labels, top_limit),
        faction_up=faction_up,
        faction_down=faction_down,
        factions_touched=factions,
        deaths=deaths,
        levels_gained=levels_gained,
        levels_lost=levels_lost,
        tasks_assigned=tasks_assigned,
        task_updates=task_updates,
        merchant_sales=merchant_sales,
        pathway_count=max(0, int(pathway_count)),
    )


def session_activity_text(summary: SessionActivitySummary) -> str:
    if summary.empty:
        zone = f"\nCurrent zone: {summary.current_zone}" if summary.current_zone else ""
        return "No parsed log activity has been observed in this monitoring session yet." + zone

    lines = [
        "Session activity recap",
        "",
        f"Parsed log events: {summary.event_count:,}",
        f"Zones seen/current: {len(summary.zones):,}",
    ]
    if summary.zones:
        lines.append("  " + " → ".join(summary.zones))
    lines += [
        f"Mobs observed slain: {summary.mobs_observed_slain:,} "
        f"({summary.unique_mobs_observed_slain:,} unique)",
        f"Items you looted: {summary.items_looted:,} ({summary.unique_items_looted:,} unique)",
        f"Faction messages: +{summary.faction_up:,} / -{summary.faction_down:,}",
        f"Deaths: {summary.deaths:,}",
        f"Levels: +{summary.levels_gained:,} / -{summary.levels_lost:,}",
        f"Tasks: {summary.tasks_assigned:,} assigned / {summary.task_updates:,} updates",
        f"Merchant sales observed: {summary.merchant_sales:,}",
        f"Potential pathways currently surfaced: {summary.pathway_count:,}",
    ]
    if summary.top_mobs:
        lines += ["", "Most-observed slain mobs:"]
        lines.extend(f"  • {row.label}: {row.count:,}" for row in summary.top_mobs)
    if summary.top_items:
        lines += ["", "Most-looted items:"]
        lines.extend(f"  • {row.label}: {row.count:,}" for row in summary.top_items)
    if summary.factions_touched:
        lines += ["", "Factions with standing-change messages:"]
        lines.extend(f"  • {name}" for name in summary.factions_touched)
    lines += [
        "",
        "Observation boundary:",
        "  Generic kill lines are reported as mobs observed slain, not guaranteed personal kills.",
        "  Faction messages are listed as contemporaneous observations, not attributed to a specific kill.",
    ]
    return "\n".join(lines)
