from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .db import Database


# Canonical EverQuestie graph relations for merchant/trainer data.  Importers should
# store only the forward fact; UI code derives the reverse direction automatically.
REL_SELLS = "sells"
REL_TEACHES_SPELL = "teaches_spell"
REL_TRAINS_SKILL = "trains_skill"

VENDOR_RELATIONS = {REL_SELLS, REL_TEACHES_SPELL, REL_TRAINS_SKILL}


@dataclass(frozen=True, slots=True)
class VendorLink:
    relation: str
    source_entity_id: int
    target_entity_id: int
    quantity: int | None = None
    evidence: str = ""
    data: dict[str, Any] | None = None


def link_vendor_fact(
    db: Database,
    *,
    npc_entity_id: int,
    target_entity_id: int,
    relation: str = REL_SELLS,
    source_page_id: int | None = None,
    evidence: str = "",
    quantity: int | None = None,
    price: str | int | float | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Canonical helper for future Allakhazam/client merchant imports.

    Merchant evidence is represented as NPC -> target.  `target` may be an item,
    spell, skill-like entity, etc.  Price/currency information stays on the edge so
    repeated inventories do not contaminate entity identity.
    """
    if relation not in VENDOR_RELATIONS:
        raise ValueError(f"Unsupported vendor relation: {relation}")
    payload = dict(data or {})
    if price not in (None, ""):
        payload["price"] = price
    payload["vendor_fact"] = True
    db.upsert_relationship(
        npc_entity_id,
        target_entity_id,
        relation,
        quantity=quantity,
        source_page_id=source_page_id,
        evidence=evidence,
        data=payload,
    )


def vendor_section_lines(db: Database, entity_id: int) -> list[str]:
    row = db.entity(entity_id)
    if row is None:
        return []
    rels = [r for r in db.relationships_for_entity(entity_id) if str(r["relation"]) in VENDOR_RELATIONS]
    if not rels:
        return []

    lines = ["", "Merchant / trainer relationships:"]
    order = {REL_SELLS: 0, REL_TEACHES_SPELL: 1, REL_TRAINS_SKILL: 2}
    rels.sort(key=lambda r: (order.get(str(r["relation"]), 99), str(r["target_kind"]), str(r["target_name"])))
    for rel in rels:
        relation = str(rel["relation"])
        if rel["direction"] == "out":
            other_kind = str(rel["target_kind"])
            other_name = str(rel["target_name"])
            if relation == REL_SELLS:
                label = "Sells"
            elif relation == REL_TEACHES_SPELL:
                label = "Teaches spell"
            else:
                label = "Trains skill"
        else:
            other_kind = str(rel["source_kind"])
            other_name = str(rel["source_name"])
            if relation == REL_SELLS:
                label = "Sold by"
            elif relation == REL_TEACHES_SPELL:
                label = "Taught by"
            else:
                label = "Trained by"
        suffix = ""
        try:
            import json
            data = json.loads(rel["data_json"] or "{}")
        except Exception:
            data = {}
        if isinstance(data, dict) and data.get("price") not in (None, ""):
            suffix = f" | price {data['price']}"
        lines.append(f"  • {label}: [{other_kind}] {other_name}{suffix}")
    return lines
