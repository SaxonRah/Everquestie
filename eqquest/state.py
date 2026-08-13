from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field

from .events import Event


@dataclass
class SessionState:
    current_zone: str | None = None
    zone_source: str = "unknown"
    last_location: tuple[float, float, float] | None = None
    seen_npcs: deque[str] = field(default_factory=lambda: deque(maxlen=30))
    seen_items: deque[str] = field(default_factory=lambda: deque(maxlen=30))
    looted_items: Counter[str] = field(default_factory=Counter)
    killed_npcs: Counter[str] = field(default_factory=Counter)

    def set_zone(self, zone: str | None, *, source: str, force: bool = False) -> bool:
        """Set current zone with conservative source priority.

        Actual log/manual state may always change the zone. Quest-derived zones are
        suggestions and only fill an unknown (or previously quest-inferred) zone.
        Returns True if current zone/source changed.
        """
        if not zone or not zone.strip():
            return False
        zone = zone.strip()

        if source == "quest" and not force:
            if self.current_zone and self.zone_source not in {"unknown", "quest"}:
                return False

        changed = self.current_zone != zone or self.zone_source != source
        if self.current_zone != zone:
            # /loc belongs to the old zone and must never be projected onto a new map.
            self.last_location = None
        self.current_zone = zone
        self.zone_source = source
        return changed

    def apply(self, event: Event) -> None:
        if event.kind == "zone" and event.zone:
            self.set_zone(event.zone, source="log", force=True)

        elif event.kind == "loc":
            self.last_location = (
                float(event.fields["x"]),
                float(event.fields["y"]),
                float(event.fields["z"]),
            )

        if event.kind in {"npc_say", "consider", "target_npc", "kill"}:
            npc = event.actor if event.kind not in {"consider", "target_npc"} else event.target
            if npc:
                self.seen_npcs.appendleft(npc)

        if event.kind == "loot" and event.item:
            self.seen_items.appendleft(event.item)
            self.looted_items[event.item.casefold()] += 1

        if event.kind == "receive_item" and event.item:
            self.seen_items.appendleft(event.item)

        if event.kind == "kill" and event.actor:
            self.killed_npcs[event.actor.casefold()] += 1
