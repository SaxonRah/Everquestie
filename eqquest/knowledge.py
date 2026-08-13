from __future__ import annotations

import json
from .db import Database


RELATION_LABELS = {
    "occurs_in": "Occurs in",
    "started_by": "Started by",
    "quest_item": "Quest item",
    "related_creature": "Related creature",
    "related_quest": "Related quest",
    "objective_kill": "Kill target",
    "objective_loot": "Loot objective",
    "objective_source_creature": "Loot source",
    "objective_turn_in_item": "Turn-in item",
    "objective_turn_in_to": "Turn in to",
    "objective_speak": "Speak with",
    "drops_from": "Drops from",
    "turn_in_to": "Turn in to",
    "found_in": "Found in",
    "connected_to": "Connected to",
    "starts_in": "Starts in",
}


def relation_label(relation: str) -> str:
    return RELATION_LABELS.get(relation, relation.replace("_", " ").title())



def _first(data: dict, *keys):
    for key in keys:
        if key in data and data[key] not in (None, "", [], {}):
            return data[key]
    return None


def _format_duration_ms(value) -> str | None:
    if value is None or value == "":
        return None
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return str(value)
    if ms == 0:
        return "0 s"
    return f"{ms / 1000:g} s"


def _render_spell_detail(data: dict) -> list[str]:
    lines = ["", "Spell mechanics (installed EverQuest client):"]
    scalar = [
        ("Mana", _first(data, "mana")),
        ("Endurance", _first(data, "endurance")),
        ("Cast time", _format_duration_ms(_first(data, "castTime", "cast_time"))),
        ("Recovery", _format_duration_ms(_first(data, "recoveryTime", "recovery_time"))),
        ("Recast", _format_duration_ms(_first(data, "recastTime", "recast_time"))),
        ("Range", _first(data, "range")),
        ("AE range", _first(data, "aeRange", "ae_range")),
        ("Target", _first(data, "targetType", "target_type", "target")),
        ("Resist", _first(data, "resistType", "resist_type", "resist")),
        ("Beneficial", _first(data, "beneficial")),
        ("Category", _first(data, "category", "categoryName", "category_name")),
        ("Subcategory", _first(data, "subcategory", "subCategory", "subcategoryName")),
        ("Duration", _first(data, "duration", "durationValue", "duration_value")),
        ("Timer", _first(data, "timerId", "timer_id")),
    ]
    for label, value in scalar:
        if value is not None:
            lines.append(f"  {label}: {value}")

    classes = _first(data, "classes", "classLevels", "class_levels")
    if classes:
        lines.append("  Classes:")
        if isinstance(classes, dict):
            def key_order(item):
                try:
                    return int(item[1])
                except Exception:
                    return 9999
            for cls, level in sorted(classes.items(), key=key_order):
                if level not in (None, "", 255):
                    lines.append(f"    • {cls}: {level}")
        elif isinstance(classes, list):
            for value in classes:
                if isinstance(value, dict):
                    name = _first(value, "name", "class", "className", "class_name")
                    level = _first(value, "level", "requiredLevel", "required_level")
                    lines.append(f"    • {name or 'Class'}" + (f": {level}" if level is not None else ""))
                else:
                    lines.append(f"    • {value}")

    effects = _first(data, "effects", "effectSlots", "effect_slots")
    if effects:
        lines.append("  Effects:")
        if isinstance(effects, dict):
            iterable = effects.items()
        elif isinstance(effects, list):
            iterable = enumerate(effects, start=1)
        else:
            iterable = [(1, effects)]
        for slot, effect in iterable:
            if isinstance(effect, dict):
                label = _first(effect, "description", "text", "name", "effect")
                if label:
                    lines.append(f"    • Slot {slot}: {label}")
                else:
                    compact = ", ".join(f"{k}={v}" for k, v in effect.items() if v not in (None, "", 0, []))
                    lines.append(f"    • Slot {slot}: {compact or effect}")
            else:
                lines.append(f"    • Slot {slot}: {effect}")

    description = _first(data, "description", "spellDescription", "spell_description")
    if description:
        lines.extend(["", "Description:", str(description)])

    messages = _first(data, "messages", "castMessages", "cast_messages")
    if messages:
        lines.extend(["", "Cast messages:"])
        if isinstance(messages, dict):
            for key, value in messages.items():
                if value:
                    lines.append(f"  {key}: {value}")
        else:
            lines.append(str(messages))

    stacking = _first(data, "stacking", "stackingGroup", "stacking_group")
    if stacking:
        lines.extend(["", "Stacking:"])
        if isinstance(stacking, dict):
            for key, value in stacking.items():
                if value not in (None, ""):
                    lines.append(f"  {key}: {value}")
        else:
            lines.append(f"  {stacking}")
    return lines


