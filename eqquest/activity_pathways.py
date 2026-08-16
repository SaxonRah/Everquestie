from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .db import normalize_name
from .profile_availability import entity_profile_decision


@dataclass(frozen=True, slots=True)
class PathwayEvidence:
    event_kind: str
    subject: str
    observed_count: int
    step_order: int
    step_description: str
    step_zone: str


@dataclass(frozen=True, slots=True)
class PathwaySuggestion:
    quest_id: int
    quest_name: str
    score: int
    evidence: tuple[PathwayEvidence, ...]
    profile_status: str

    @property
    def primary_reason(self) -> str:
        if not self.evidence:
            return "Exact structured quest relationship"
        evidence = self.evidence[0]
        action = "killed" if evidence.event_kind == "kill" else "looted"
        return f"{action} {evidence.subject} x{evidence.observed_count}"


@dataclass(frozen=True, slots=True)
class _Objective:
    quest_id: int
    quest_name: str
    event_kind: str
    subject: str
    step_order: int
    description: str
    zone: str


class ActivityPathwayEngine:
    """Project live player observations into source-backed quest opportunities.

    Only exact structured quest-step targets are indexed. Names and prose are never
    fuzzily interpreted as objectives. Session counters come from the writable player
    event log; knowledge stays read-only and a suggestion never means a quest is owned.
    """

    def __init__(self, db):
        self.db = db
        self._index: dict[tuple[str, str], list[_Objective]] | None = None
        self._counts: dict[tuple[str, str], int] = {}
        self._display_names: dict[tuple[str, str], str] = {}
        self._last_event_id = 0

    def reset_session(self, after_event_id: int | None = None) -> None:
        self._counts.clear()
        self._display_names.clear()
        self._last_event_id = int(after_event_id or 0)

    def latest_observed_event_id(self) -> int:
        row = self.db.conn.execute(
            "SELECT COALESCE(MAX(id),0) AS n FROM observed_events"
        ).fetchone()
        return int(row["n"] if row is not None else 0)

    def _entity_keys(self, entity_id: int) -> list[str]:
        rows = self.db.conn.execute(
            """
            SELECT normalized_name AS value FROM entities WHERE id=?
            UNION
            SELECT normalized_alias AS value FROM entity_aliases WHERE entity_id=?
            """,
            (int(entity_id), int(entity_id)),
        ).fetchall()
        return sorted(
            {str(row["value"] or "") for row in rows if str(row["value"] or "")}
        )

    def _build_index(self) -> dict[tuple[str, str], list[_Objective]]:
        index: dict[tuple[str, str], list[_Objective]] = {}
        rows = self.db.conn.execute(
            """
            SELECT qs.quest_entity_id, qs.step_order, qs.description, qs.zone,
                   qs.match_json, e.name AS quest_name
            FROM quest_steps qs
            JOIN entities e ON e.id=qs.quest_entity_id
            WHERE e.kind='quest'
            ORDER BY qs.quest_entity_id, qs.step_order
            """
        ).fetchall()
        for row in rows:
            try:
                rule = json.loads(row["match_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            expected = str(rule.get("event", "")).casefold()
            if expected == "receive_item":
                expected = "loot"
            if expected not in {"kill", "loot"}:
                continue

            keys: list[str] = []
            subject = ""
            entity_id = None
            if expected == "kill":
                entity_id = rule.get("npc_entity_id")
                literal = rule.get("npc")
            else:
                entity_id = rule.get("item_entity_id")
                literal = rule.get("item")

            if entity_id is not None:
                try:
                    entity_id = int(entity_id)
                    keys = self._entity_keys(entity_id)
                except (TypeError, ValueError):
                    keys = []
                entity = self.db.entity(entity_id) if keys else None
                subject = str(entity["name"] or "") if entity is not None else ""
            elif literal:
                subject = str(literal).strip()
                keys = [normalize_name(subject)] if subject else []

            if not keys:
                continue
            objective = _Objective(
                quest_id=int(row["quest_entity_id"]),
                quest_name=str(row["quest_name"]),
                event_kind=expected,
                subject=subject or keys[0],
                step_order=int(row["step_order"]),
                description=str(row["description"] or ""),
                zone=str(row["zone"] or ""),
            )
            for key in keys:
                bucket = index.setdefault((expected, key), [])
                if objective not in bucket:
                    bucket.append(objective)
        return index

    def _ensure_index(self) -> dict[tuple[str, str], list[_Objective]]:
        if self._index is None:
            self._index = self._build_index()
        return self._index

    def refresh_observations(self) -> int:
        """Consume newly persisted session events and return the number inspected."""
        rows = self.db.conn.execute(
            "SELECT id,kind,actor,item FROM observed_events WHERE id>? ORDER BY id",
            (self._last_event_id,),
        ).fetchall()
        for row in rows:
            self._last_event_id = max(self._last_event_id, int(row["id"]))
            kind = str(row["kind"] or "").casefold()
            if kind == "kill":
                subject = str(row["actor"] or "").strip()
            elif kind == "loot":
                subject = str(row["item"] or "").strip()
            else:
                continue
            if not subject:
                continue
            key = (kind, normalize_name(subject))
            self._counts[key] = self._counts.get(key, 0) + 1
            self._display_names.setdefault(key, subject)
        return len(rows)

    def suggestions(
        self,
        current_zone: str | None = None,
        *,
        limit: int = 10,
    ) -> list[PathwaySuggestion]:
        index = self._ensure_index()
        grouped: dict[int, dict[str, Any]] = {}
        zone_key = normalize_name(current_zone or "")

        for key, count in self._counts.items():
            if count <= 0:
                continue
            for objective in index.get(key, ()):
                if self.db.is_quest_tracked(objective.quest_id):
                    continue
                decision = entity_profile_decision(self.db, objective.quest_id)
                if decision.compatibility is False:
                    continue

                entry = grouped.setdefault(
                    objective.quest_id,
                    {
                        "name": objective.quest_name,
                        "score": 0,
                        "evidence": [],
                        "profile_status": decision.status,
                        "seen": set(),
                    },
                )
                evidence_key = (objective.event_kind, key[1], objective.step_order)
                if evidence_key in entry["seen"]:
                    continue
                entry["seen"].add(evidence_key)

                base = 45 if objective.event_kind == "loot" else 30
                repeat = min(count, 10) * (5 if objective.event_kind == "loot" else 3)
                zone_bonus = (
                    15
                    if zone_key and normalize_name(objective.zone) == zone_key
                    else 0
                )
                entry["score"] += base + repeat + zone_bonus
                entry["evidence"].append(
                    PathwayEvidence(
                        objective.event_kind,
                        self._display_names.get(key, objective.subject),
                        count,
                        objective.step_order,
                        objective.description,
                        objective.zone,
                    )
                )

        out = [
            PathwaySuggestion(
                quest_id=quest_id,
                quest_name=str(entry["name"]),
                score=int(entry["score"]),
                evidence=tuple(
                    sorted(
                        entry["evidence"],
                        key=lambda evidence: (
                            evidence.event_kind,
                            evidence.subject.casefold(),
                            evidence.step_order,
                        ),
                    )
                ),
                profile_status=str(entry["profile_status"]),
            )
            for quest_id, entry in grouped.items()
        ]
        out.sort(
            key=lambda suggestion: (
                -suggestion.score,
                suggestion.quest_name.casefold(),
                suggestion.quest_id,
            )
        )
        return out[: max(0, int(limit))]


def pathway_detail_text(suggestion: PathwaySuggestion) -> str:
    lines = [suggestion.quest_name, "", "Why this appeared:"]
    for evidence in suggestion.evidence:
        if evidence.event_kind == "kill":
            observed = f"Killed {evidence.subject} x{evidence.observed_count} this session"
            relation = "exact kill objective"
        else:
            observed = f"Looted {evidence.subject} x{evidence.observed_count} this session"
            relation = "exact item objective"
        zone = f" | {evidence.step_zone}" if evidence.step_zone else ""
        lines.append(f"  • {observed}")
        lines.append(
            f"    Quest step {evidence.step_order}: {evidence.step_description}{zone} "
            f"({relation})"
        )
    lines += [
        "",
        "This is a potential pathway, not proof that the quest is currently owned.",
        "Track it explicitly if you want EverQuestie to begin quest guidance.",
    ]
    return "\n".join(lines)
