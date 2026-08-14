from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.knowledge_build import ProviderInvocation, build_and_finalize_knowledge


def _assignment(value: str, *, option: str) -> tuple[str, str]:
    name, sep, payload = value.partition("=")
    name = name.strip()
    payload = payload.strip()
    if not sep or not name or not payload:
        raise argparse.ArgumentTypeError(f"{option} must use NAME=VALUE syntax")
    return name, payload


def _map_versions(values: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for value in values:
        name, version = _assignment(value, option="--map-version")
        versions[name.casefold()] = version
    return versions


def build_invocations(args: argparse.Namespace) -> list[ProviderInvocation]:
    invocations: list[ProviderInvocation] = []

    eq_install = str(args.eq_install or "").strip()
    if eq_install:
        invocations.append(
            ProviderInvocation(
                "eqclient",
                {"path": eq_install},
                label="installed EverQuest client",
            )
        )

    mcp_repository = str(args.mcp_repository or "").strip()
    if mcp_repository:
        if not eq_install:
            raise ValueError("--mcp-repository requires --eq-install")
        invocations.append(
            ProviderInvocation(
                "mcp",
                {
                    "eq_path": eq_install,
                    "mcp_path": mcp_repository,
                    "include_details": not bool(args.skip_mcp_details),
                },
                label="everquest1-mcp builder snapshot",
            )
        )

    versions = _map_versions(list(args.map_version or []))
    seen_map_names: set[str] = set()
    for raw in list(args.map_pack or []):
        source_name, path = _assignment(raw, option="--map-pack")
        key = source_name.casefold()
        if key in seen_map_names:
            raise ValueError(f"duplicate --map-pack source name: {source_name}")
        seen_map_names.add(key)
        invocations.append(
            ProviderInvocation(
                "map-pack",
                {
                    "path": path,
                    "source_name": source_name,
                    "source_version": versions.get(key, ""),
                },
                label=source_name,
            )
        )

    unknown_versions = sorted(set(versions) - seen_map_names)
    if unknown_versions:
        raise ValueError(
            "--map-version supplied without matching --map-pack: "
            + ", ".join(unknown_versions)
        )
    if not invocations:
        raise ValueError(
            "No knowledge providers selected. Supply --eq-install, --map-pack, or another registered builder provider."
        )
    return invocations


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Build an EverQuestie working knowledge DB from explicitly selected providers, "
            "then finalize a distributable snapshot. Allakhazam DB/Wiki are not required."
        )
    )
    p.add_argument("--working-db", required=True, help="Fresh builder/working SQLite database")
    p.add_argument("--snapshot-db", required=True, help="Distributable knowledge snapshot")
    p.add_argument("--version", required=True, help="Knowledge content/snapshot version")
    p.add_argument("--eq-install", help="EverQuest installation to import directly")
    p.add_argument(
        "--mcp-repository",
        help="Optional everquest1-mcp checkout for builder-only inventory/detail enrichment",
    )
    p.add_argument(
        "--skip-mcp-details",
        action="store_true",
        help="Capture MCP inventory only; skip optional rich-detail bridge",
    )
    p.add_argument(
        "--map-pack",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Explicit map source to catalog; repeat for Good/Brewall/other packs",
    )
    p.add_argument(
        "--map-version",
        action="append",
        default=[],
        metavar="NAME=VERSION",
        help="Optional version/date for a named --map-pack",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Replace existing builder/snapshot outputs; never overwrites a user runtime DB implicitly",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        invocations = build_invocations(args)
        report = build_and_finalize_knowledge(
            Path(args.working_db),
            Path(args.snapshot_db),
            invocations,
            snapshot_version=args.version,
            overwrite=bool(args.force),
            progress=print,
        )
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc

    print()
    print(f"working knowledge DB: {report.working_db}")
    for result in report.providers:
        counts = ", ".join(f"{key}={value}" for key, value in sorted(result.counts.items()))
        print(f"provider {result.provider} ({result.label}): {counts or 'completed'}")
    assert report.snapshot is not None
    print(f"release snapshot: {report.snapshot.path}")
    print(f"content version: {report.snapshot.snapshot_version}")
    print(f"schema version: {report.snapshot.schema_version}")
    print(f"integrity: {report.snapshot.diagnostics.get('integrity')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
