from __future__ import annotations

from .profile_availability import entity_profile_lines
from .spell_stacking_context import spell_stacking_text
from .world_profiles import active_world_profile_id, world_profile


def mechanics_profile_source_notice(db) -> str:
    """Explain how the selected server profile relates to compiled client mechanics.

    Class/level tables are exact source facts from the EverQuest client used by the
    knowledge builder. A gameplay profile changes availability/routing policy; it does
    not rewrite those support tables into another server's ruleset. Keep that boundary
    visible so selecting P99/custom cannot make Live-client caps or formulas look like
    profile-specific mechanics.
    """

    profile = world_profile(active_world_profile_id(db))
    if profile.profile_id == "live":
        return (
            f"Gameplay profile: {profile.label}. Class/level mechanics below are "
            "compiled from exact installed Live-client support files."
        )
    return (
        f"Gameplay profile: {profile.label}. Class/level mechanics below are compiled "
        "from installed Live-client support files, not a profile-specific ruleset. "
        "EverQuestie does not reinterpret Live-client caps, base stats, AC formulas, "
        "or skill progression as mechanics for this server profile."
    )


def profiled_spell_stacking_text(db, entity_id: int) -> str:
    """Render canonical spell mechanics plus the active gameplay-profile projection.

    Stacking/mechanics remains owned by :mod:`spell_stacking_context`; lifecycle/profile
    truth remains owned by :mod:`profile_availability`.  This function only composes the
    two read-only projections for the Mechanics tab so selecting a spell there cannot
    disagree with the same entity in Knowledge.
    """

    mechanics = spell_stacking_text(db, int(entity_id)).rstrip()
    profile = "\n".join(entity_profile_lines(db, int(entity_id)))
    if not mechanics:
        return profile.lstrip("\n")
    return mechanics + "\n" + profile
