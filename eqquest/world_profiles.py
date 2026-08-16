from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import json
from typing import Any

from .db import Database, normalize_name
from .travel import TravelRouteResult, build_route_result
from .zone_travel import ZoneTravelCatalog


WORLD_PROFILE_META_KEY = "world_profile"
DEFAULT_WORLD_PROFILE_ID = "live"


@dataclass(frozen=True, slots=True)
class WorldProfile:
    profile_id: str
    label: str
    description: str
    availability_mode: str = "live"
    expansion_cap: str | None = None
    expansion_cap_label: str = ""
    excluded_zone_names: frozenset[str] = frozenset()
    excluded_zone_status: str = "historical"
    excluded_zone_reason: str = ""
    force_allow_zone_names: frozenset[str] = frozenset()
    force_allow_reason: str = ""
    force_deny_zone_names: frozenset[str] = frozenset()
    force_deny_reason: str = ""


@dataclass(frozen=True, slots=True)
class ZoneProfileDecision:
    zone_entity_id: int
    zone_name: str
    profile_id: str
    allowed: bool
    status: str
    reason: str
    expansions: tuple[str, ...] = ()


# Reviewed exact expansion aliases are normalized onto one chronological key. This is
# intentionally not a substring classifier: source fields can contain taxonomy/noise,
# while modern expansion names can themselves contain old-era words such as Kunark or
# Velious. Unknown labels remain unknown instead of being guessed into an era.
_REVIEWED_EXPANSION_ALIASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "classic",
        "EverQuest",
        (
            "EverQuest",
            "Classic",
            "Classic EverQuest",
            "Original",
            "Original EverQuest",
            "EverQuest Classic",
        ),
    ),
    ("kunark", "Kunark", ("Kunark", "The Ruins of Kunark", "Ruins of Kunark")),
    ("velious", "Velious", ("Velious", "The Scars of Velious", "Scars of Velious")),
    ("luclin", "Luclin", ("Luclin", "The Shadows of Luclin", "Shadows of Luclin")),
    ("planes_of_power", "Planes of Power", ("Power", "The Planes of Power", "Planes of Power")),
    ("legacy_of_ykesha", "Legacy of Ykesha", ("The Legacy of Ykesha", "Legacy of Ykesha", "Ykesha")),
    ("lost_dungeons_of_norrath", "Lost Dungeons of Norrath", ("Lost Dungeons of Norrath", "LDoN")),
    ("gates_of_discord", "Gates of Discord", ("Gates", "Gates of Discord")),
    ("omens_of_war", "Omens of War", ("Omens", "Omens of War")),
    ("dragons_of_norrath", "Dragons of Norrath", ("Dragons of Norrath",)),
    ("depths_of_darkhollow", "Depths of Darkhollow", ("Depths of Darkhollow",)),
    ("prophecy_of_ro", "Prophecy of Ro", ("Prophecy of Ro",)),
    ("the_serpents_spine", "The Serpent's Spine", ("The Serpent's Spine",)),
    ("the_buried_sea", "The Buried Sea", ("The Buried Sea",)),
    ("secrets_of_faydwer", "Secrets of Faydwer", ("Secrets of Faydwer",)),
    ("seeds_of_destruction", "Seeds of Destruction", ("Seeds of Destruction",)),
    ("underfoot", "Underfoot", ("Underfoot",)),
    ("house_of_thule", "House of Thule", ("House of Thule",)),
    ("veil_of_alaris", "Veil of Alaris", ("Veil of Alaris",)),
    ("rain_of_fear", "Rain of Fear", ("Rain of Fear",)),
    ("call_of_the_forsaken", "Call of the Forsaken", ("Call of the Forsaken",)),
    ("the_darkened_sea", "The Darkened Sea", ("The Darkened Sea",)),
    ("the_broken_mirror", "The Broken Mirror", ("The Broken Mirror",)),
    ("empires_of_kunark", "Empires of Kunark", ("Empires of Kunark",)),
    ("ring_of_scale", "Ring of Scale", ("Ring of Scale",)),
    ("the_burning_lands", "The Burning Lands", ("The Burning Lands",)),
    ("torment_of_velious", "Torment of Velious", ("Torment of Velious",)),
    ("claws_of_veeshan", "Claws of Veeshan", ("Claws of Veeshan",)),
    ("terror_of_luclin", "Terror of Luclin", ("Terror of Luclin",)),
    ("night_of_shadows", "Night of Shadows", ("Night of Shadows",)),
    ("laurions_song", "Laurion's Song", ("Laurion's Song",)),
    ("the_outer_brood", "The Outer Brood", ("The Outer Brood",)),
    ("shattering_of_ro", "Shattering of Ro", ("Shattering of Ro",)),
)

