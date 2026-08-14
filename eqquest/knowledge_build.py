from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .db import Database
from .knowledge_snapshot import KnowledgeSnapshotReport, create_knowledge_snapshot
from .map_catalog import MapCatalog
from .sources import EQClientImporter, MCPLocalSnapshotCompiler


ProviderConfig = Mapping[str, Any]
ProviderRunner = Callable[["KnowledgeBuildContext", ProviderConfig], "ProviderBuildResult"]


@dataclass(slots=True)
class ProviderBuildResult:
    provider: str
    label: str
    counts: dict[str, int] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderInvocation:
    provider: str
    config: dict[str, Any] = field(default_factory=dict)
    label: str = ""


@dataclass(slots=True)
class KnowledgeBuildContext:
    db: Database
    working_db: Path
    progress: Callable[[str], None] | None = None

    def emit(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)


@dataclass(slots=True)
class KnowledgeBuildReport:
    working_db: Path
    providers: list[ProviderBuildResult]
    snapshot: KnowledgeSnapshotReport | None = None


class KnowledgeProviderRegistry:
    """Registry of explicit builder-side knowledge providers.

    The build coordinator knows only provider names/configuration and EverQuestie's
    normalized database.  Allakhazam DB/Wiki, or any other future mirror, can register
    a provider later without becoming a required import or changing the coordinator.
    """

    def __init__(self) -> None:
        self._runners: dict[str, ProviderRunner] = {}

    def register(self, name: str, runner: ProviderRunner, *, replace: bool = False) -> None:
        key = self._normalize_name(name)
        if not key:
            raise ValueError("provider name is required")
        if key in self._runners and not replace:
            raise ValueError(f"knowledge provider already registered: {key}")
        self._runners[key] = runner

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._runners))

    def run(
        self,
        invocation: ProviderInvocation,
        context: KnowledgeBuildContext,
    ) -> ProviderBuildResult:
        key = self._normalize_name(invocation.provider)
        runner = self._runners.get(key)
        if runner is None:
            available = ", ".join(self.names()) or "none"
            raise KeyError(f"unknown knowledge provider {key!r}; registered providers: {available}")
        context.emit(f"[{key}] {invocation.label or 'starting'}")
        result = runner(context, invocation.config)
        if result.provider != key:
            result.provider = key
        if not result.label:
            result.label = invocation.label or key
        return result

    @staticmethod
    def _normalize_name(name: str) -> str:
        return "-".join(str(name or "").strip().casefold().replace("_", "-").split())


def _required_path(config: ProviderConfig, key: str) -> Path:
    raw = str(config.get(key) or "").strip()
    if not raw:
        raise ValueError(f"provider configuration requires {key!r}")
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _run_eqclient(context: KnowledgeBuildContext, config: ProviderConfig) -> ProviderBuildResult:
    root = _required_path(config, "path")
    result = EQClientImporter(context.db).import_installation(root)
    counts = {
        "zones": int(result.zones),
        "help_topics": int(result.help_topics),
        "skill_caps": int(result.skill_caps),
        "base_stats": int(result.base_stats),
        "ac_mitigation": int(result.ac_mitigation),
        "spell_stacking": int(result.spell_stacking),
        "dbstring_entities": int(result.dbstring_entities),
        "skipped": int(result.skipped),
    }
    return ProviderBuildResult(
        provider="eqclient",
        label="EverQuest client files",
        counts=counts,
        details={"path": str(root)},
    )


def _run_mcp(context: KnowledgeBuildContext, config: ProviderConfig) -> ProviderBuildResult:
    eq_path = _required_path(config, "eq_path")
    mcp_path = _required_path(config, "mcp_path")
    include_details = bool(config.get("include_details", True))
    compiler = MCPLocalSnapshotCompiler(context.db)
    result = compiler.compile_installation(
        eq_path,
        mcp_path,
        include_details=include_details,
        progress=context.emit,
    )
    counts = {f"inventory_{kind}": int(count) for kind, count in result.inventory_by_kind.items()}
    counts.update(
        {f"details_{kind}": int(count) for kind, count in result.detail_imported_by_kind.items()}
    )
    return ProviderBuildResult(
        provider="mcp",
        label="EverQuest client via everquest1-mcp",
        counts=counts,
        details={
            "mcp_version": result.mcp_version,
            "mcp_commit": result.mcp_commit,
            "snapshot_timestamp": result.snapshot_timestamp,
        },
    )


def _run_map_pack(context: KnowledgeBuildContext, config: ProviderConfig) -> ProviderBuildResult:
    root = _required_path(config, "path")
    source_name = str(config.get("source_name") or "").strip()
    if not source_name:
        raise ValueError("map-pack provider requires 'source_name'")
    source_version = str(config.get("source_version") or "")

    def progress(stage: str, current: int, total: int, detail: str) -> None:
        context.emit(f"[map-pack:{source_name}] {stage} {current}/{total} {detail}")

    stats = MapCatalog(context.db).index_root(
        root,
        source_name=source_name,
        source_version=source_version,
        progress=progress,
    )
    return ProviderBuildResult(
        provider="map-pack",
        label=source_name,
        counts={
            "base_maps": int(stats.base_maps),
            "files_indexed": int(stats.files_indexed),
            "files_unchanged": int(stats.files_unchanged),
            "labels": int(stats.labels),
            "linked": int(stats.linked),
            "ambiguous": int(stats.ambiguous),
            "unresolved": int(stats.unresolved),
        },
        details={"source_version": source_version},
    )


def default_provider_registry() -> KnowledgeProviderRegistry:
    registry = KnowledgeProviderRegistry()
    registry.register("eqclient", _run_eqclient)
    registry.register("mcp", _run_mcp)
    registry.register("map-pack", _run_map_pack)
    return registry


def build_working_knowledge_db(
    output_db: str | Path,
    invocations: list[ProviderInvocation],
    *,
    registry: KnowledgeProviderRegistry | None = None,
    overwrite: bool = False,
    progress: Callable[[str], None] | None = None,
) -> KnowledgeBuildReport:
    """Build a fresh EverQuestie-owned working knowledge DB from explicit providers."""
    output = Path(output_db).expanduser().resolve()
    if output.exists() and not overwrite:
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".building")
    temp.unlink(missing_ok=True)
    registry = registry or default_provider_registry()

    provider_results: list[ProviderBuildResult] = []
    db: Database | None = None
    try:
        db = Database(temp)
        context = KnowledgeBuildContext(db=db, working_db=temp, progress=progress)
        for invocation in invocations:
            provider_results.append(registry.run(invocation, context))
        db.set_meta("knowledge_build_provider_count", str(len(provider_results)))
        db.close()
        db = None

        if output.exists():
            output.unlink()
        os.replace(temp, output)
        return KnowledgeBuildReport(working_db=output, providers=provider_results)
    except Exception:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
        temp.unlink(missing_ok=True)
        raise


def build_and_finalize_knowledge(
    working_db: str | Path,
    snapshot_db: str | Path,
    invocations: list[ProviderInvocation],
    *,
    snapshot_version: str,
    registry: KnowledgeProviderRegistry | None = None,
    overwrite: bool = False,
    progress: Callable[[str], None] | None = None,
) -> KnowledgeBuildReport:
    """Build a working DB and then produce the distributable snapshot from its copy."""
    report = build_working_knowledge_db(
        working_db,
        invocations,
        registry=registry,
        overwrite=overwrite,
        progress=progress,
    )
    report.snapshot = create_knowledge_snapshot(
        report.working_db,
        snapshot_db,
        snapshot_version=snapshot_version,
        overwrite=overwrite,
    )
    return report
