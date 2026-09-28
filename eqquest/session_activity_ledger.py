from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Iterable

from .activity_pathways import PathwaySuggestion
from .db import normalize_name
from .events import Event, event_from_observed_row
from .loot_relevance import loot_quest_uses_for_name
from .zone_authority import authoritative_zones_match


@dataclass(frozen=True, slots=True)
class SessionLedgerEntry:
    event_id: int
    event: Event
    annotations: tuple[str, ...]


@dataclass(slots=True)
class SessionLedgerCounter:
    """Incremental kill/loot counters for one monitoring-session boundary.

    The Live ledger renders once per persisted event. Re-querying every prior session
    row for each new event makes annotation cost quadratic over a long play session.
    This cursor consumes each kill/loot row once and keeps only normalized counters.
    """

    after_event_id: int = 0
    last_event_id: int = 0
    totals: dict[tuple[str, str], int] = field(default_factory=dict)
    personal_kills: dict[str, int] = field(default_factory=dict)

    def reset(self, after_event_id: int) -> None:
        boundary = max(0, int(after_event_id))
        self.after_event_id = boundary
        self.last_event_id = boundary
        self.totals.clear()
        self.personal_kills.clear()

    def update_through(self, db, event_id: int, after_event_id: int) -> None:
        boundary = max(0, int(after_event_id))
        if self.after_event_id != boundary or self.last_event_id < boundary:
            self.reset(boundary)

        upper = max(boundary, int(event_id))
        if upper <= self.last_event_id:
            return

        rows = db.conn.execute(
            """
            SELECT id,kind,actor,target,item
            FROM observed_events
            WHERE id>? AND id<=? AND kind IN ('kill','loot')
            ORDER BY id
            """,
            (int(self.last_event_id), upper),
        ).fetchall()
        for row in rows:
            kind = str(row["kind"] or "").casefold()
            subject = row["actor"] if kind == "kill" else row["item"]
            key = normalize_name(str(subject or ""))
            if not key:
                continue
            counter_key = (kind, key)
            self.totals[counter_key] = self.totals.get(counter_key, 0) + 1
            if (
                kind == "kill"
                and str(row["target"] or "").strip().casefold() == "you"
            ):
                self.personal_kills[key] = self.personal_kills.get(key, 0) + 1

        # IDs are monotonically increasing. Advancing through non-kill/loot gaps keeps
        # future updates bounded to rows that actually arrived since the last render.
        self.last_event_id = upper

    def subject_counts(self, kind: str, subject: str) -> tuple[int, int]:
        kind_key = str(kind or "").casefold()
        key = normalize_name(str(subject or ""))
        total = int(self.totals.get((kind_key, key), 0))
        personal = int(self.personal_kills.get(key, 0)) if kind_key == "kill" else 0
        return total, personal


