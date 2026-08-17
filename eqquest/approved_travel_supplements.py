from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from typing import Callable

from .approved_zone_aliases import compile_approved_zone_aliases
from .db import Database
from .knowledge_build import (
    KnowledgeBuildReport,
    KnowledgeProviderRegistry,
    ProviderInvocation,
    build_working_knowledge_db,
)
from .knowledge_snapshot import create_knowledge_snapshot
from .travel_supplement import TravelSupplementBuildStats, TravelSupplementImporter


ProgressCallback = Callable[[str], None] | None


def approved_travel_manifest_paths(root: str | Path) -> tuple[Path, ...]:
    """Return the reviewed manifest set in deterministic filename order.

    Release builds treat the repository-owned directory as a required builder input.
    Missing or accidentally emptied directories fail loudly instead of producing a
    snapshot that silently drops reviewed travel knowledge.
    """
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
            f"approved travel supplement directory contains no JSON manifests: {directory}"
        )
    return manifests


def compile_approved_travel_supplements(
    working_db: str | Path,
    supplement_dir: str | Path,
    *,
    progress: ProgressCallback = None,
) -> tuple[TravelSupplementBuildStats, ...]:
    """Compile every reviewed travel manifest into a writable working DB."""
    manifests = approved_travel_manifest_paths(supplement_dir)
    db = Database(Path(working_db).expanduser().resolve())
    results: list[TravelSupplementBuildStats] = []
    try:
        importer = TravelSupplementImporter(db)
        for manifest in manifests:
            if progress is not None:
                progress(f"[travel-supplement] {manifest.name}")
            result = importer.import_manifest(manifest)
            results.append(result)
            if progress is not None:
                progress(
                    "[travel-supplement] compiled "
                    f"{manifest.name}: edges={result.edges}, "
                    f"bidirectional={result.bidirectional_edges}, "
                    f"requirements={result.requirements}"
                )
        db.set_meta("approved_travel_supplement_count", str(len(results)))
        db.set_meta(
            "approved_travel_supplement_edge_count",
            str(sum(result.edges for result in results)),
        )
    finally:
        db.close()
    return tuple(results)


def stage_builder_with_approved_travel_supplements(
    source_db: str | Path,
    staged_db: str | Path,
    supplement_dir: str | Path,
    *,
    zone_alias_dir: str | Path | None = None,
    overwrite: bool = False,
    progress: ProgressCallback = None,
) -> tuple[TravelSupplementBuildStats, ...]:
    """Clone a builder DB safely, then compile approved supplements into the clone.

    The source is opened read-only and copied with SQLite's backup API so committed WAL
    content is included without mutating the builder database. If a reviewed zone-alias
    directory is supplied, identity aliases are compiled first so subsequent travel
    compilation and finalization can resolve source labels through ordinary canonical
    identity. The staged file is only published after every requested manifest set
    validates and compiles successfully.
    """
    source = Path(source_db).expanduser().resolve()
    staged = Path(staged_db).expanduser().resolve()
    if source == staged:
        raise ValueError("staged release database must differ from source builder database")
    if not source.is_file():
        raise FileNotFoundError(source)
    if staged.exists() and not overwrite:
        raise FileExistsError(staged)

    staged.parent.mkdir(parents=True, exist_ok=True)
    temp = staged.with_name(staged.name + ".building")
    temp.unlink(missing_ok=True)

    source_conn: sqlite3.Connection | None = None
    target_conn: sqlite3.Connection | None = None
    try:
        if progress is not None:
            progress(f"[release-stage] cloning builder DB: {source}")
        source_conn = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        target_conn = sqlite3.connect(temp)
        source_conn.backup(target_conn)
        target_conn.close()
        target_conn = None
        source_conn.close()
        source_conn = None

        if zone_alias_dir is not None:
            compile_approved_zone_aliases(
                temp,
                zone_alias_dir,
                progress=progress,
            )
        results = compile_approved_travel_supplements(
            temp,
            supplement_dir,
            progress=progress,
        )
        if staged.exists():
            staged.unlink()
        os.replace(temp, staged)
        if progress is not None:
            progress(f"[release-stage] ready: {staged}")
        return results
    except Exception:
        if target_conn is not None:
            try:
                target_conn.close()
            except Exception:
                pass
        if source_conn is not None:
            try:
                source_conn.close()
            except Exception:
                pass
        temp.unlink(missing_ok=True)
        raise


def build_and_finalize_with_approved_travel_supplements(
    working_db: str | Path,
    snapshot_db: str | Path,
    invocations: list[ProviderInvocation],
    *,
    snapshot_version: str,
    supplement_dir: str | Path,
    zone_alias_dir: str | Path | None = None,
    registry: KnowledgeProviderRegistry | None = None,
    overwrite: bool = False,
    progress: ProgressCallback = None,
) -> KnowledgeBuildReport:
    """Build providers, compile reviewed identity/travel data, then finalize."""
    report = build_working_knowledge_db(
        working_db,
        invocations,
        registry=registry,
        overwrite=overwrite,
        progress=progress,
    )
    if zone_alias_dir is not None:
        compile_approved_zone_aliases(
            report.working_db,
            zone_alias_dir,
            progress=progress,
        )
    compile_approved_travel_supplements(
        report.working_db,
        supplement_dir,
        progress=progress,
    )
    report.snapshot = create_knowledge_snapshot(
        report.working_db,
        snapshot_db,
        snapshot_version=snapshot_version,
        overwrite=overwrite,
    )
    return report
