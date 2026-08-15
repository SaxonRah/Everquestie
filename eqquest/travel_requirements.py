from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

from .db import Database


_REQUIREMENT_KEYS = (
    "travel_requirements",
    "requirements",
    "entry_requirements",
    "transition_requirements",
)
_NESTED_PAYLOAD_KEYS = (
    "relationship_data",
    "travel",
    "gate",
    "transition",
)


@dataclass(frozen=True, slots=True)
class TravelRequirement:
    """One informational requirement attached to an otherwise traversable travel edge.

    Requirements never remove an edge from the route graph. They describe what the
    player must do or possess at that transition: a level threshold, key/item, NPC
    interaction, clicked object, scripted barrier, teleport dialogue, and so on.
    """

    kind: str
    text: str
    direction: str = "both"
    minimum_level: int | None = None
    source_names: tuple[str, ...] = ()

    @property
    def kind_label(self) -> str:
        return (self.kind or "requirement").replace("_", " ").strip() or "requirement"

    @property
    def source_label(self) -> str:
        return ", ".join(self.source_names)

    def applies_to(self, *, reverse: bool) -> bool:
        if self.direction == "both":
            return True
        return self.direction == ("reverse" if reverse else "forward")



def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()



def _safe_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None



def _direction(value: Any) -> str:
    text = _clean_text(value).casefold().replace("-", "_").replace(" ", "_")
    if text in {"forward", "source_to_target", "outbound"}:
        return "forward"
    if text in {"reverse", "target_to_source", "inbound"}:
        return "reverse"
    return "both"



def _requirement_text(data: dict[str, Any], minimum_level: int | None) -> str:
    for key in ("text", "description", "instruction", "label", "requirement"):
        text = _clean_text(data.get(key))
        if text:
            return text

    item_name = _clean_text(data.get("item_name") or data.get("key_name"))
    npc_name = _clean_text(data.get("npc_name"))
    object_name = _clean_text(data.get("object_name") or data.get("barrier_name"))
    action = _clean_text(data.get("action") or data.get("interaction"))

    if minimum_level is not None:
        return f"Minimum level {minimum_level}"
    if item_name:
        return f"Requires item: {item_name}"
    if npc_name and action:
        return f"{action} — {npc_name}"
    if npc_name:
        return f"Interact with NPC: {npc_name}"
    if object_name and action:
        return f"{action} — {object_name}"
    if object_name:
        return f"Interact with: {object_name}"
    return ""



def _one_requirement(value: Any, *, source_name: str) -> TravelRequirement | None:
    if isinstance(value, str):
        text = _clean_text(value)
        if not text:
            return None
        return TravelRequirement("requirement", text, source_names=(source_name,) if source_name else ())

    if not isinstance(value, dict):
        return None

    kind = _clean_text(
        value.get("kind") or value.get("type") or value.get("requirement_type") or "requirement"
    ).casefold().replace(" ", "_")
    minimum_level = _safe_int(
        value.get("minimum_level")
        if "minimum_level" in value
        else value.get("min_level")
        if "min_level" in value
        else value.get("level") if kind in {"level", "minimum_level", "level_requirement"} else None
    )
    text = _requirement_text(value, minimum_level)
    if not text:
        return None
    return TravelRequirement(
        kind=kind or "requirement",
        text=text,
        direction=_direction(value.get("direction") or value.get("applies_to")),
        minimum_level=minimum_level,
        source_names=(source_name,) if source_name else (),
    )



def _flatten_requirement_values(value: Any) -> Iterable[Any]:
    if isinstance(value, (list, tuple)):
        for item in value:
            yield item
        return
    yield value



def _requirements_from_payload(payload: Any, *, source_name: str) -> list[TravelRequirement]:
    if not isinstance(payload, dict):
        return []

    result: list[TravelRequirement] = []
    for key in _REQUIREMENT_KEYS:
        if key not in payload:
            continue
        for value in _flatten_requirement_values(payload.get(key)):
            requirement = _one_requirement(value, source_name=source_name)
            if requirement is not None:
                result.append(requirement)

    # Provider compilers preserve source-owned structured data inside nested payloads.
    # Recurse only through explicit travel/gate containers so arbitrary entity metadata
    # is never reinterpreted as a navigation requirement.
    for key in _NESTED_PAYLOAD_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            result.extend(_requirements_from_payload(nested, source_name=source_name))
    return result



def travel_requirements_from_data_json(
    raw: str | dict[str, Any] | None,
    *,
    source_name: str = "",
) -> tuple[TravelRequirement, ...]:
    if isinstance(raw, dict):
        payload: Any = raw
    else:
        try:
            payload = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
    requirements = _requirements_from_payload(payload, source_name=_clean_text(source_name))
    return tuple(requirements)



def _table_exists(db: Database, name: str) -> bool:
    return db.conn.execute(
        """
        SELECT 1 FROM sqlite_temp_master
        WHERE type IN ('table','view') AND name=?
        UNION ALL
        SELECT 1 FROM sqlite_master
        WHERE type IN ('table','view') AND name=?
        LIMIT 1
        """,
        (name, name),
    ).fetchone() is not None



def travel_requirements_for_hop(
    db: Database,
    source_entity_id: int,
    target_entity_id: int,
) -> tuple[TravelRequirement, ...]:
    """Aggregate every confirmed requirement that applies to one route direction.

    This deliberately queries all evidence rows for the hop rather than only the row
    chosen for coordinates/rendering. A map edge may own the best source-side /loc
    while a provider edge owns the gate requirement; neither fact should hide the other.
    """
    if not _table_exists(db, "zone_travel_edges"):
        return ()

    source = int(source_entity_id)
    target = int(target_entity_id)
    rows = db.conn.execute(
        """
        SELECT source_zone_entity_id,target_zone_entity_id,bidirectional,
               source_name,source_kind,data_json
        FROM zone_travel_edges
        WHERE status='linked' AND target_zone_entity_id IS NOT NULL
          AND (
              (source_zone_entity_id=? AND target_zone_entity_id=?)
              OR
              (bidirectional=1 AND source_zone_entity_id=? AND target_zone_entity_id=?)
          )
        ORDER BY source_kind,source_name,id
        """,
        (source, target, target, source),
    ).fetchall()

    merged: dict[tuple[str, str, str, int | None], TravelRequirement] = {}
    for row in rows:
        reverse = not (
            int(row["source_zone_entity_id"]) == source
            and int(row["target_zone_entity_id"]) == target
        )
        source_label = _clean_text(row["source_name"] or row["source_kind"])
        for requirement in travel_requirements_from_data_json(
            row["data_json"],
            source_name=source_label,
        ):
            if not requirement.applies_to(reverse=reverse):
                continue
            key = (
                requirement.kind,
                requirement.text.casefold(),
                requirement.direction,
                requirement.minimum_level,
            )
            previous = merged.get(key)
            if previous is None:
                merged[key] = requirement
                continue
            sources = tuple(sorted(set(previous.source_names) | set(requirement.source_names), key=str.casefold))
            merged[key] = TravelRequirement(
                kind=previous.kind,
                text=previous.text,
                direction=previous.direction,
                minimum_level=previous.minimum_level,
                source_names=sources,
            )

    return tuple(
        sorted(
            merged.values(),
            key=lambda requirement: (
                requirement.kind,
                requirement.minimum_level if requirement.minimum_level is not None else -1,
                requirement.text.casefold(),
            ),
        )
    )