_EXPANSION_ORDER = {
    key: index for index, (key, _label, _aliases) in enumerate(_REVIEWED_EXPANSION_ALIASES)
}
_EXPANSION_DISPLAY = {
    key: label for key, label, _aliases in _REVIEWED_EXPANSION_ALIASES
}
_EXPANSION_KEY_BY_LABEL = {
    normalize_name(alias): key
    for key, _label, aliases in _REVIEWED_EXPANSION_ALIASES
    for alias in aliases
}

# Source parsers/providers sometimes preserve an explicit placeholder rather than an
# empty field. These values mean "the source did not tell us" and never cross a profile
# expansion boundary as if they named a real expansion.
_EXPANSION_UNKNOWN_MARKERS = {
    "?",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "unspecified",
    "not specified",
    "not available",
    "tbd",
}


WORLD_PROFILES: tuple[WorldProfile, ...] = (
    WorldProfile(
        "live",
        "Live (default)",
        "Current Live routing. Historical/retired identities remain searchable but are excluded from normal routes.",
        availability_mode="live",
        excluded_zone_names=frozenset({normalize_name("North Freeport")}),
        excluded_zone_status="historical",
        excluded_zone_reason="historical/retired identity is not active in the default Live profile",
    ),
    WorldProfile(
        "p99",
        "Classic / P99-style (Velious cap)",
        "Classic-through-Velious routing using compiled expansion evidence plus reviewed era overrides.",
        availability_mode="expansion_cap",
        expansion_cap="velious",
        expansion_cap_label="Velious",
        force_allow_zone_names=frozenset({normalize_name("North Freeport")}),
        force_allow_reason="reviewed classic-era identity explicitly enabled for the P99-style profile",
        force_deny_zone_names=frozenset(
            {
                normalize_name("The Plane of Knowledge"),
                normalize_name("Plane of Knowledge"),
                normalize_name("Guild Lobby"),
                normalize_name("Guild Hall"),
            }
        ),
        force_deny_reason="modern travel hub explicitly excluded from the P99-style profile",
    ),
    WorldProfile(
        "unrestricted",
        "Unrestricted / custom",
        "All confirmed compiled topology, including historical and modern eras. Intended for diagnostics/custom servers.",
        availability_mode="unrestricted",
    ),
)

_PROFILE_BY_ID = {profile.profile_id: profile for profile in WORLD_PROFILES}


def world_profile(profile_id: str | None) -> WorldProfile:
    return _PROFILE_BY_ID.get(
        str(profile_id or "").strip().casefold(),
        _PROFILE_BY_ID[DEFAULT_WORLD_PROFILE_ID],
    )


def active_world_profile_id(db: Database) -> str:
    raw = str(
        db.get_meta(WORLD_PROFILE_META_KEY, DEFAULT_WORLD_PROFILE_ID) or ""
    ).strip().casefold()
    return raw if raw in _PROFILE_BY_ID else DEFAULT_WORLD_PROFILE_ID


def set_active_world_profile(db: Database, profile_id: str) -> WorldProfile:
    profile = world_profile(profile_id)
    db.set_meta(WORLD_PROFILE_META_KEY, profile.profile_id)
    return profile


def reviewed_expansion_key(expansion: str) -> str | None:
    """Return one reviewed chronological expansion key for exact source text or key."""
    raw = str(expansion or "").strip().casefold()
    if not raw:
        return None
    # Profile definitions use stable canonical keys such as ``planes_of_power``. Check
    # that namespace before normalizing human source/display text so underscores cannot
    # be erased or reinterpreted by the general entity-name normalizer.
    if raw in _EXPANSION_ORDER:
        return raw
    text = normalize_name(raw)
    if not text or text in _EXPANSION_UNKNOWN_MARKERS:
        return None
    return _EXPANSION_KEY_BY_LABEL.get(text)


