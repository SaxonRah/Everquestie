from __future__ import annotations

from .profile_availability import entity_profile_lines
from .spell_stacking_context import spell_stacking_text


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
