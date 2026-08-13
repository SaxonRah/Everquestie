from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .db import Database
from .events import Event


def eq(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.casefold() == b.casefold())


@dataclass(slots=True)
class Guidance:
    title: str
    text: str
    source_url: str | None = None


@dataclass(slots=True)
class ReconcileResult:
    quest_id: int
    source: str
    boundary: str
    confidence: str
    events_available: int
    events_replayed: int
    boundary_timestamp: str | None
    progress_total: int
    completed_steps: int
    total_steps: int

    @property
    def reconciled(self) -> bool:
        return self.events_replayed >= 0 and self.boundary != "none"

    def summary(self) -> str:
        if self.boundary == "none":
            return "no reliable quest-start boundary found; existing progress was preserved"
        when = f" @ {self.boundary_timestamp}" if self.boundary_timestamp else ""
        return (
            f"replayed {self.events_replayed} events from {self.boundary}{when}; "
            f"{self.completed_steps}/{self.total_steps} steps complete, "
            f"{self.progress_total} counted objective events"
        )


class QuestEngine:
    def __init__(self, db: Database):
        self.db = db

    def observe(self, event: Event) -> None:
        for quest in self.db.tracked_quests():
            self._observe_quest(int(quest["id"]), event)

    def _observe_quest(self, quest_id: int, event: Event) -> bool:
        """Apply one observation to one quest. Returns True if any step progressed."""
        tracked_now = next(
            (q for q in self.db.tracked_quests() if int(q["id"]) == quest_id),
            None,
        )
        if tracked_now is None:
            return False

        active_step = int(tracked_now["active_step"])
        progressed = False
        steps = self.db.quest_steps(quest_id)

        for step in steps:
            if int(step["complete"]):
                continue

            rule = json.loads(step["match_json"] or "{}")
            if not rule:
                continue

            expected = str(rule.get("event", "")).casefold()
            if expected not in {"kill", "loot", "receive_item"}:
                if int(step["step_order"]) != active_step:
                    continue

            matched, increment = self._match(rule, event)
            if not matched:
                continue

            old_count = int(step["progress_count"])
            new_count = old_count + increment
            need = max(1, int(rule.get("count", 1)))
            self.db.set_step_progress(
                quest_id,
                int(step["step_order"]),
                min(new_count, need),
                new_count >= need,
            )
            progressed = True

            tracked_now = next(
                (q for q in self.db.tracked_quests() if int(q["id"]) == quest_id),
                None,
            )
            if tracked_now:
                active_step = int(tracked_now["active_step"])

        return progressed

    def _match(self, rule: dict, event: Event) -> tuple[bool, int]:
        expected = str(rule.get("event", "")).casefold()
        if expected and expected != event.kind.casefold():
            return False, 0

        if "zone" in rule and not eq(str(rule["zone"]), event.zone):
            return False, 0

        if "item_entity_id" in rule:
            if not self.db.name_matches_entity(int(rule["item_entity_id"]), event.item):
                return False, 0
        elif "item" in rule and not eq(str(rule["item"]), event.item):
            return False, 0

        if "npc_entity_id" in rule:
            if event.kind == "kill":
                npc = event.actor
            elif event.kind == "consider":
                npc = event.target
            else:
                npc = event.actor or event.target
            if not self.db.name_matches_entity(int(rule["npc_entity_id"]), npc):
                return False, 0
        elif "npc" in rule:
            if event.kind == "kill":
                npc = event.actor
            elif event.kind == "consider":
                npc = event.target
            else:
                npc = event.actor or event.target
            if not eq(str(rule["npc"]), npc):
                return False, 0

        if "quest_entity_id" in rule:
            if not self.db.name_matches_entity(int(rule["quest_entity_id"]), event.text):
                return False, 0

        if "contains" in rule:
            haystack = event.text or event.raw
            if str(rule["contains"]).casefold() not in haystack.casefold():
                return False, 0

        return True, 1

    def _quest_starter_ids(self, quest_id: int) -> list[int]:
        return [
            int(r["id"])
            for r in self.db.relationship_targets(quest_id, "started_by")
            if r["kind"] == "npc"
        ]

    def _event_matches_any_count_objective(self, quest_id: int, event: Event) -> bool:
        for step in self.db.quest_steps(quest_id):
            rule = json.loads(step["match_json"] or "{}")
            if rule.get("event") not in {"kill", "loot", "receive_item"}:
                continue
            matched, _ = self._match(rule, event)
            if matched:
                return True
        return False

    def _find_reconcile_boundary(self, quest_id: int, events: list[Event]):
        for i in range(len(events) - 1, -1, -1):
            e = events[i]
            if (
                e.kind == "task_assigned"
                and e.text
                and self.db.name_matches_entity(quest_id, e.text)
            ):
                return i, "task assignment", "high"

        starters = self._quest_starter_ids(quest_id)
        if starters:
            for i in range(len(events) - 1, -1, -1):
                e = events[i]
                if e.kind != "say" or not e.text:
                    continue
                if not any(self.db.name_matches_entity(npc_id, e.text.replace("Hail,", "").strip())
                           or self.db.name_matches_entity(npc_id, e.text)
                           for npc_id in starters):
                    continue
                if any(
                    self._event_matches_any_count_objective(quest_id, later)
                    for later in events[i + 1:]
                ):
                    return i, "starter NPC hail", "medium"

        return None, "none", "none"

    def reconcile_quest_from_events(
        self,
        quest_id: int,
        events: Iterable[Event],
        *,
        source: str = "event history",
    ) -> ReconcileResult:
        materialized = list(events)
        start, boundary, confidence = self._find_reconcile_boundary(quest_id, materialized)
        if start is None:
            steps = self.db.quest_steps(quest_id)
            return ReconcileResult(
                quest_id=quest_id,
                source=source,
                boundary="none",
                confidence="none",
                events_available=len(materialized),
                events_replayed=-1,
                boundary_timestamp=None,
                progress_total=sum(int(s["progress_count"]) for s in steps),
                completed_steps=sum(1 for s in steps if int(s["complete"])),
                total_steps=len(steps),
            )

        self.db.reset_quest_progress(quest_id)
        replay = materialized[start:]
        for event in replay:
            self._observe_quest(quest_id, event)

        steps = self.db.quest_steps(quest_id)
        stamp = materialized[start].timestamp
        return ReconcileResult(
            quest_id=quest_id,
            source=source,
            boundary=boundary,
            confidence=confidence,
            events_available=len(materialized),
            events_replayed=len(replay),
            boundary_timestamp=stamp.isoformat(sep=" ", timespec="seconds") if stamp else None,
            progress_total=sum(int(s["progress_count"]) for s in steps),
            completed_steps=sum(1 for s in steps if int(s["complete"])),
            total_steps=len(steps),
        )

    def reconcile_quest_from_history(self, quest_id: int) -> ReconcileResult:
        return self.reconcile_quest_from_events(
            quest_id,
            self.db.observed_event_history(),
            source="stored observation history",
        )

    def reconcile_quest_from_log(self, quest_id: int, path: str | Path, parser=None) -> ReconcileResult:
        from .parser import EQLogParser

        log_path = Path(path)
        parser = parser or EQLogParser()
        events: list[Event] = []
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                event = parser.parse_line(line)
                if event is not None:
                    events.append(event)
        return self.reconcile_quest_from_events(
            quest_id,
            events,
            source=f"log file {log_path.name}",
        )

    def guidance(self, current_zone: str | None) -> list[Guidance]:
        out: list[Guidance] = []

        for quest in self.db.tracked_quests():
            quest_id = int(quest["id"])
            active_step = int(quest["active_step"])
            steps = self.db.quest_steps(quest_id)

            pending = next(
                (s for s in steps if int(s["step_order"]) == active_step),
                None,
            )

            if not pending:
                out.append(Guidance(
                    quest["name"],
                    "All locally defined steps are complete.",
                    quest["source_url"],
                ))
                continue

            step_zone = pending["zone"]
            if step_zone and current_zone and not eq(step_zone, current_zone):
                prefix = f"Travel from {current_zone} to {step_zone}. "
            elif step_zone and not current_zone:
                prefix = f"Destination zone: {step_zone}. "
            else:
                prefix = ""

            rule = json.loads(pending["match_json"] or "{}")
            progress = int(pending["progress_count"])
            need = max(1, int(rule.get("count", 1)))
            suffix = f" [{progress}/{need}]" if need > 1 else ""

            extras: list[str] = []
            for step in steps:
                if int(step["step_order"]) == active_step or int(step["complete"]):
                    continue
                r = json.loads(step["match_json"] or "{}")
                if r.get("event") not in {"kill", "loot", "receive_item"}:
                    continue
                n = max(1, int(r.get("count", 1)))
                p = int(step["progress_count"])
                if p:
                    extras.append(f"Also: {step['description']} [{p}/{n}]")

            text = prefix + pending["description"] + suffix
            if extras:
                text += "\n" + "\n".join(extras)

            out.append(Guidance(
                quest["name"],
                text,
                quest["source_url"],
            ))

        return out
