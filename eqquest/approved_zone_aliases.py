from __future__ import annotations

from pathlib import Path
from typing import Callable

from .db import Database
from .zone_alias_supplement import (
    ZoneAliasSupplementBuildStats,
    ZoneAliasSupplementImporter,
)


ProgressCallback = Callable[[str], None] | None


def approved_zone_alias_manifest_paths(root: str | Path) -> tuple[Path, ...]:
    """Return the repository-reviewed zone-alias manifests in deterministic order."""
    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    manifests = tuple(
        sorted(
            (
                path
                for path in directory.iterdir()
                if path.is_file() and path.suffix.casefold() == ".json"
            ),
            key=lambda path: path.name.casefold(),
        )
    )
    if not manifests:
        raise ValueError(
            f"approved zone alias directory contains no JSON manifests: {directory}"
        )
    return manifests


def compile_approved_zone_aliases(
    working_db: str | Path,
    alias_dir: str | Path,
    *,
    progress: ProgressCallback = None,
) -> tuple[ZoneAliasSupplementBuildStats, ...]:
    """Compile every reviewed zone-alias manifest into a writable working DB."""
    manifests = approved_zone_alias_manifest_paths(alias_dir)
    db = Database(Path(working_db).expanduser().resolve())
    results: list[ZoneAliasSupplementBuildStats] = []
    try:
        importer = ZoneAliasSupplementImporter(db)
        for manifest in manifests:
            if progress is not None:
                progress(f"[zone-alias] {manifest.name}")
            result = importer.import_manifest(manifest)
            results.append(result)
            if progress is not None:
                progress(
                    "[zone-alias] compiled "
                    f"{manifest.name}: aliases={result.aliases}"
                )
        db.set_meta("approved_zone_alias_supplement_count", str(len(results)))
        db.set_meta(
            "approved_zone_alias_count",
            str(sum(result.aliases for result in results)),
        )
    finally:
        db.close()
    return tuple(results)
