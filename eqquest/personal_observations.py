from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .db import normalize_name


@dataclass(frozen=True, slots=True)
class PersonalObservationCount:
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class PersonalObservationSummary:
    entity_id: int
    entity_kind: str
    entity_name: str
    counts: tuple[PersonalObservationCount, ...]
    first_observed: str
    last_observed: str
    direct_loot: tuple[PersonalObservationCount, ...] = ()
    direct_sources: tuple[PersonalObservationCount, ...] = ()

    @property
    def observed(self) -> bool:
        return any(row.count > 0 for row in self.counts) or bool(self.direct_loot) or bool(self.direct_sources)


_EVENT_FIELDS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "npc": (
        ("kill", "actor", "Observed slain"),
        ("target_npc", "target", "Targeted"),
        ("consider", "target", "Considered"),
        ("npc_say", "actor", "Heard speaking"),
        ("death", "actor", "Slain you"),
        ("merchant_sale", "actor", "Merchant sales involving this NPC"),
    ),
    "item": (
        ("loot", "item", "You looted"),
        ("merchant_sale", "item", "You sold to a merchant"),
    ),
    "faction": (
        ("faction_up", "target", "Standing got better"),
        ("faction_down", "target", "Standing got worse"),
    ),
    "zone": (
        ("zone", "zone", "Entered"),
    ),
    "spell": (
        ("cast", "text", "You began casting"),
    ),
    "quest": (
        ("task_assigned", "text", "Task assigned"),
        ("task_update", "text", "Task update messages"),
    ),
}


def _candidate_labels(db, entity_id: int, kind: str) -> tuple[str, ...]:
    """Return display labels that uniquely identify this canonical entity within kind."""
    rows = db.conn.execute(
        """
        SELECT name AS label, normalized_name AS normalized
        FROM entities WHERE id=? AND kind=?
        UNION ALL
        SELECT a.alias AS label, a.normalized_alias AS normalized
        FROM entity_aliases a
        JOIN entities e ON e.id=a.entity_id
        WHERE a.entity_id=? AND e.kind=?
        """,
        (int(entity_id), kind, int(entity_id), kind),
    ).fetchall()
    accepted: dict[str, str] = {}
    for row in rows:
        label = " ".join(str(row["label"] or "").split()).strip()
        normalized = str(row["normalized"] or "") or normalize_name(label)
        if not label or not normalized:
            continue
        owners = db.conn.execute(
            """
            SELECT entity_id FROM (
                SELECT id AS entity_id
                FROM entities
                WHERE kind=? AND normalized_name=?
                UNION
                SELECT a.entity_id AS entity_id
                FROM entity_aliases a
                JOIN entities e ON e.id=a.entity_id
                WHERE e.kind=? AND a.normalized_alias=?
            )
            ORDER BY entity_id
            """,
            (kind, normalized, kind, normalized),
        ).fetchall()
        owner_ids = {int(owner["entity_id"]) for owner in owners}
        if owner_ids == {int(entity_id)}:
            accepted.setdefault(label.casefold(), label)
    return tuple(sorted(accepted.values(), key=str.casefold))


def _where_labels(field: str, labels: tuple[str, ...]) -> tuple[str, list[str]]:
    placeholders = ",".join("?" for _ in labels)
    return f"{field} COLLATE NOCASE IN ({placeholders})", list(labels)


def _count_event(db, kind: str, field: str, labels: tuple[str, ...]) -> tuple[int, str, str]:
    if not labels:
        return 0, "", ""
    where, params = _where_labels(field, labels)
    row = db.conn.execute(
        f"""
        SELECT COUNT(*) AS n,
               COALESCE(MIN(occurred_at),'') AS first_observed,
               COALESCE(MAX(occurred_at),'') AS last_observed
        FROM observed_events
        WHERE kind=? AND {where}
        """,
        [kind, *params],
    ).fetchone()
    if row is None:
        return 0, "", ""
    return int(row["n"]), str(row["first_observed"] or ""), str(row["last_observed"] or "")


def _merge_time(first: str, last: str, candidate_first: str, candidate_last: str) -> tuple[str, str]:
    if candidate_first and (not first or candidate_first < first):
        first = candidate_first
    if candidate_last and (not last or candidate_last > last):
        last = candidate_last
    return first, last


