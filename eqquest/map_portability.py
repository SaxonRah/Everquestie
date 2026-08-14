from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
import re

from .db import Database
from .eqmap import normalize_map_name


LEGACY_SOURCE_NAME = "legacy-local"


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
    if not raw_value or not raw_root or not _looks_absolute(raw_value) or not _looks_absolute(raw_root):
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


def _legacy_target(row) -> tuple[str, str, str] | None:
    """Return a safe portable identity for one schema-migrated legacy-local row.

    The old catalog recorded the selected map-pack directory in ``root`` and absolute
    filenames in both ``source_key`` and ``path``. The root basename is therefore the
    original pack identity (for example ``Good's Maps``), while the path relative to
    that root is exactly the key the current catalog builder would write.
    """
    if str(row["source_name"] or "").strip().casefold() != LEGACY_SOURCE_NAME:
        return None

    root = str(row["root"] or "").strip()
    source_key = str(row["source_key"] or "").strip()
    path = str(row["path"] or "").strip()
    map_stem = str(row["map_stem"] or "").strip()
    layer = int(row["layer"] or 0)

    source_name = _basename(root)
    if not source_name:
        return None

    portable_key = ""
    for candidate in (source_key, path):
        portable_key = _relative_to_root(candidate, root)
        if portable_key:
            break

    # Some very early rows may have lost a usable root but still contain the exact
    # stem/layer filename. Only that deterministic leaf is accepted as a fallback.
    if not portable_key:
        expected = _expected_filename(map_stem, layer)
        for candidate in (source_key, path):
            leaf = _basename(candidate)
            if leaf and expected and leaf.casefold() == expected.casefold():
                portable_key = leaf
                break

    if not portable_key:
        return None

    return source_name, portable_key, _portable_path(source_name, portable_key)


def _merge_labels(db: Database, *, winner_id: int, loser_id: int) -> None:
    table = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='map_labels'"
    ).fetchone()
    if table is None:
        return
    # Preserve source lines that do not already exist in the preferred portable row.
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


def normalize_legacy_map_sources(db: Database) -> MapPortabilityMigration:
    """Normalize pre-portable ``legacy-local`` map rows in a release/build DB copy.

    Current map indexing is already portable. This function exists solely for builder
    databases cataloged before that change, where ``source_name`` was later backfilled
    to ``legacy-local`` and absolute builder paths remained in the row.

    Named sources are never guessed or rewritten here. If a named source still carries
    absolute filesystem paths, the existing snapshot portability audit continues to
    reject it. That keeps this migration narrow and deterministic.
    """
    table = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='map_sources'"
    ).fetchone()
    if table is None:
        return MapPortabilityMigration()

    rows = db.conn.execute(
        "SELECT id,root,source_name,source_key,map_stem,layer,path,mtime_ns,size,indexed_at "
        "FROM map_sources WHERE lower(trim(source_name))=? ORDER BY id",
        (LEGACY_SOURCE_NAME,),
    ).fetchall()
    if not rows:
        return MapPortabilityMigration()

    normalized = 0
    deduplicated = 0
    with db.batch():
        for row in rows:
            row_id = int(row["id"])
            target = _legacy_target(row)
            if target is None:
                # Leave genuinely non-derivable evidence untouched. The final
                # portability audit will emit the release-blocking diagnostic.
                continue
            source_name, source_key, portable_path = target

            existing = db.conn.execute(
                """
                SELECT id FROM map_sources
                WHERE id<>? AND (
                    (source_name=? AND source_key=?) OR path=?
                )
                ORDER BY
                    CASE WHEN path LIKE 'mapcatalog://%' THEN 0 ELSE 1 END,
                    mtime_ns DESC,
                    indexed_at DESC,
                    id DESC
                LIMIT 1
                """,
                (row_id, source_name, source_key, portable_path),
            ).fetchone()

            if existing is not None:
                winner_id = int(existing["id"])
                _merge_labels(db, winner_id=winner_id, loser_id=row_id)
                db.conn.execute("DELETE FROM map_sources WHERE id=?", (row_id,))
                deduplicated += 1
                continue

            db.conn.execute(
                "UPDATE map_sources SET root=?,source_name=?,source_key=?,path=? WHERE id=?",
                (source_name, source_name, source_key, portable_path, row_id),
            )
            normalized += 1

    return MapPortabilityMigration(normalized=normalized, deduplicated=deduplicated)
