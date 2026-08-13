from __future__ import annotations

import re
from datetime import datetime

from .events import Event


STAMP = re.compile(
    r"^\[(?P<stamp>[A-Z][a-z]{2} [A-Z][a-z]{2}\s+\d{1,2} "
    r"\d{2}:\d{2}:\d{2} \d{4})\]\s*(?P<body>.*)$"
)

# P1999 / classic-style chat forms plus common Live-style variants.
# Only outgoing private-channel messages are later eligible as EverQuestie commands.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("welcome", re.compile(r"^Welcome to EverQuest!$")),
    ("help", re.compile(r'^If you need help, .+$')),
    ("zone", re.compile(r"^You have entered (?P<zone>.+)\.$")),

    # Modern task-system messages. These let imported Allakhazam task objectives
    # advance without scraping memory or the quest window.
    ("task_assigned", re.compile(r"^You have been assigned the task '(?P<text>.+?)'\.$")),
    ("task_update", re.compile(r"^Your task '(?P<text>.+?)' has been updated\.$")),

    # Private/local chat.  P1999 logs /g as "You tell your party".
    ("group_out", re.compile(r"^You tell (?:your party|the group), '(?P<text>.*)'$")),
    ("group_in", re.compile(r"^(?P<actor>.+?) tells (?:the group|your party), '(?P<text>.*)'$")),
    ("guild_out", re.compile(r"^You (?:tell the guild|say to your guild), '(?P<text>.*)'$")),
    ("guild_in", re.compile(r"^(?P<actor>.+?) tells the guild, '(?P<text>.*)'$")),
    ("tell_in", re.compile(r"^(?P<actor>.+?) tells you, '(?P<text>.*)'$")),
    ("tell_out", re.compile(r"^You told (?P<target>.+?), '(?P<text>.*)'$")),
    ("say", re.compile(r"^You say, '(?P<text>.*)'$")),
    ("npc_say", re.compile(r"^(?P<actor>.+?) says, '(?P<text>.*)'$")),

    ("target_npc", re.compile(r"^Targeted \(NPC\): (?P<target>.+)$")),
    ("target_player", re.compile(r"^Targeted \(Player\): (?P<target>.+)$")),
    ("consider", re.compile(
        r"^(?P<target>.+?) (?:scowls at you, ready to attack|"
        r"glares at you threateningly|"
        r"glowers at you dubiously|"
        r"regards you indifferently|"
        r"judges you amiably|"
        r"kindly considers you|"
        r"looks upon you warmly|"
        r"could NOT possibly get any better)"
        r"(?: -- .*?)?(?: \(Lvl: (?P<level>\d+)\))?[.!]?$",
        re.IGNORECASE,
    )),

    # Live can include the source corpse in the loot line; keep it out of the
    # item name so relationship/objective matching sees exactly "Bog Bark".
    ("loot", re.compile(
        r"^--You have looted (?:a |an )?(?P<item>.+?)(?: from (?P<actor>.+?)'s corpse)?\.--$"
    )),
    # Also retain the simpler form used by some clients/configurations.
    ("loot", re.compile(r"^You have looted (?P<item>.+?)\.$")),

    ("death", re.compile(r"^You have been slain by (?P<actor>.+?)!$")),
    ("kill", re.compile(r"^(?P<actor>.+?) (?:has been|was) slain by (?P<target>.+?)!$")),
    ("kill_you", re.compile(r"^You have slain (?P<target>.+?)!$")),

    ("level_gain", re.compile(
        r"^You have gained a level! Welcome to level (?P<level>\d+)!$"
    )),
    ("level_loss", re.compile(
        r"^You LOST a level! You are now level (?P<level>\d+)!$"
    )),

    ("faction_up", re.compile(
        r"^Your faction standing with (?P<target>.+?) got better\.$"
    )),
    ("faction_down", re.compile(
        r"^Your faction standing with (?P<target>.+?) got worse\.$"
    )),
    ("xp", re.compile(r"^You gain experience(?:!!|!)?$")),
    ("xp", re.compile(r"^You gain party experience! \((?P<percent>\d+(?:\.\d+)?)%\)$")),
    ("cast", re.compile(r"^You begin casting (?P<text>.+?)\.$")),
    ("loc", re.compile(
        r"^Your Location is (?P<y>-?\d+(?:\.\d+)?),\s*"
        r"(?P<x>-?\d+(?:\.\d+)?),\s*"
        r"(?P<z>-?\d+(?:\.\d+)?)"
    )),
]

