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


@dataclass(frozen=True, slots=True)
class ZoneProfileDecision:
    zone_entity_id: int
    zone_name: str
    profile_id: str
    allowed: bool
    status: str
    reason: str
    expansions: tuple[str, ...] = ()


WORLD_PROFILES: tuple[WorldProfile, ...] = (
    WorldProfile(
        "live",
        "Live (default)",
        "Current Live routing. Historical/retired identities remain searchable but are excluded from normal routes.",
    ),
    WorldProfile(
        "p99",
        "Classic / P99-style (Velious cap)",
        "Classic-through-Velious routing using compiled expansion evidence plus reviewed era overrides.",
    ),
    WorldProfile(
        "unrestricted",
        "Unrestricted / custom",
        "All confirmed compiled topology, including historical and modern eras. Intended for diagnostics/custom servers.",
    ),
)

_PROFILE_BY_ID = {profile.profile_id: profile for profile in WORLD_PROFILES}

# Keep historical knowledge in the shared DB. These are runtime availability rules,
# not deletion/identity rules. Expand this reviewed set as lifecycle evidence is added.
_LIVE_EXCLUDED_NAMES = {
    normalize_name("North Freeport"),
}

# A P99-style profile deliberately re-enables historical classic identities while
# excluding modern universal hubs even if source expansion metadata is incomplete.
_P99_FORCE_ALLOW_NAMES = {
    normalize_name("North Freeport"),
}
_P99_FORCE_DENY_NAMES = {
    normalize_name("The Plane of Knowledge"),
    normalize_name("Plane of Knowledge"),
    normalize_name("Guild Lobby"),
    normalize_name("Guild Hall"),
}

# Source parsers/providers sometimes preserve an explicit placeholder rather than an
# empty field. These values mean "the source did not tell us"; they must never cross
# the P99 era boundary as if they named a real post-Velious expansion.
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


def world_profile(profile_id: str | None) -> WorldProfile:
    return _PROFILE_BY_ID.get(str(profile_id or "").strip().casefold(), _PROFILE_BY_ID[DEFAULT_WORLD_PROFILE_ID])


def active_world_profile_id(db: Database) -> str:
    raw = str(db.get_meta(WORLD_PROFILE_META_KEY, DEFAULT_WORLD_PROFILE_ID) or "").strip().casefold()
    return raw if raw in _PROFILE_BY_ID else DEFAULT_WORLD_PROFILE_ID


def set_active_world_profile(db: Database, profile_id: str) -> WorldProfile:
    profile = world_profile(profile_id)
    db.set_meta(WORLD_PROFILE_META_KEY, profile.profile_id)
    return profile


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


def p99_expansion_allowed(expansion: str) -> bool | None:
    """Classify explicit source expansion text against the P99 Velious-era cap.

    ``None`` means the source string is empty or explicitly marks the expansion as
    unknown/unavailable. The helper is intentionally shared by zone routing and entity
    lifecycle projection so both surfaces apply the same reviewed era boundary instead
    of growing separate expansion parsers.
    """
    text = normalize_name(expansion)
    if not text or text in _EXPANSION_UNKNOWN_MARKERS:
        return None
    if "kunark" in text or "velious" in text:
        return True
    if text in {
        "everquest",
        "classic",
        "classic everquest",
        "original",
        "original everquest",
        "everquest classic",
    }:
        return True
    return False


# Backward-compatible private spelling for older internal/tests while new entity
# lifecycle code consumes the public shared helper above.
def _p99_expansion_allowed(expansion: str) -> bool | None:
    return p99_expansion_allowed(expansion)