def expansion_allowed_through(expansion: str, cap_expansion: str) -> bool | None:
    """Classify reviewed expansion text against an arbitrary reviewed era cap.

    ``True`` means the source expansion is at or before the cap. ``False`` means it is
    later than the cap. ``None`` means either side is not a reviewed expansion label.
    No substring, level-range, date, or name inference is performed.
    """
    expansion_key = reviewed_expansion_key(expansion)
    cap_key = reviewed_expansion_key(cap_expansion)
    if expansion_key is None or cap_key is None:
        return None
    return _EXPANSION_ORDER[expansion_key] <= _EXPANSION_ORDER[cap_key]


def profile_expansion_allowed(profile_id: str, expansion: str) -> bool | None:
    """Classify one reviewed expansion against a profile-owned expansion cap."""
    profile = world_profile(profile_id)
    if profile.availability_mode != "expansion_cap" or not profile.expansion_cap:
        return None
    return expansion_allowed_through(expansion, profile.expansion_cap)


def p99_expansion_allowed(expansion: str) -> bool | None:
    """Backward-compatible P99 spelling backed by the generic profile cap policy."""
    return profile_expansion_allowed("p99", expansion)


# Backward-compatible private spelling for older internal/tests.
def _p99_expansion_allowed(expansion: str) -> bool | None:
    return p99_expansion_allowed(expansion)


def _profile_cap_label(profile: WorldProfile) -> str:
    if profile.expansion_cap_label:
        return profile.expansion_cap_label
    if profile.expansion_cap:
        key = reviewed_expansion_key(profile.expansion_cap)
        if key is not None:
            return _EXPANSION_DISPLAY.get(key, profile.expansion_cap)
        return profile.expansion_cap
    return "configured expansion cap"


def _post_cap_status(profile: WorldProfile, *, override: bool = False) -> str:
    cap = reviewed_expansion_key(profile.expansion_cap or "") or str(profile.expansion_cap or "cap").strip().casefold().replace("-", "_").replace(" ", "_")
    suffix = "_override" if override else ""
    return f"post_{cap}{suffix}"


def _relation_exists(db: Database, name: str) -> bool:
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


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _expansion_text(data: dict[str, Any]) -> str:
    for key in ("expansion", "expansion_name", "era"):
        value = data.get(key)
        if value is not None and str(value).strip():
            return " ".join(str(value).split())
    return ""