def _render_local_detail(db: Database, entity_id: int, kind: str) -> list[str]:
    row = db.entity_detail(entity_id)
    if row is None:
        return []
    fmt = str(row["detail_format"] or "text")
    raw_json = str(row["detail_json"] or "{}")
    data = None
    if raw_json and raw_json != "{}":
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            data = None
    if kind == "spell" and isinstance(data, dict):
        return _render_spell_detail(data)

    text = str(row["detail_text"] or "").strip()
    if not text:
        return []
    title = "Installed EverQuest client detail"
    if fmt == "markdown":
        title += " (via everquest1-mcp)"
    return ["", title + ":", text]


def entity_detail_text(db: Database, entity_id: int, *, include_source_text: bool = False) -> str:
    r = db.entity(entity_id)
    if not r:
        return "Entity not found."

    lines = [
        r["name"],
        f"Type: {r['kind']}",
    ]
    if r["kind"] != "zone":
        lines.append(f"Zone: {r['zone'] or 'unknown/not parsed'}")
    if r["level_min"] is not None or r["level_max"] is not None:
        lines.append(f"Level: {r['level_min'] if r['level_min'] is not None else '?'} - {r['level_max'] if r['level_max'] is not None else '?'}")
    lines += [
        f"Primary source: {r['source_url'] or 'none'}",
        f"External ID: {r['external_id'] or 'none'}",
    ]

    ext_ids = db.external_ids_for_entity(entity_id)
    if ext_ids:
        lines.append("External identities: " + ", ".join(f"{x['namespace']}={x['external_id']}" for x in ext_ids))

    sources = db.sources_for_entity(entity_id)
    if sources:
        lines += ["", "Provenance:"]
        seen = set()
        for src in sources:
            key = (src["source_name"], src["url"], src["role"])
            if key in seen:
                continue
            seen.add(key)
            location = src["local_path"] or src["url"]
            lines.append(f"  • {src['source_name']} [{src['role']}] — {location}")

    aliases = [a["alias"] for a in db.aliases_for_entity(entity_id) if a["alias"] != r["name"]]
    if aliases:
        lines.append("Aliases: " + ", ".join(dict.fromkeys(aliases)))

    if r["notes"]:
        lines += ["", r["notes"]]

    try:
        data = json.loads(r["data_json"] or "{}")
    except json.JSONDecodeError:
        data = {}
    useful = [
        ("Quest type", data.get("quest_type")),
        ("Repeatable", data.get("repeatable")),
        ("Group size", data.get("group_size")),
    ]
    if r["kind"] == "npc":
        useful += [
            ("NPC type", data.get("npc_type")),
            ("Expansion", data.get("expansion")),
        ]
    elif r["kind"] == "item":
        useful += [
            ("Item type", data.get("item_type")),
            ("Required level", data.get("required_level")),
            ("Recommended level", data.get("recommended_level")),
            ("Stackable", data.get("stackable")),
            ("Merchant value", data.get("merchant_value")),
            ("Item lore", data.get("item_lore")),
        ]
    elif r["kind"] == "zone":
        useful += [
            ("Zone type", data.get("zone_type")),
            ("Expansion", data.get("expansion")),
            ("Instanced", data.get("instanced")),
            ("Keyed", data.get("keyed")),
            ("Hot zone", "Yes" if data.get("hot_zone") else "No" if "hot_zone" in data else None),
        ]
    for label, value in useful:
        if value is not None and value != "":
            lines.append(f"{label}: {value}")
    if r["kind"] == "item":
        for label, key in (("Slots", "slots"), ("Classes", "classes"), ("Races", "races"), ("Flags", "flags")):
            values = data.get(key) or []
            if values:
                lines.append(f"{label}: " + ", ".join(str(v) for v in values))
    for label, key in (("Factions raised", "factions_raised"), ("Factions lowered", "factions_lowered")):
        values = data.get(key) or []
        if values:
            lines.append(f"{label}: " + ", ".join(values))

    lines.extend(_render_local_detail(db, entity_id, str(r["kind"])))

    locs = db.locations_for_entity(entity_id)
    if locs:
        lines += ["", "Locations:"]
        for loc in locs:
            coords = []
            if loc["y"] is not None:
                coords.append(f"Y {loc['y']:g}")
            if loc["x"] is not None:
                coords.append(f"X {loc['x']:g}")
            if loc["z"] is not None:
                coords.append(f"Z {loc['z']:g}")
            where = loc["zone_name"] or "unknown zone"
            suffix = f" ({loc['label']})" if loc["label"] else ""
            lines.append(f"  • {where}: {', '.join(coords) if coords else 'coordinates unknown'}{suffix}")

    rels = db.relationships_for_entity(entity_id)
    if rels:
        lines += ["", "Relationships:"]
        for rel in rels:
            if rel["direction"] == "out":
                other = f"[{rel['target_kind']}] {rel['target_name']}"
                arrow = "→"
            else:
                other = f"[{rel['source_kind']}] {rel['source_name']}"
                arrow = "←"
            qty = f" x{rel['quantity']}" if rel["quantity"] is not None else ""
            lines.append(f"  • {relation_label(rel['relation'])}{qty} {arrow} {other}")

    if r["kind"] == "quest":
        steps = db.quest_steps(entity_id)
        if steps:
            lines += ["", "Steps:"]
            for s in steps:
                mark = "✓" if int(s["complete"]) else "•"
                try:
                    rule = json.loads(s["match_json"] or "{}")
                except json.JSONDecodeError:
                    rule = {}
                count = max(1, int(rule.get("count", 1)))
                progress = int(s["progress_count"])
                progress_text = f" [{progress}/{count}]" if count > 1 else (" [done]" if int(s["complete"]) else "")
                lines.append(f"  {mark} {s['step_order']}. {s['description']}{progress_text}")

    if include_source_text and r["source_text"]:
        lines += ["", "--- Primary source text snapshot ---", r["source_text"][:20000]]

    return "\n".join(lines)