def _top_grouped(db, *, kind: str, match_field: str, labels: tuple[str, ...], group_field: str, limit: int = 8) -> tuple[PersonalObservationCount, ...]:
    if not labels:
        return ()
    where, params = _where_labels(match_field, labels)
    rows = db.conn.execute(
        f"""
        SELECT {group_field} AS label, COUNT(*) AS n
        FROM observed_events
        WHERE kind=? AND {where}
          AND {group_field} IS NOT NULL AND TRIM({group_field})<>''
        GROUP BY {group_field} COLLATE NOCASE
        ORDER BY n DESC, {group_field} COLLATE NOCASE
        LIMIT ?
        """,
        [kind, *params, max(0, int(limit))],
    ).fetchall()
    return tuple(
        PersonalObservationCount(str(row["label"] or ""), int(row["n"]))
        for row in rows
    )


def personal_observation_summary(db, entity_id: int) -> PersonalObservationSummary | None:
    entity = db.entity(int(entity_id))
    if entity is None:
        return None
    kind = str(entity["kind"] or "")
    name = str(entity["name"] or "")
    specs = _EVENT_FIELDS.get(kind)
    if not specs:
        return PersonalObservationSummary(int(entity_id), kind, name, (), "", "")

    labels = _candidate_labels(db, int(entity_id), kind)
    if not labels:
        # Duplicate canonical names/aliases are deliberately not mapped to one entity.
        return PersonalObservationSummary(int(entity_id), kind, name, (), "", "")

    counts: list[PersonalObservationCount] = []
    first = ""
    last = ""
    for event_kind, field, label in specs:
        count, event_first, event_last = _count_event(db, event_kind, field, labels)
        if count:
            counts.append(PersonalObservationCount(label, count))
            first, last = _merge_time(first, last, event_first, event_last)

    direct_loot: tuple[PersonalObservationCount, ...] = ()
    direct_sources: tuple[PersonalObservationCount, ...] = ()
    if kind == "npc":
        # Only loot lines that explicitly named this corpse source qualify. A generic
        # loot line is never associated with the currently selected NPC by proximity.
        direct_loot = _top_grouped(
            db,
            kind="loot",
            match_field="actor",
            labels=labels,
            group_field="item",
        )
    elif kind == "item":
        # These are raw corpse/source names stated by the player's own loot lines.
        # They are personal observations, not canonical drops_from assertions.
        direct_sources = _top_grouped(
            db,
            kind="loot",
            match_field="item",
            labels=labels,
            group_field="actor",
        )

    return PersonalObservationSummary(
        entity_id=int(entity_id),
        entity_kind=kind,
        entity_name=name,
        counts=tuple(counts),
        first_observed=first,
        last_observed=last,
        direct_loot=direct_loot,
        direct_sources=direct_sources,
    )


def _display_time(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text).isoformat(sep=" ", timespec="seconds")
    except ValueError:
        return text


def personal_observation_text(db, entity_id: int) -> str:
    summary = personal_observation_summary(db, int(entity_id))
    if summary is None or not summary.observed:
        return ""

    lines = [
        "Your log observations:",
        "  Personal/local history only — not canonical EverQuest source data.",
    ]
    for row in summary.counts:
        lines.append(f"  • {row.label}: {row.count:,}")

    first = _display_time(summary.first_observed)
    last = _display_time(summary.last_observed)
    if first:
        lines.append(f"  First logged: {first}")
    if last:
        lines.append(f"  Last logged: {last}")

    if summary.direct_loot:
        lines += [
            "",
            "  Items your loot log explicitly named from this NPC's corpse:",
        ]
        lines.extend(f"    • {row.label}: {row.count:,}" for row in summary.direct_loot)
        lines.append("  These are direct personal observations, not a calculated drop rate.")

    if summary.direct_sources:
        lines += [
            "",
            "  Corpse/source names explicitly recorded when you looted this item:",
        ]
        lines.extend(f"    • {row.label}: {row.count:,}" for row in summary.direct_sources)
        lines.append("  These are direct personal observations, not canonical drop-table claims.")

    if summary.entity_kind == "npc" and any(row.label == "Observed slain" for row in summary.counts):
        lines.append(
            "  Generic kill lines mean observed slain; they are not guaranteed personal kills."
        )
    return "\n".join(lines)