def zone_profile_decisions(
    db: Database,
    profile_id: str | None = None,
) -> dict[int, ZoneProfileDecision]:
    profile = world_profile(profile_id or active_world_profile_id(db))
    rows = db.conn.execute(
        """
        SELECT e.id,e.name,e.data_json
        FROM entities e
        WHERE e.kind='zone'
          AND EXISTS (
              SELECT 1 FROM entity_external_ids x
              WHERE x.entity_id=e.id AND x.namespace='eqclient:zone'
          )
        ORDER BY e.id
        """
    ).fetchall()

    expansions: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        value = _expansion_text(_json_object(row["data_json"]))
        if value:
            expansions[int(row["id"])].add(value)

    if _relation_exists(db, "zone_provider_bindings"):
        provider_rows = db.conn.execute(
            """
            SELECT b.gameplay_zone_entity_id,e.data_json
            FROM zone_provider_bindings b
            JOIN entities e ON e.id=b.provider_zone_entity_id
            WHERE b.status='linked' AND b.gameplay_zone_entity_id IS NOT NULL
            """
        ).fetchall()
        for row in provider_rows:
            value = _expansion_text(_json_object(row["data_json"]))
            if value:
                expansions[int(row["gameplay_zone_entity_id"])].add(value)

    result: dict[int, ZoneProfileDecision] = {}
    for row in rows:
        zone_id = int(row["id"])
        name = str(row["name"])
        normalized = normalize_name(name)
        zone_expansions = tuple(
            sorted(expansions.get(zone_id, set()), key=str.casefold)
        )

        if profile.availability_mode == "unrestricted":
            decision = ZoneProfileDecision(
                zone_id,
                name,
                profile.profile_id,
                True,
                "available",
                "unrestricted confirmed knowledge",
                zone_expansions,
            )
        elif profile.availability_mode == "live":
            if normalized in profile.excluded_zone_names:
                decision = ZoneProfileDecision(
                    zone_id,
                    name,
                    profile.profile_id,
                    False,
                    profile.excluded_zone_status,
                    profile.excluded_zone_reason
                    or "zone is excluded from this Live availability profile",
                    zone_expansions,
                )
            else:
                decision = ZoneProfileDecision(
                    zone_id,
                    name,
                    profile.profile_id,
                    True,
                    "available",
                    "available in the Live profile",
                    zone_expansions,
                )
        elif profile.availability_mode == "expansion_cap" and profile.expansion_cap:
            cap_label = _profile_cap_label(profile)
            if normalized in profile.force_allow_zone_names:
                decision = ZoneProfileDecision(
                    zone_id,
                    name,
                    profile.profile_id,
                    True,
                    "available_override",
                    profile.force_allow_reason
                    or f"reviewed identity explicitly enabled for the {profile.label} profile",
                    zone_expansions,
                )
            elif normalized in profile.force_deny_zone_names:
                decision = ZoneProfileDecision(
                    zone_id,
                    name,
                    profile.profile_id,
                    False,
                    _post_cap_status(profile, override=True),
                    profile.force_deny_reason
                    or f"reviewed identity explicitly excluded from the {profile.label} profile",
                    zone_expansions,
                )
            else:
                classified = [
                    profile_expansion_allowed(profile.profile_id, value)
                    for value in zone_expansions
                ]
                known = [value for value in classified if value is not None]
                if any(value is True for value in known):
                    decision = ZoneProfileDecision(
                        zone_id,
                        name,
                        profile.profile_id,
                        True,
                        "available",
                        f"compiled expansion evidence places this zone at or before {cap_label}",
                        zone_expansions,
                    )
                elif known and all(value is False for value in known):
                    decision = ZoneProfileDecision(
                        zone_id,
                        name,
                        profile.profile_id,
                        False,
                        _post_cap_status(profile),
                        f"compiled expansion evidence places this zone after {cap_label}",
                        zone_expansions,
                    )
                else:
                    # Preserve utility on incomplete historical metadata. Unknown is not
                    # promoted into a factual era statement; it remains routeable until
                    # the builder compiles stronger lifecycle evidence.
                    decision = ZoneProfileDecision(
                        zone_id,
                        name,
                        profile.profile_id,
                        True,
                        "era_unknown",
                        f"no compiled expansion fact proves this zone is post-{cap_label}",
                        zone_expansions,
                    )
        else:
            # Known profile definitions should never reach this branch. Fail closed if
            # a future profile is configured with an unsupported availability mode.
            decision = ZoneProfileDecision(
                zone_id,
                name,
                profile.profile_id,
                False,
                "profile_policy_error",
                "gameplay profile availability policy is not configured",
                zone_expansions,
            )
        result[zone_id] = decision
    return result


def zone_profile_decision(
    db: Database,
    zone_entity_id: int,
    profile_id: str | None = None,
) -> ZoneProfileDecision:
    profile = world_profile(profile_id or active_world_profile_id(db))
    decisions = zone_profile_decisions(db, profile.profile_id)
    zone_id = int(zone_entity_id)
    found = decisions.get(zone_id)
    if found is not None:
        return found
    row = db.entity(zone_id)
    name = str(row["name"]) if row is not None else f"zone {zone_id}"
    unrestricted = profile.availability_mode == "unrestricted"
    return ZoneProfileDecision(
        zone_id,
        name,
        profile.profile_id,
        unrestricted,
        "non_client_identity",
        (
            "non-client zone identities are available only to unrestricted/custom routing"
            if not unrestricted
            else "unrestricted confirmed knowledge"
        ),
        (),
    )


