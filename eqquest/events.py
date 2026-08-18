from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any


@dataclass(slots=True)
class Event:
    kind: str
    raw: str
    timestamp: datetime | None = None
    actor: str | None = None
    target: str | None = None
    text: str | None = None
    zone: str | None = None
    item: str | None = None
    amount: int | None = None
    fields: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        p: list[str] = [self.kind.upper()]

        if self.zone:
            p.append(self.zone)
        if self.actor:
            p.append(self.actor)
        if self.target:
            p.append(f"-> {self.target}")
        if self.item:
            p.append(self.item)
        if self.amount is not None:
            p.append(f"x{self.amount}")
        if self.kind in {"coin", "merchant_sale"} and self.fields:
            money = []
            for key, label in (("pp", "pp"), ("gp", "gp"), ("sp", "sp"), ("cp", "cp")):
                value = self.fields.get(key, 0)
                if value:
                    money.append(f"{value}{label}")
            if money:
                p.append(" ".join(money))
        if self.kind in {"level_gain", "level_loss"} and "level" in self.fields:
            p.append(f"level {self.fields['level']}")
        if self.text:
            p.append(self.text)

        return " | ".join(p)


def event_from_observed_row(row) -> Event:
    """Reconstruct one persisted ``observed_events`` row as an ``Event``.

    Stored observations are a user-state serialization boundary. Keep timestamp and
    structured-field recovery in one place so history, Live projections, and future
    provenance readers cannot drift in how they interpret the same persisted row.
    Malformed legacy timestamp/field payloads fail closed to ``None`` / ``{}``.
    """
    occurred = None
    if row["occurred_at"]:
        try:
            occurred = datetime.fromisoformat(str(row["occurred_at"]))
        except (TypeError, ValueError):
            occurred = None

    try:
        fields = json.loads(row["fields_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        fields = {}
    if not isinstance(fields, dict):
        fields = {}

    return Event(
        kind=str(row["kind"] or ""),
        raw=str(row["raw"] or ""),
        timestamp=occurred,
        actor=row["actor"],
        target=row["target"],
        text=row["text"],
        zone=row["zone"],
        item=row["item"],
        amount=row["amount"],
        fields=fields,
    )