# Money text is intentionally permissive because P1999 uses many punctuation forms:
#   1 silver and 12 copper
#   1 platinum, 1 gold, 1 silver and 9 copper
#   5 platinum 5 gold 3 copper
MONEY_PART = re.compile(
    r"(?P<amount>\d+)\s+(?P<denom>platinum|gold|silver|copper)",
    re.IGNORECASE,
)
MERCHANT_RECEIVE = re.compile(
    r"^You receive (?P<money>.+?) from (?P<actor>.+?) for the (?P<item>.+?)\(s\)\.$"
)
CORPSE_RECEIVE = re.compile(
    r"^You receive (?P<money>.+?) from the corpse\.$"
)
SPLIT_RECEIVE = re.compile(
    r"^You receive (?P<money>.+?) as your split\.$"
)


def _timestamp(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp, "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None


def _money_fields(text: str) -> dict[str, int] | None:
    fields = {"pp": 0, "gp": 0, "sp": 0, "cp": 0}
    key = {
        "platinum": "pp",
        "gold": "gp",
        "silver": "sp",
        "copper": "cp",
    }
    matches = list(MONEY_PART.finditer(text))
    if not matches:
        return None
    for m in matches:
        fields[key[m.group("denom").casefold()]] = int(m.group("amount"))
    return fields


class EQLogParser:
    def parse_line(self, raw_line: str) -> Event | None:
        line = raw_line.rstrip("\r\n")
        if not line:
            return None

        stamp = None
        body = line

        m = STAMP.match(line)
        if m:
            stamp = _timestamp(m.group("stamp"))
            body = m.group("body")

        # Merchant sales are useful economically and for identifying nearby NPCs/items.
        mm = MERCHANT_RECEIVE.match(body)
        if mm:
            money = _money_fields(mm.group("money"))
            if money:
                return Event(
                    kind="merchant_sale",
                    raw=line,
                    timestamp=stamp,
                    actor=mm.group("actor"),
                    item=mm.group("item"),
                    fields=money,
                )

        cm = CORPSE_RECEIVE.match(body)
        if cm:
            money = _money_fields(cm.group("money"))
            if money:
                money["source"] = "corpse"
                return Event(kind="coin", raw=line, timestamp=stamp, fields=money)

        sm = SPLIT_RECEIVE.match(body)
        if sm:
            money = _money_fields(sm.group("money"))
            if money:
                money["source"] = "split"
                return Event(kind="coin", raw=line, timestamp=stamp, fields=money)

        for kind, rx in PATTERNS:
            pm = rx.match(body)
            if not pm:
                continue

            gd = pm.groupdict()
            event = Event(
                kind=kind,
                raw=line,
                timestamp=stamp,
                actor=gd.get("actor"),
                target=gd.get("target"),
                text=gd.get("text"),
                zone=gd.get("zone"),
                item=gd.get("item"),
            )

            if kind == "loc":
                event.fields = {
                    "x": float(gd["x"]),
                    "y": float(gd["y"]),
                    "z": float(gd["z"]),
                }
            elif kind in {"level_gain", "level_loss"}:
                event.fields = {"level": int(gd["level"])}
            elif kind == "consider" and gd.get("level"):
                event.fields = {"level": int(gd["level"])}
            elif kind == "xp" and gd.get("percent"):
                event.fields = {"percent": float(gd["percent"])}

            if kind == "kill_you":
                event.kind = "kill"
                event.actor = event.target
                event.target = "You"

            return event

        return Event(kind="other", raw=line, timestamp=stamp, text=body)
