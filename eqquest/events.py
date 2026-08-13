from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
