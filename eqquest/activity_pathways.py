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
    path_kind: str = "direct_objective"
    related_item: str = ""
    relationship_evidence: str = ""


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
        if evidence.path_kind == "loot_turn_in":
            return (
                f"looted {evidence.subject} x{evidence.observed_count} "
                "→ quest turn-in item"
            )
        if evidence.path_kind == "mob_drop_quest":
            item = f" → {evidence.related_item}" if evidence.related_item else ""
            return (
                f"observed slain {evidence.subject} x{evidence.observed_count}{item}"
            )
        action = "observed slain" if evidence.event_kind == "kill" else "looted"
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


@dataclass(frozen=True, slots=True)
class _GraphOpportunity:
    quest_id: int
    quest_name: str
    event_kind: str
    path_kind: str
    subject: str
    related_item: str
    relationship_evidence: str


@dataclass(frozen=True, slots=True)
class _QuestItemLink:
    quest_id: int
    quest_name: str
    item_id: int
    item_name: str
    relation: str
    evidence: str


class ActivityPathwayEngine:
    """Project live player observations into source-backed quest opportunities.

    Direct pathways use source-backed exact structured quest-step targets. Graph pathways
    use only reviewed normalized relationship semantics and require a unique canonical
    NPC/item identity for the observed name. Names/prose are never fuzzily interpreted.
    Session counters come from writable player state; knowledge remains read-only and a
    suggestion never means a quest is owned.
    """

    def __init__(self, db):
        self.db = db
        self._index: dict[tuple[str, str], list[_Objective]] | None = None
        self._graph_index: dict[tuple[str, str], list[_GraphOpportunity]] | None = None
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

    def _unique_entity_keys(self, kind: str) -> dict[int, tuple[str, ...]]:
        """Return only names/aliases that resolve to one canonical entity of a kind."""
        rows = self.db.conn.execute(
            """
            SELECT e.id AS entity_id, e.normalized_name AS value
            FROM entities e
            WHERE e.kind=?
            UNION ALL
            SELECT e.id AS entity_id, a.normalized_alias AS value
            FROM entity_aliases a
            JOIN entities e ON e.id=a.entity_id
            WHERE e.kind=?
            """,
            (kind, kind),
        ).fetchall()
        owners: dict[str, set[int]] = {}
        for row in rows:
            key = str(row["value"] or "")
            if not key:
                continue
            owners.setdefault(key, set()).add(int(row["entity_id"]))

        by_entity: dict[int, list[str]] = {}
        for key, entity_ids in owners.items():
            if len(entity_ids) != 1:
                continue
            entity_id = next(iter(entity_ids))
            by_entity.setdefault(entity_id, []).append(key)
        return {
            entity_id: tuple(sorted(set(keys)))
            for entity_id, keys in by_entity.items()
        }

    def _build_index(self) -> dict[tuple[str, str], list[_Objective]]:
        index: dict[tuple[str, str], list[_Objective]] = {}
        rows = self.db.conn.execute(
            """
            SELECT qs.quest_entity_id, qs.step_order, qs.description, qs.zone,
                   qs.match_json, e.name AS quest_name
            FROM quest_steps qs
            JOIN entities e ON e.id=qs.quest_entity_id
            WHERE e.kind='quest'
              AND qs.source_page_id IS NOT NULL
            ORDER BY qs.quest_entity_id, qs.step_order
            """
        ).fetchall()
        for row in rows:
            try:
                rule = json.loads(row["match_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            expected = str(rule.get("event", "")).casefold()
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

    @staticmethod
    def _bounded_evidence(*parts: str) -> str:
        text = " | ".join(" ".join(str(part or "").split()) for part in parts if str(part or "").strip())
        return text[:500]

    def _build_graph_index(self) -> dict[tuple[str, str], list[_GraphOpportunity]]:
        """Compile reviewed one/two-hop quest opportunity relationships.

        Accepted normalized semantics:
          quest -> item : objective_turn_in_item / objective_loot
          item  -> npc  : drops_from

        Every relationship must retain a source_page_id. Second-hop observation
        identity uses only names/aliases unique within its entity kind.
        """
        graph: dict[tuple[str, str], list[_GraphOpportunity]] = {}
        item_keys = self._unique_entity_keys("item")
        npc_keys = self._unique_entity_keys("npc")

        quest_item_rows = self.db.conn.execute(
            """
            SELECT r.source_entity_id AS quest_id,
                   q.name AS quest_name,
                   r.target_entity_id AS item_id,
                   i.name AS item_name,
                   r.relation,
                   r.evidence
            FROM entity_relationships r
            JOIN entities q ON q.id=r.source_entity_id AND q.kind='quest'
            JOIN entities i ON i.id=r.target_entity_id AND i.kind='item'
            WHERE r.relation IN ('objective_loot','objective_turn_in_item')
              AND r.source_page_id IS NOT NULL
            ORDER BY r.source_entity_id, r.target_entity_id, r.relation, r.id
            """
        ).fetchall()
        links_by_item: dict[int, list[_QuestItemLink]] = {}
        for row in quest_item_rows:
            link = _QuestItemLink(
                quest_id=int(row["quest_id"]),
                quest_name=str(row["quest_name"]),
                item_id=int(row["item_id"]),
                item_name=str(row["item_name"]),
                relation=str(row["relation"]),
                evidence=self._bounded_evidence(str(row["evidence"] or "")),
            )
            links_by_item.setdefault(link.item_id, []).append(link)

            # Direct loot objectives are already represented by quest_steps. Turn-in
            # item relationships are the useful extra signal: possession can matter to
            # the quest even though the structured active action is handing it to an NPC.
            if link.relation != "objective_turn_in_item":
                continue
            for key in item_keys.get(link.item_id, ()):
                opportunity = _GraphOpportunity(
                    quest_id=link.quest_id,
                    quest_name=link.quest_name,
                    event_kind="loot",
                    path_kind="loot_turn_in",
                    subject=link.item_name,
                    related_item=link.item_name,
                    relationship_evidence=link.evidence,
                )
                bucket = graph.setdefault(("loot", key), [])
                if opportunity not in bucket:
                    bucket.append(opportunity)

        drop_rows = self.db.conn.execute(
            """
            SELECT r.source_entity_id AS item_id,
                   i.name AS item_name,
                   r.target_entity_id AS npc_id,
                   n.name AS npc_name,
                   r.evidence
            FROM entity_relationships r
            JOIN entities i ON i.id=r.source_entity_id AND i.kind='item'
            JOIN entities n ON n.id=r.target_entity_id AND n.kind='npc'
            WHERE r.relation='drops_from'
              AND r.source_page_id IS NOT NULL
            ORDER BY r.source_entity_id, r.target_entity_id, r.id
            """
        ).fetchall()
        for row in drop_rows:
            item_id = int(row["item_id"])
            npc_id = int(row["npc_id"])
            npc_name = str(row["npc_name"])
            item_name = str(row["item_name"])
            drop_evidence = str(row["evidence"] or "")
            for link in links_by_item.get(item_id, ()):
                quest_use = (
                    "quest loot objective"
                    if link.relation == "objective_loot"
                    else "quest turn-in item"
                )
                evidence = self._bounded_evidence(
                    f"drop: {drop_evidence}",
                    f"{quest_use}: {link.evidence}",
                )
                for key in npc_keys.get(npc_id, ()):
                    opportunity = _GraphOpportunity(
                        quest_id=link.quest_id,
                        quest_name=link.quest_name,
                        event_kind="kill",
                        path_kind="mob_drop_quest",
                        subject=npc_name,
                        related_item=item_name,
                        relationship_evidence=evidence,
                    )
                    bucket = graph.setdefault(("kill", key), [])
                    if opportunity not in bucket:
                        bucket.append(opportunity)

        return graph

    def _ensure_index(self) -> dict[tuple[str, str], list[_Objective]]:
        if self._index is None:
            self._index = self._build_index()
        return self._index

    def _ensure_graph_index(self) -> dict[tuple[str, str], list[_GraphOpportunity]]:
        if self._graph_index is None:
            self._graph_index = self._build_graph_index()
        return self._graph_index

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

    def _entry_for(self, grouped: dict[int, dict[str, Any]], quest_id: int, quest_name: str):
        if self.db.is_quest_tracked(quest_id):
            return None
        decision = entity_profile_decision(self.db, quest_id)
        if decision.compatibility is False:
            return None
        return grouped.setdefault(
            quest_id,
            {
                "name": quest_name,
                "score": 0,
                "evidence": [],
                "profile_status": decision.status,
                "seen": set(),
            },
        )

    def suggestions(
        self,
        current_zone: str | None = None,
        *,
        limit: int = 10,
    ) -> list[PathwaySuggestion]:
        if not self._counts:
            return []
        index = self._ensure_index()
        graph_index = self._ensure_graph_index()
        grouped: dict[int, dict[str, Any]] = {}
        zone_key = normalize_name(current_zone or "")

        for key, count in self._counts.items():
            if count <= 0:
                continue
            for objective in index.get(key, ()):
                entry = self._entry_for(grouped, objective.quest_id, objective.quest_name)
                if entry is None:
                    continue
                evidence_key = ("direct", objective.event_kind, key[1], objective.step_order)
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

            for opportunity in graph_index.get(key, ()):
                entry = self._entry_for(
                    grouped, opportunity.quest_id, opportunity.quest_name
                )
                if entry is None:
                    continue
                evidence_key = (
                    opportunity.path_kind,
                    key[1],
                    opportunity.related_item.casefold(),
                )
                if evidence_key in entry["seen"]:
                    continue
                entry["seen"].add(evidence_key)

                if opportunity.path_kind == "loot_turn_in":
                    base = 38
                    repeat = min(count, 10) * 4
                else:
                    base = 20
                    repeat = min(count, 10) * 2
                entry["score"] += base + repeat
                entry["evidence"].append(
                    PathwayEvidence(
                        event_kind=opportunity.event_kind,
                        subject=self._display_names.get(key, opportunity.subject),
                        observed_count=count,
                        step_order=0,
                        step_description="",
                        step_zone="",
                        path_kind=opportunity.path_kind,
                        related_item=opportunity.related_item,
                        relationship_evidence=opportunity.relationship_evidence,
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
                            0 if evidence.path_kind == "direct_objective" else 1,
                            evidence.event_kind,
                            evidence.subject.casefold(),
                            evidence.related_item.casefold(),
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
        if evidence.path_kind == "loot_turn_in":
            lines.append(
                f"  • You looted {evidence.subject} x{evidence.observed_count} this session"
            )
            lines.append(
                "    Source-backed chain: this exact item is a structured turn-in "
                "objective for the quest."
            )
            if evidence.relationship_evidence:
                lines.append(f"    Evidence: {evidence.relationship_evidence}")
            continue

        if evidence.path_kind == "mob_drop_quest":
            lines.append(
                f"  • Observed {evidence.subject} slain x{evidence.observed_count} this session"
            )
            lines.append(
                f"    Source-backed chain: {evidence.subject} → drops "
                f"{evidence.related_item} → quest item objective."
            )
            if evidence.relationship_evidence:
                lines.append(f"    Evidence: {evidence.relationship_evidence}")
            continue

        if evidence.event_kind == "kill":
            observed = (
                f"Observed {evidence.subject} slain x{evidence.observed_count} this session"
            )
            relation = "exact kill objective"
        else:
            observed = f"You looted {evidence.subject} x{evidence.observed_count} this session"
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