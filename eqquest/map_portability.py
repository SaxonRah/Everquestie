from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
import re

from .db import Database
from .eqmap import normalize_map_name


_LEGACY_SOURCE_NAMES = {"", "legacy-local"}


@dataclass(frozen=True, slots=True)
class MapPortabilityMigration:
    normalized: int = 0
    deduplicated: int = 0


def _looks_absolute(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text) and (
        text.startswith(("/", "\\"))
        or bool(re.match(r"^[A-Za-z]:[\\/]", text))
    )


def _path_class(value: str):
    text = str(value or "")
    if bool(re.match(r"^[A-Za-z]:[\\/]", text)) or "\\" in text:
        return PureWindowsPath
    return PurePosixPath


def _basename(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _path_class(text)(text).name


def _safe_relative(value: str) -> str:
    text = str(value or "").strip()
    if not text or _looks_absolute(text):
        return ""
    path = _path_class(text)(text)
    parts = tuple(part for part in path.parts if part not in ("", "."))
    if not parts or any(part == ".." for part in parts):
        return ""
    return PurePosixPath(*parts).as_posix()


def _relative_to_root(value: str, root: str) -> str:
    raw_value = str(value or "").strip()
    raw_root = str(root or "").strip()
    if not raw_value or not raw_root or not _looks_absolute(raw_value):
        return ""
    path_cls = _path_class(raw_value)
    if path_cls is not _path_class(raw_root):
        return ""
    try:
        rel = path_cls(raw_value).relative_to(path_cls(raw_root))
    except (TypeError, ValueError):
        return ""
    return _safe_relative(rel.as_posix())


def _expected_filename(map_stem: str, layer: int) -> str:
    stem = str(map_stem or "").strip()
    suffix = "" if int(layer or 0) == 0 else f"_{int(layer)}"
    return f"{stem}{suffix}.txt" if stem else ""


def _portable_path(source_name: str, source_key: str) -> str:
    source_token = normalize_map_name(source_name) or "maps"
    return f"mapcatalog://{source_token}/{source_key}"


def _target_for_row(row) -> tuple[str, str, str]:
    source_name = " ".join(str(row["source_name"] or "").split()).strip()
    root = str(row["root"] or "").strip()
    source_key = str(row["source_key"] or "").strip()
    path = str(row["path"] or "").strip()
    map_stem = str(row["map_stem"] or "").strip()
    layer = int(row["layer"] or 0)

    if source_name.casefold() in _LEGACY_SOURCE_NAMES:
        inferred = _basename(root)
        if inferred:
            source_name = inferred
    if not source_name:
        source_name = "legacy-local"

    portable_key = _safe_relative(source_key)
    if not portable_key:
        for candidate in (source_key, path):
            portable_key = _relative_to_root(candidate, root)
            if portable_key:
                break

    if not portable_key:
        expected = _expected_filename(map_stem, layer)
        for candidate in (source_key, path):
            leaf = _basename(candidate)
            if leaf and expected and leaf.casefold() == expected.casefold():
                portable_key = leaf
                break

    if not portable_key:
        raise ValueError(
            "Cannot safely derive a portable map source key for "
            f"map_sources id {row['id']}: source_key={source_key!r}, path={path!r}, root={root!r}"
        )

    return source_name, portable_key, _portable_path(source_name, portable_key)


def _already_target(row, target: tuple[str, str, str]) -> bool:
    source_name, source_key, path = target
    return (
        str(row["source_name"] or "") == source_name
        and str(row["source_key"] or "") == source_key
        and str(row["path"] or "") == path
        and str(row["root"] or "") == source_name
    )


def normalize_legacy_map_sources(db: Database) -> MapPortabilityMigration:
    """Normalize pre-portable map catalog rows inside a release/build database.

    Older EverQuestie catalogs persisted the builder machine's absolute map path in
    ``root``, ``source_key`` and ``path``. Current catalogs use a source-relative key
    and a synthetic ``mapcatalog://`` provenance URI. This migration is deterministic
    from the row's existing root/stem/layer metadata and never needs the source map
    files to still exist.

    If a long-lived builder DB contains both an old absolute row and a newer portable
    row for the same source file, the already-portable/newer row wins. Non-conflicting
    labels are retained before the duplicate source row is removed.
    """
    table = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='map_sources'"
    ).fetchone()
    if table is None:
        return MapPortabilityMigration()

    rows = db.conn.execute(
        "SELECT id,root,source_name,source_key,map_stem,layer,path,mtime_ns,size,indexed_at "
        "FROM map_sources ORDER BY id"
    ).fetchall()
    if not rows:
        return MapPortabilityMigration()

    targets = {int(row["id"]): _target_for_row(row) for row in rows}
    by_identity: dict[tuple[str, str], list] = {}
    for row in rows:
        source_name, source_key, _path = targets[int(row["id"])]
        by_identity.setdefault((source_name, source_key), []).append(row)

    normalized = 0
    deduplicated = 0
    with db.batch():
        for _identity, group in by_identity.items():
            ranked = sorted(
                group,
                key=lambda row: (
                    1 if _already_target(row, targets[int(row["id"])]) else 0,
                    1 if str(row["path"] or "").startswith("mapcatalog://") else 0,
                    int(row["mtime_ns"] or 0),
                    str(row["indexed_at"] or ""),
                    int(row["id"]),
                ),
                reverse=True,
            )
            winner = ranked[0]
            winner_id = int(winner["id"])

            for loser in ranked[1:]:
                loser_id = int(loser["id"])
                if db.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='map_labels'"
                ).fetchone() is not None:
                    # Preserve any source lines the preferred row does not contain.
                    db.conn.execute(
                        """
                        UPDATE map_labels AS ml
                        SET source_id=?
                        WHERE ml.source_id=?
                          AND NOT EXISTS (
                              SELECT 1 FROM map_labels existing
                              WHERE existing.source_id=?
                                AND existing.source_line=ml.source_line
                          )
                        """,
                        (winner_id, loser_id, winner_id),
                    )
                db.conn.execute("DELETE FROM map_sources WHERE id=?", (loser_id,))
                deduplicated += 1

            target = targets[winner_id]
            if not _already_target(winner, target):
                source_name, source_key, portable_path = target
                db.conn.execute(
                    "UPDATE map_sources SET root=?,source_name=?,source_key=?,path=? WHERE id=?",
                    (source_name, source_name, source_key, portable_path, winner_id),
                )
                normalized += 1

    return MapPortabilityMigration(normalized=normalized, deduplicated=deduplicated)
