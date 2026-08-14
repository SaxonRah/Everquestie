from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .db import Database
from .map_resolution import resolve_catalog_map_for_zone
from .runtime_zone_identity import resolve_runtime_zone


@dataclass(frozen=True, slots=True)
class LocalMapReadiness:
    zone_token: str
    canonical_zone_entity_id: int | None
    canonical_zone_name: str
    status: str
    reason: str
    path: Path | None
    candidates: tuple[Path, ...]
    bound_stem: str
    hinted_stem: str

    @property
    def ready(self) -> bool:
        return self.status == "ready" and self.path is not None


def _canonical_zone_hint(db: Database, zone_token: str) -> tuple[int | None, str, str, str]:
    """Return runtime canonical identity plus packaged short-name hint without writes."""
    resolution = resolve_runtime_zone(db, zone_token, include_map_bindings=True)
    if resolution.identity is None:
        return None, "", "", resolution.status
    identity = resolution.identity
    row = db.entity(identity.entity_id)
    hint = ""
    if row is not None:
        try:
            data = json.loads(row["data_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            hint = str(data.get("map_short_name") or data.get("short_name") or "").strip()
    return identity.entity_id, identity.name, hint, resolution.status


def resolve_local_map_readiness(
    db: Database,
    zone_token: str,
    root: str | Path,
    *,
    bound_stem: str | None = None,
) -> LocalMapReadiness:
    """Project whether one live zone can be rendered from a player's local pack.

    This is a runtime/local-resource check only. It does not index map files, rebuild
    shipped bindings, or persist any player choice. ``bound_stem`` is supplied by the
    caller from user state when an explicit local override exists.

    Canonical knowledge ambiguity does not automatically block rendering. The map
    resolver may safely render shared geometry for duplicate literal zone names while
    still leaving the underlying knowledge identities distinct. Alias ambiguity remains
    a hard stop.
    """
    token = " ".join(str(zone_token or "").split()).strip()
    root_path = Path(root)
    entity_id, canonical_name, hinted_stem, identity_status = _canonical_zone_hint(db, token)

    if not root_path.is_dir():
        return LocalMapReadiness(
            zone_token=token,
            canonical_zone_entity_id=entity_id,
            canonical_zone_name=canonical_name,
            status="root_unavailable",
            reason="selected local map root does not exist",
            path=None,
            candidates=(),
            bound_stem=str(bound_stem or ""),
            hinted_stem=hinted_stem,
        )

    resolved = resolve_catalog_map_for_zone(
        db,
        token,
        root_path,
        bound_stem=str(bound_stem or "") or None,
        hinted_stem=hinted_stem or None,
    )
    if resolved.path is not None:
        return LocalMapReadiness(
            zone_token=token,
            canonical_zone_entity_id=entity_id,
            canonical_zone_name=canonical_name,
            status="ready",
            reason=resolved.reason,
            path=resolved.path,
            candidates=resolved.candidates,
            bound_stem=str(bound_stem or ""),
            hinted_stem=hinted_stem,
        )

    reason = resolved.reason
    if reason.startswith("canonical zone identity is ambiguous"):
        status = "zone_ambiguous"
    elif len(resolved.candidates) > 1:
        status = "map_ambiguous"
    elif identity_status == "ambiguous":
        status = "zone_ambiguous"
    else:
        status = "map_missing"
    return LocalMapReadiness(
        zone_token=token,
        canonical_zone_entity_id=entity_id,
        canonical_zone_name=canonical_name,
        status=status,
        reason=reason,
        path=None,
        candidates=resolved.candidates,
        bound_stem=str(bound_stem or ""),
        hinted_stem=hinted_stem,
    )


def local_map_readiness_text(readiness: LocalMapReadiness) -> str:
    zone = readiness.canonical_zone_name or readiness.zone_token or "current zone"
    if readiness.ready:
        return f"Local map ready for {zone}: {readiness.path.name} | {readiness.reason}"
    if readiness.status == "root_unavailable":
        return f"Local map unavailable for {zone}: choose a valid map pack folder."
    if readiness.status == "zone_ambiguous":
        return f"Local map unresolved for {zone}: canonical zone identity is ambiguous; EverQuestie will not guess."
    if readiness.status == "map_ambiguous":
        names = ", ".join(path.name for path in readiness.candidates[:6])
        suffix = f" ({names})" if names else ""
        return f"Local map ambiguous for {zone}: multiple canonical map variants are present{suffix}."
    return f"Local map missing for {zone}: {readiness.reason}."
