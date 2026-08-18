from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable

from .activity_pathways import PathwaySuggestion
from .db import normalize_name
from .events import Event, event_from_observed_row
from .loot_relevance import recent_loot_relevance
from .zone_authority import authoritative_zones_match


@dataclass(frozen=True, slots=True)
class SessionLedgerEntry:
    event_id: int
    event: Event
    annotations: tuple[str, ...]


def latest_observed_event(db) -> tuple[int, Event] | None:
    """Return the newest persisted player observation without changing either DB."""
    row = db.conn.execute(
        "SELECT * FROM observed_events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return int(row["id"]), event_from_observed_row(row)


def _session_subject_counts(
    db,
    after_event_id: int,
    *,
    kind: str,
    field: str,
    subject: str,
) -> tuple[int, int]:
    if field not in {"actor", "item"}:
        raise ValueError(f"Unsupported observed-event subject field: {field}")
    rows = db.conn.execute(
        f"SELECT target,{field} AS subject FROM observed_events WHERE id>? AND kind=? ORDER BY id",
        (int(after_event_id), kind),
    ).fetchall()
    key = normalize_name(subject)
    total = 0
    personal = 0
    for row in rows:
        if normalize_name(str(row["subject"] or "")) != key:
            continue
        total += 1
        if kind == "kill" and str(row["target"] or "").strip().casefold() == "you":
            personal += 1
    return total, personal


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
    if event.kind not in {"kill", "loot"}:
        return ()
    rows = db.conn.execute(
        """
        SELECT q.id AS quest_id, q.name AS quest_name, qs.step_order,
               qs.description, qs.zone, qs.match_json,
               COALESCE(qp.complete,0) AS complete
        FROM tracked_quests tq
        JOIN entities q ON q.id=tq.quest_entity_id AND q.kind='quest'
        JOIN quest_steps qs ON qs.quest_entity_id=q.id
        LEFT JOIN quest_progress qp
          ON qp.quest_entity_id=qs.quest_entity_id AND qp.step_order=qs.step_order
        WHERE qs.source_page_id IS NOT NULL
        ORDER BY q.name, qs.step_order
        """
    ).fetchall()
    out: list[str] = []
    for row in rows:
        try:
            rule = json.loads(row["match_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(rule, dict) or not _rule_subject_matches(db, rule, event):
            continue
        step_zone = str(row["zone"] or "").strip()
        if (
            event.kind == "kill"
            and step_zone
            and not authoritative_zones_match(db, current_zone, step_zone)
        ):
            continue
        quest = str(row["quest_name"])
        step = int(row["step_order"])
        description = str(row["description"] or "")
        complete = bool(row["complete"])
        if event.kind == "kill" and str(event.target or "").strip().casefold() != "you":
            out.append(
                f"TRACKED QUEST CONTEXT | {quest} — step {step} target observed slain; "
                "this log line does not prove your kill credit"
            )
            continue
        state = "; step currently complete" if complete else ""
        out.append(
            f"TRACKED QUEST CONTEXT | {quest} — exact step {step} match: {description}{state}"
        )
    return tuple(out)


def _loot_relevance_lines(db, after_event_id: int, item_name: str) -> tuple[str, ...]:
    key = normalize_name(item_name)
    matches = (
        row
        for row in recent_loot_relevance(db, int(after_event_id), limit_items=1000)
        if normalize_name(row.item_name) == key
    )
    item = next(matches, None)
    if item is None:
        return ()
    lines: list[str] = []
    for use in item.uses:
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

    if event.kind == "kill" and str(event.actor or "").strip():
        mob = str(event.actor).strip()
        observed, personal = _session_subject_counts(
            db,
            after_event_id,
            kind="kill",
            field="actor",
            subject=mob,
        )
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
        observed, _personal = _session_subject_counts(
            db,
            after_event_id,
            kind="loot",
            field="item",
            subject=item,
        )
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
        annotations.extend(_loot_relevance_lines(db, after_event_id, item))

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
