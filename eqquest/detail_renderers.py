from __future__ import annotations

from typing import Any


_KIND_FIELDS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "aa": (
        ("ID", ("id", "aaId", "aa_id")),
        ("Category", ("category", "categoryName", "category_name")),
        ("Rank", ("rank", "currentRank", "current_rank")),
        ("Max rank", ("maxRank", "max_rank", "maxRanks")),
        ("Cost", ("cost", "pointCost", "point_cost")),
        ("Level", ("level", "requiredLevel", "required_level")),
        ("Expansion", ("expansion", "expansionName", "expansion_name")),
        ("Reuse", ("reuse", "reuseTime", "reuse_time")),
        ("Spell", ("spell", "spellName", "spell_name", "spellId", "spell_id")),
        ("Prerequisite", ("prerequisite", "prerequisites", "requires")),
        ("Classes", ("classes", "classNames", "class_names")),
    ),
    "faction": (
        ("ID", ("id", "factionId", "faction_id")),
        ("Name", ("name", "factionName", "faction_name")),
        ("Minimum", ("minimum", "min", "minValue", "min_value")),
        ("Maximum", ("maximum", "max", "maxValue", "max_value")),
        ("Default", ("default", "base", "baseValue", "base_value")),
        ("Expansion", ("expansion", "expansionName", "expansion_name")),
        ("Modifiers", ("modifiers", "mods", "adjustments")),
    ),
    "achievement": (
        ("ID", ("id", "achievementId", "achievement_id")),
        ("Category", ("category", "categoryName", "category_name")),
        ("Subcategory", ("subcategory", "subCategory", "subcategoryName")),
        ("Points", ("points", "pointValue", "point_value")),
        ("Expansion", ("expansion", "expansionName", "expansion_name")),
        ("Requirements", ("requirements", "tasks", "objectives")),
        ("Rewards", ("rewards", "reward")),
    ),
    "mercenary": (
        ("ID", ("id", "mercenaryId", "mercenary_id")),
        ("Type", ("type", "mercenaryType", "mercenary_type")),
        ("Class", ("class", "className", "class_name")),
        ("Race", ("race", "raceName", "race_name")),
        ("Tier", ("tier", "rank")),
        ("Level", ("level", "requiredLevel", "required_level")),
        ("Stance", ("stance", "stances")),
        ("Expansion", ("expansion", "expansionName", "expansion_name")),
    ),
    "overseer_agent": (
        ("ID", ("id", "agentId", "agent_id")),
        ("Rarity", ("rarity", "quality")),
        ("Job", ("job", "jobName", "job_name")),
        ("Race", ("race", "raceName", "race_name")),
        ("Class", ("class", "className", "class_name")),
        ("Traits", ("traits", "trait")),
        ("Stats", ("stats", "attributes")),
    ),
    "overseer_quest": (
        ("ID", ("id", "questId", "quest_id")),
        ("Category", ("category", "type", "questType", "quest_type")),
        ("Rarity", ("rarity", "quality")),
        ("Duration", ("duration", "durationSeconds", "duration_seconds")),
        ("Required jobs", ("jobs", "requiredJobs", "required_jobs")),
        ("Required agents", ("agents", "requiredAgents", "required_agents")),
        ("Rewards", ("rewards", "reward")),
    ),
    "zone": (
        ("Zone ID", ("id", "zoneId", "zone_id")),
        ("Short name", ("shortName", "short_name", "name")),
        ("Long name", ("longName", "long_name", "displayName", "display_name")),
        ("Expansion", ("expansion", "expansionName", "expansion_name")),
        ("Minimum level", ("minLevel", "min_level", "minimumLevel")),
        ("Maximum level", ("maxLevel", "max_level", "maximumLevel")),
        ("Safe point", ("safePoint", "safe_point", "safeCoordinates", "safe_coordinates")),
        ("Zone type", ("type", "zoneType", "zone_type")),
    ),
    "tribute": (
        ("ID", ("id", "tributeId", "tribute_id")),
        ("Tier", ("tier", "rank")),
        ("Favor", ("favor", "favorCost", "favor_cost", "cost")),
        ("Benefit", ("benefit", "effect", "effects")),
        ("Level", ("level", "requiredLevel", "required_level")),
    ),
    "combat_ability": (
        ("ID", ("id", "abilityId", "ability_id")),
        ("Skill", ("skill", "skillName", "skill_name")),
        ("Class", ("class", "className", "class_name", "classes")),
        ("Level", ("level", "requiredLevel", "required_level")),
        ("Endurance", ("endurance", "enduranceCost", "endurance_cost")),
        ("Reuse", ("reuse", "reuseTime", "reuse_time")),
        ("Spell", ("spell", "spellName", "spell_name", "spellId", "spell_id")),
    ),
}


def _first(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, "", [], {}):
            return data[key]
    return None


def _compact(value: Any, *, max_items: int = 12) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            items.append(f"{key}={_compact(item, max_items=5)}")
            if len(items) >= max_items:
                break
        suffix = " …" if len(value) > len(items) else ""
        return ", ".join(items) + suffix
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        shown = ", ".join(_compact(item, max_items=5) for item in seq[:max_items])
        return shown + (" …" if len(seq) > max_items else "")
    return str(value)


def render_structured_local_detail(kind: str, data: dict[str, Any]) -> list[str]:
    fields = _KIND_FIELDS.get(kind)
    if not fields:
        return []
    lines = ["", "Installed EverQuest client fields:"]
    found = 0
    for label, keys in fields:
        value = _first(data, keys)
        if value is None:
            continue
        found += 1
        lines.append(f"  {label}: {_compact(value)}")
    if not found:
        return []

    # Common descriptive fields are useful for nearly every rich local record.
    description = _first(data, ("description", "text", "details", "summary"))
    if description is not None:
        lines.extend(["", "Description:", _compact(description, max_items=20)])
    return lines
