from __future__ import annotations

import json


_QUEST_INTERACTION_GUIDANCE_MARKER = "_everquestie_quest_interaction_guidance_ui"
_WARNING = (
    "Log automation paused: NPC speech alone does not prove this interaction completed; "
    "EverQuestie will not auto-complete this step."
)


def install_quest_interaction_guidance_ui() -> None:
    """Explain why legacy NPC-speech interaction steps fail closed.

    QuestEngine owns the mutation boundary. This layer only makes that conservative
    decision visible in Live Guidance so an imported Speak/Hail or item turn-in step does
    not look mysteriously stuck while unrelated NPC dialogue is correctly ignored.
    """
    from .quest_engine import QuestEngine

    if getattr(QuestEngine, _QUEST_INTERACTION_GUIDANCE_MARKER, False):
        return

    current_guidance = QuestEngine.guidance

    def guidance(self, current_zone):
        rows = current_guidance(self, current_zone)
        tracked = list(self.db.tracked_quests())
        for rendered, quest in zip(rows, tracked):
            active_step = int(quest["active_step"])
            pending = next(
                (
                    step
                    for step in self.db.quest_steps(int(quest["id"]))
                    if int(step["step_order"]) == active_step
                ),
                None,
            )
            if pending is None or int(pending["complete"]):
                continue
            rule = json.loads(pending["match_json"] or "{}")
            if (
                str(rule.get("event", "")).casefold() == "npc_say"
                and rule.get("verified_completion_signal") is not True
            ):
                rendered.text += "\n" + _WARNING
        return rows

    QuestEngine.guidance = guidance
    setattr(QuestEngine, _QUEST_INTERACTION_GUIDANCE_MARKER, True)