def where_text(db: Database, entity_id: int, current_zone: str | None = None) -> str:
    r = db.entity(entity_id)
    if not r:
        return "Entity not found."

    lines = [f"WHERE | [{r['kind']}] {r['name']}"]
    locs = db.locations_for_entity(entity_id)

    if r["kind"] == "zone":
        lines.append(f"Zone: {r['name']}")
        for target in db.relationship_targets(entity_id, "connected_to"):
            try:
                rel_data = json.loads(target["relationship_data_json"] or "{}")
            except json.JSONDecodeError:
                rel_data = {}
            direction = rel_data.get("direction")
            lines.append(
                f"Connects: {target['name']}" + (f" | {direction}" if direction else "")
            )
    elif r["zone"]:
        lines.append(f"Zone: {r['zone']}")

    for loc in locs:
        coords = []
        if loc["y"] is not None:
            coords.append(f"Y={loc['y']:g}")
        if loc["x"] is not None:
            coords.append(f"X={loc['x']:g}")
        if loc["z"] is not None:
            coords.append(f"Z={loc['z']:g}")
        lines.append(
            f"{loc['zone_name'] or 'unknown zone'} | {' '.join(coords) if coords else 'location known'}"
            + (f" | {loc['label']}" if loc["label"] else "")
        )

    if r["kind"] == "item":
        for relation in ("drops_from", "turn_in_to"):
            for target in db.relationship_targets(entity_id, relation):
                label = relation_label(relation)
                target_locs = list(db.locations_for_entity(int(target["id"])))
                preferred_label = "quest target" if relation == "drops_from" else "turn-in"
                preferred = [loc for loc in target_locs if loc["label"] == preferred_label]
                if preferred:
                    target_locs = preferred
                if target_locs:
                    for loc in target_locs:
                        coords = []
                        if loc["y"] is not None:
                            coords.append(f"Y={loc['y']:g}")
                        if loc["x"] is not None:
                            coords.append(f"X={loc['x']:g}")
                        coord_text = f" | {' '.join(coords)}" if coords else ""
                        lines.append(
                            f"{label}: {target['name']} | {loc['zone_name'] or 'unknown zone'}{coord_text}"
                        )
                else:
                    try:
                        rel_data = json.loads(target["relationship_data_json"] or "{}")
                    except json.JSONDecodeError:
                        rel_data = {}
                    zone = rel_data.get("zone")
                    lines.append(f"{label}: {target['name']}" + (f" | {zone}" if zone else ""))

        direct_zones = [z["name"] for z in db.relationship_targets(entity_id, "found_in")]
        if direct_zones:
            lines.append("Found in zones: " + ", ".join(dict.fromkeys(direct_zones)))

    if r["kind"] == "quest":
        for starter in db.relationship_targets(entity_id, "started_by"):
            starter_locs = list(db.locations_for_entity(int(starter["id"])))
            preferred = [loc for loc in starter_locs if loc["label"] == "quest starter"]
            if preferred:
                starter_locs = preferred
            for loc in starter_locs:
                coords = []
                if loc["y"] is not None:
                    coords.append(f"Y={loc['y']:g}")
                if loc["x"] is not None:
                    coords.append(f"X={loc['x']:g}")
                lines.append(
                    f"Starter: {starter['name']} | {loc['zone_name'] or 'unknown zone'} | {' '.join(coords)}"
                )

    if len(lines) == 1:
        rels = db.relationships_for_entity(entity_id)
        zones: list[str] = []
        for rel in rels:
            if rel["relation"] == "occurs_in":
                zone_name = rel["target_name"] if rel["direction"] == "out" else rel["source_name"]
                zones.append(zone_name)
        if zones:
            lines.append("Related zone: " + ", ".join(dict.fromkeys(zones)))
        else:
            lines.append("No imported location is known yet.")

    if current_zone:
        lines.append(f"Current zone: {current_zone}")

    return "\n".join(lines)


def find_text(db: Database, term: str, limit: int = 8) -> str:
    rows = db.search_entities(term)
    if not rows:
        return f"FIND | no local match: {term}"
    lines = [f"FIND | {term} | {len(rows)} match(es)"]
    for row in rows[:limit]:
        extra = f" | {row['zone']}" if row["zone"] else ""
        lines.append(f"[{row['kind']}] {row['name']}{extra}")
    if len(rows) > limit:
        lines.append(f"...and {len(rows) - limit} more")
    return "\n".join(lines)
