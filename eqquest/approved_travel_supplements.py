from __future__ import annotations

from pathlib import Path
from typing import Callable

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


def build_and_finalize_with_approved_travel_supplements(
    working_db: str | Path,
    snapshot_db: str | Path,
    invocations: list[ProviderInvocation],
    *,
    snapshot_version: str,
    supplement_dir: str | Path,
    registry: KnowledgeProviderRegistry | None = None,
    overwrite: bool = False,
    progress: ProgressCallback = None,
) -> KnowledgeBuildReport:
    """Build providers, compile reviewed supplements, then finalize the snapshot."""
    report = build_working_knowledge_db(
        working_db,
        invocations,
        registry=registry,
        overwrite=overwrite,
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