def latest_observed_event(db) -> tuple[int, Event] | None:
    """Return the newest persisted player observation without changing either DB."""
    row = db.conn.execute(
        "SELECT * FROM observed_events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return int(row["id"]), event_from_observed_row(row)


def _matching_pathways(
    db,
    suggestions: Iterable[PathwaySuggestion],
    *,
    kind: str,
    subject: str,
    current_zone: str | None,
) -> tuple[str, ...]:
    key = normalize_name(subject)
    rows: list[str] = []
    seen: set[tuple[int, str, int, str]] = set()
    for suggestion in suggestions:
        for evidence in suggestion.evidence:
            if evidence.event_kind != kind or normalize_name(evidence.subject) != key:
                continue
            if (
                kind == "kill"
                and evidence.path_kind == "direct_objective"
                and evidence.step_zone
                and not authoritative_zones_match(db, current_zone, evidence.step_zone)
            ):
                continue
            identity = (
                int(suggestion.quest_id),
                evidence.path_kind,
                int(evidence.step_order),
                evidence.related_item,
            )
            if identity in seen:
                continue
            seen.add(identity)
            if evidence.path_kind == "direct_objective":
                detail = f"step {evidence.step_order}: {evidence.step_description}"
                if evidence.step_zone:
                    detail += f" [{evidence.step_zone}]"
            elif evidence.path_kind == "loot_turn_in":
                detail = "exact looted item is a reviewed quest turn-in item"
            elif evidence.path_kind == "mob_drop_quest":
                detail = (
                    f"reviewed chain: {subject} → {evidence.related_item} → quest item"
                )
            else:
                detail = "reviewed source-backed relationship"
            rows.append(f"POTENTIAL PATHWAY | {suggestion.quest_name} — {detail}")
    return tuple(rows)


def _rule_subject_matches(db, rule: dict, event: Event) -> bool:
    expected = str(rule.get("event", "")).casefold()
    if expected != str(event.kind or "").casefold():
        return False
    if expected == "kill":
        observed = event.actor
        entity_key = "npc_entity_id"
        literal_key = "npc"
    elif expected in {"loot", "receive_item"}:
        observed = event.item
        entity_key = "item_entity_id"
        literal_key = "item"
    else:
        return False
    if entity_key in rule:
        try:
            return db.name_matches_entity(int(rule[entity_key]), observed)
        except (TypeError, ValueError):
            return False
    literal = str(rule.get(literal_key, "")).strip()
    return bool(literal and normalize_name(literal) == normalize_name(str(observed or "")))


def _tracked_objective_context(
    db,
    event: Event,
    *,
    current_zone: str | None,
) -> tuple[str, ...]:
    """Return tracked-objective context through the database abstraction.

    Builder databases store tracked quests by quest_entity_id. Packaged runtime
    state deliberately stores stable quest_key identities instead. Do not query
    either physical tracked-state schema here; Database and RuntimeDatabase both
    expose tracked_quests() and quest_steps() with canonical entity IDs and
    merged progress.
    """
    if event.kind not in {"kill", "loot"}:
        return ()

    out: list[str] = []

    for tracked in db.tracked_quests():
        quest_id = int(tracked["id"])
        quest_name = str(tracked["name"])

        for row in db.quest_steps(quest_id):
            # Preserve the previous evidence rule: unsourced/synthetic steps do
            # not become source-backed Live intelligence.
            if row["source_page_id"] is None:
                continue

            try:
                rule = json.loads(row["match_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue

            if (
                not isinstance(rule, dict)
                or not _rule_subject_matches(db, rule, event)
            ):
                continue

            step_zone = str(row["zone"] or "").strip()

            if (
                event.kind == "kill"
                and step_zone
                and not authoritative_zones_match(
                    db,
                    current_zone,
                    step_zone,
                )
            ):
                continue

            step = int(row["step_order"])
            description = str(row["description"] or "")
            complete = bool(row["complete"])

            if (
                event.kind == "kill"
                and str(event.target or "").strip().casefold()
                != "you"
            ):
                out.append(
                    f"TRACKED QUEST CONTEXT | {quest_name} - "
                    f"step {step} target observed slain; "
                    "this log line does not prove your kill credit"
                )
                continue

            state = "; step currently complete" if complete else ""

            out.append(
                f"TRACKED QUEST CONTEXT | {quest_name} - "
                f"exact step {step} match: {description}{state}"
            )

    return tuple(out)


def _loot_relevance_lines(db, item_name: str) -> tuple[str, ...]:
    lines: list[str] = []
    for use in loot_quest_uses_for_name(db, item_name):
        quantity = f" x{use.quantity}" if use.quantity else ""
        tracked = "; tracked" if use.tracked else ""
        lines.append(
            f"ITEM RELEVANCE | {use.quest_name} — {use.relation_label}{quantity}{tracked}"
        )
    return tuple(lines)


def session_ledger_entry(
    db,
    event_id: int,
    after_event_id: int,
    *,
    current_zone: str | None = None,
    pathway_suggestions: Iterable[PathwaySuggestion] = (),
    annotation_limit: int = 8,
    counter: SessionLedgerCounter | None = None,
) -> SessionLedgerEntry | None:
    """Enrich one persisted kill/loot row with conservative session intelligence.

    The returned lines are a read-only projection. They never claim generic slain lines
    are personal kills, never infer drop rates, and never claim that one event changed
    quest progress. Existing quest/pathway/item surfaces remain the owners of actions.
    """
    row = db.conn.execute(
        "SELECT * FROM observed_events WHERE id=?",
        (int(event_id),),
    ).fetchone()
    if row is None:
        return None
    event = event_from_observed_row(row)
    annotations: list[str] = []
    ledger_counter = counter or SessionLedgerCounter()
    ledger_counter.update_through(db, int(event_id), int(after_event_id))

    if event.kind == "kill" and str(event.actor or "").strip():
        mob = str(event.actor).strip()
        observed, personal = ledger_counter.subject_counts("kill", mob)
        if str(event.target or "").strip().casefold() == "you":
            annotations.append(
                f"KILL TRACK | personal kill #{personal}; {mob} observed slain x{observed} this session"
            )
        else:
            killer = str(event.target or "").strip()
            suffix = f"; killer: {killer}" if killer else ""
            annotations.append(
                f"KILL TRACK | {mob} observed slain x{observed} this session{suffix}; "
                "no personal kill credit inferred"
            )
        annotations.extend(
            _tracked_objective_context(db, event, current_zone=current_zone)
        )
        annotations.extend(
            _matching_pathways(
                db,
                pathway_suggestions,
                kind="kill",
                subject=mob,
                current_zone=current_zone,
            )
        )

    elif event.kind == "loot" and str(event.item or "").strip():
        item = str(event.item).strip()
        observed, _personal = ledger_counter.subject_counts("loot", item)
        source = str(event.actor or "").strip()
        source_text = f"; from {source}'s corpse" if source else ""
        annotations.append(f"LOOT TRACK | {item} x{observed} this session{source_text}")
        annotations.extend(
            _tracked_objective_context(db, event, current_zone=current_zone)
        )
        annotations.extend(
            _matching_pathways(
                db,
                pathway_suggestions,
                kind="loot",
                subject=item,
                current_zone=current_zone,
            )
        )
        annotations.extend(_loot_relevance_lines(db, item))

    limit = max(0, int(annotation_limit))
    if limit and len(annotations) > limit:
        hidden = len(annotations) - (limit - 1)
        annotations = annotations[: max(0, limit - 1)] + [
            f"LIVE INTELLIGENCE | +{hidden} more exact source-backed match(es); see Live panels"
        ]
    elif limit == 0:
        annotations = []

    return SessionLedgerEntry(
        event_id=int(event_id),
        event=event,
        annotations=tuple(annotations),
    )
