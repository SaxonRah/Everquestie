from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .db import Database
from .eqmap import player_map_binding_value
from .local_map_readiness import LocalMapReadiness, resolve_local_map_readiness


@dataclass(frozen=True, slots=True)
class LocalMapVariantResult:
    ok: bool
    status: str
    reason: str
    selected_path: Path | None
    readiness: LocalMapReadiness


def current_local_map_variants(
    db: Database,
    zone_token: str,
    root: str | Path,
) -> tuple[LocalMapReadiness, tuple[Path, ...]]:
    """Return the current canonical local candidate set without applying user binding.

    A packaged canonical short-name hint may select one candidate, but ``candidates``
    still contains the complete canonical set present in the selected local map root.
    Explicit player binding is intentionally omitted so a stale/previous choice cannot
    define which paths are allowed for the next choice.
    """
    readiness = resolve_local_map_readiness(db, zone_token, root, bound_stem=None)
    return readiness, tuple(readiness.candidates)


def bind_local_map_variant(
    db: Database,
    zone_token: str,
    root: str | Path,
    selected_path: str | Path,
    *,
    binding_key: str,
) -> LocalMapVariantResult:
    """Persist one explicitly chosen canonical local map variant safely.

    The candidate set is recomputed at apply time. Only an exact current candidate may
    be persisted, which rejects arbitrary paths and stale dialog choices after a zone,
    map-root, or local-file change. A direct single-pack choice retains the historic
    stem-only value; a nested collection-root choice stores only a portable root-relative
    file key. The write goes through ``db.set_meta`` so packaged ``RuntimeDatabase``
    routes it to the separate player-state DB.
    """
    readiness, candidates = current_local_map_variants(db, zone_token, root)
    if readiness.status == "zone_ambiguous":
        return LocalMapVariantResult(
            False,
            "zone_ambiguous",
            "canonical zone identity is ambiguous",
            None,
            readiness,
        )
    if not candidates:
        return LocalMapVariantResult(
            False,
            "no_candidates",
            "no current canonical local map candidates are available",
            None,
            readiness,
        )

    selected = Path(selected_path).expanduser().resolve()
    by_resolved = {candidate.expanduser().resolve(): candidate for candidate in candidates}
    chosen = by_resolved.get(selected)
    if chosen is None:
        return LocalMapVariantResult(
            False,
            "not_candidate",
            "selected path is not in the current canonical local candidate set",
            None,
            readiness,
        )

    key = str(binding_key or "").strip()
    if not key.startswith("map_binding::"):
        return LocalMapVariantResult(
            False,
            "invalid_binding_key",
            "local map variant binding key is not player map-binding metadata",
            None,
            readiness,
        )

    try:
        binding_value = player_map_binding_value(root, chosen)
    except ValueError:
        return LocalMapVariantResult(
            False,
            "outside_root",
            "selected path is not inside the current local map root",
            None,
            readiness,
        )

    db.set_meta(key, binding_value)
    verified = resolve_local_map_readiness(
        db,
        zone_token,
        root,
        bound_stem=binding_value,
    )
    if not verified.ready or verified.path is None or verified.path.resolve() != chosen.resolve():
        return LocalMapVariantResult(
            False,
            "verification_failed",
            "persisted user map binding did not re-resolve to the selected candidate",
            chosen,
            verified,
        )
    return LocalMapVariantResult(
        True,
        "bound",
        verified.reason,
        chosen,
        verified,
    )