def shortest_path_for_profile(
    db: Database,
    source_zone_entity_id: int,
    target_zone_entity_id: int,
    profile_id: str | None = None,
    *,
    max_hops: int | None = None,
) -> list[int]:
    """Filter the one canonical compiled graph through a gameplay availability profile.

    No travel edge is created, reversed, or persisted here. The profile is a read-time
    node-availability projection over the same finalized ``zone_travel_edges`` table.
    """
    profile = world_profile(profile_id or active_world_profile_id(db))
    source = int(source_zone_entity_id)
    target = int(target_zone_entity_id)
    if profile.availability_mode == "unrestricted":
        return ZoneTravelCatalog(db).shortest_path(source, target, max_hops=max_hops)

    decisions = zone_profile_decisions(db, profile.profile_id)
    if not decisions.get(
        source,
        ZoneProfileDecision(source, "", profile.profile_id, False, "", ""),
    ).allowed:
        return []
    if not decisions.get(
        target,
        ZoneProfileDecision(target, "", profile.profile_id, False, "", ""),
    ).allowed:
        return []
    if source == target:
        return [source]

    adjacency: dict[int, set[int]] = {}
    rows = db.conn.execute(
        """
        SELECT source_zone_entity_id,target_zone_entity_id,bidirectional
        FROM zone_travel_edges
        WHERE status='linked' AND target_zone_entity_id IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        a = int(row["source_zone_entity_id"])
        b = int(row["target_zone_entity_id"])
        a_decision = decisions.get(a)
        b_decision = decisions.get(b)
        if (
            a_decision is None
            or b_decision is None
            or not a_decision.allowed
            or not b_decision.allowed
        ):
            continue
        adjacency.setdefault(a, set()).add(b)
        if bool(row["bidirectional"]):
            adjacency.setdefault(b, set()).add(a)

    hop_limit = None if max_hops is None else max(0, int(max_hops))
    queue: deque[tuple[int, list[int]]] = deque([(source, [source])])
    visited = {source}
    while queue:
        current, path = queue.popleft()
        if hop_limit is not None and len(path) - 1 >= hop_limit:
            continue
        for nxt in sorted(adjacency.get(current, set())):
            if nxt in visited:
                continue
            new_path = path + [nxt]
            if nxt == target:
                return new_path
            visited.add(nxt)
            queue.append((nxt, new_path))
    return []


def build_profiled_route_result(
    db: Database,
    source_text: str,
    target_text: str,
    profile_id: str | None = None,
) -> TravelRouteResult:
    profile = world_profile(profile_id or active_world_profile_id(db))
    base = build_route_result(db, source_text, target_text)
    prefix = f"Gameplay profile: {profile.label}"
    if base.source_entity_id is None or base.target_entity_id is None:
        return TravelRouteResult(
            base.ok,
            base.source_entity_id,
            base.target_entity_id,
            base.path,
            f"{prefix}\n\n{base.text}",
        )

    source_decision = zone_profile_decision(
        db, base.source_entity_id, profile.profile_id
    )
    target_decision = zone_profile_decision(
        db, base.target_entity_id, profile.profile_id
    )
    if not source_decision.allowed:
        return TravelRouteResult(
            False,
            base.source_entity_id,
            base.target_entity_id,
            (),
            f"{prefix}\n\n{source_decision.zone_name} is not routeable in this gameplay profile.\n"
            f"Reason: {source_decision.reason}",
        )
    if not target_decision.allowed:
        return TravelRouteResult(
            False,
            base.source_entity_id,
            base.target_entity_id,
            (),
            f"{prefix}\n\n{target_decision.zone_name} is retained as knowledge but is not routeable in this gameplay profile.\n"
            f"Reason: {target_decision.reason}",
        )

    path = tuple(
        shortest_path_for_profile(
            db,
            base.source_entity_id,
            base.target_entity_id,
            profile.profile_id,
        )
    )
    if not path:
        unrestricted = tuple(
            ZoneTravelCatalog(db).shortest_path(
                base.source_entity_id, base.target_entity_id
            )
        )
        if unrestricted:
            decisions = zone_profile_decisions(db, profile.profile_id)
            blocked_names = [
                decisions[zone_id].zone_name
                for zone_id in unrestricted
                if zone_id in decisions and not decisions[zone_id].allowed
            ]
            detail = (
                "A confirmed route exists in unrestricted knowledge, but the selected gameplay profile blocks "
                "one or more zones on that path."
            )
            if blocked_names:
                detail += (
                    " Blocked on the unrestricted shortest path: "
                    + ", ".join(blocked_names[:8])
                    + "."
                )
        else:
            detail = (
                "No confirmed route exists in the compiled travel graph for these endpoints."
            )
        return TravelRouteResult(
            False,
            base.source_entity_id,
            base.target_entity_id,
            (),
            f"{prefix}\n\nNo confirmed route is currently available from {source_decision.zone_name} to {target_decision.zone_name} under this profile.\n\n{detail}",
        )

    return TravelRouteResult(
        True,
        base.source_entity_id,
        base.target_entity_id,
        path,
        f"{prefix}\n\nConfirmed profile-compatible route found.",
    )
