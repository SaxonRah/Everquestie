from __future__ import annotations

import re
from dataclasses import dataclass

from .events import Event


COMMAND = re.compile(
    r"^\s*(?P<verb>quest|track|unquest|untrack|find|where|zone|status)\s*:\s*(?P<arg>.*?)\s*$",
    re.IGNORECASE,
)

# Deliberately restrict commands to messages the local player sent into a
# non-public channel. Incoming group/guild messages are never executable.
CONTROL_EVENT_KINDS = {"group_out", "guild_out"}


@dataclass(slots=True)
class ControlCommand:
    verb: str
    argument: str
    raw_text: str


def parse_control_command(event: Event) -> ControlCommand | None:
    if event.kind not in CONTROL_EVENT_KINDS or not event.text:
        return None

    m = COMMAND.match(event.text)
    if not m:
        return None

    verb = m.group("verb").casefold()
    arg = m.group("arg").strip()

    aliases = {
        "track": "quest",
        "untrack": "unquest",
    }
    verb = aliases.get(verb, verb)

    # status may be written "Status:" with no argument. Others require one.
    if verb != "status" and not arg:
        return None

    return ControlCommand(verb=verb, argument=arg, raw_text=event.text)