def zone_profile_decisions(db: Database, profile_id: str | None = None) -> dict[int, ZoneProfileDecision]:
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
        zone_expansions = tuple(sorted(expansions.get(zone_id, set()), key=str.casefold))

        if profile.profile_id == "unrestricted":
            decision = ZoneProfileDecision(
                zone_id, name, profile.profile_id, True, "available", "unrestricted confirmed knowledge", zone_expansions
            )
        elif profile.profile_id == "live":
            if normalized in _LIVE_EXCLUDED_NAMES:
                decision = ZoneProfileDecision(
                    zone_id,
                    name,
                    profile.profile_id,
                    False,
                    "historical",
                    "historical/retired identity is not active in the default Live profile",
                    zone_expansions,
                )
            else:
                decision = ZoneProfileDecision(
                    zone_id, name, profile.profile_id, True, "available", "available in the Live profile", zone_expansions
                )
        else:  # p99
            if normalized in _P99_FORCE_ALLOW_NAMES:
                decision = ZoneProfileDecision(
                    zone_id,
                    name,
                    profile.profile_id,
                    True,
                    "available_override",
                    "reviewed classic-era identity explicitly enabled for the P99-style profile",
                    zone_expansions,
                )
            elif normalized in _P99_FORCE_DENY_NAMES:
                decision = ZoneProfileDecision(
                    zone_id,
                    name,
                    profile.profile_id,
                    False,
                    "post_velious_override",
                    "modern travel hub explicitly excluded from the P99-style profile",
                    zone_expansions,
                )
            else:
                classified = [p99_expansion_allowed(value) for value in zone_expansions]
                known = [value for value in classified if value is not None]
                if any(value is True for value in known):
                    decision = ZoneProfileDecision(
                        zone_id,
                        name,
                        profile.profile_id,
                        True,
                        "available",
                        "compiled expansion evidence places this zone at or before Velious",
                        zone_expansions,
                    )
                elif known and all(value is False for value in known):
                    decision = ZoneProfileDecision(
                        zone_id,
                        name,
                        profile.profile_id,
                        False,
                        "post_velious",
                        "compiled expansion evidence places this zone after Velious",
                        zone_expansions,
                    )
                else:
                    # Preserve utility on incomplete historical metadata. Unknown is not
                    # promoted into a factual era statement; it is merely left routeable
                    # until the builder compiles stronger lifecycle evidence.
                    decision = ZoneProfileDecision(
                        zone_id,
                        name,
                        profile.profile_id,
                        True,
                        "era_unknown",
                        "no compiled expansion fact proves this zone is post-Velious",
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
    return ZoneProfileDecision(
        zone_id,
        name,
        profile.profile_id,
        profile.profile_id == "unrestricted",
        "non_client_identity",
        (
            "non-client zone identities are available only to unrestricted/custom routing"
            if profile.profile_id != "unrestricted"
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
    if profile.profile_id == "unrestricted":
        return ZoneTravelCatalog(db).shortest_path(source, target, max_hops=max_hops)

    decisions = zone_profile_decisions(db, profile.profile_id)
    if not decisions.get(source, ZoneProfileDecision(source, "", profile.profile_id, False, "", "")).allowed:
        return []
    if not decisions.get(target, ZoneProfileDecision(target, "", profile.profile_id, False, "", "")).allowed:
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
        if a_decision is None or b_decision is None or not a_decision.allowed or not b_decision.allowed:
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
        return TravelRouteResult(base.ok, base.source_entity_id, base.target_entity_id, base.path, f"{prefix}\n\n{base.text}")

    source_decision = zone_profile_decision(db, base.source_entity_id, profile.profile_id)
    target_decision = zone_profile_decision(db, base.target_entity_id, profile.profile_id)
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

    path = tuple(shortest_path_for_profile(db, base.source_entity_id, base.target_entity_id, profile.profile_id))
    if not path:
        unrestricted = tuple(ZoneTravelCatalog(db).shortest_path(base.source_entity_id, base.target_entity_id))
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
                detail += " Blocked on the unrestricted shortest path: " + ", ".join(blocked_names[:8]) + "."
        else:
            detail = "No confirmed route exists in the compiled travel graph for these endpoints."
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
