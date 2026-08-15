from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.knowledge_build import ProviderInvocation, build_and_finalize_knowledge
from eqquest.provider_travel_frontier import ProviderTravelFrontierAudit
from eqquest.route_acceptance import evaluate_route_acceptance, route_acceptance_text


_TOPOLOGY_FRONTIER_STATUSES = {
    "disconnected",
    "directionality_blocked",
    "route_inconsistency",
}


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

    allakhazam_mirror = str(args.allakhazam_mirror or "").strip()
    allakhazam_version = str(args.allakhazam_version or "").strip()
    if allakhazam_version and not allakhazam_mirror:
        raise ValueError("--allakhazam-version requires --allakhazam-mirror")
    if allakhazam_mirror:
        invocations.append(
            ProviderInvocation(
                "allakhazam-mirror",
                {
                    "path": allakhazam_mirror,
                    "source_version": allakhazam_version,
                },
                label="Allakhazam local mirror",
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
            "No knowledge providers selected. Supply --eq-install, --allakhazam-mirror, "
            "--map-pack, or another registered builder provider."
        )
    return invocations


def _open_immutable_snapshot(snapshot_db: str | Path) -> sqlite3.Connection:
    path = Path(snapshot_db).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def audit_snapshot_routes(snapshot_db: str | Path, cases=None):
    """Evaluate route acceptance through an immutable SQLite snapshot connection."""
    conn = _open_immutable_snapshot(snapshot_db)
    try:
        db = SimpleNamespace(conn=conn, knowledge_writable=False)
        return evaluate_route_acceptance(db, cases)
    finally:
        conn.close()


def route_failure_frontier_zones(summary) -> tuple[str, ...]:
    """Return unique resolved endpoints for failures that are actually topology-shaped.

    Identity failures remain identity diagnostics. Provider travel frontier output is
    useful only after both endpoints resolved and the route failure is about compiled
    graph connectivity/directionality/consistency.
    """
    zones: list[str] = []
    seen_entity_ids: set[int] = set()
    for result in summary.results:
        if result.status not in _TOPOLOGY_FRONTIER_STATUSES:
            continue
        for endpoint in (result.source, result.target):
            if not endpoint.linked or endpoint.entity_id is None:
                continue
            entity_id = int(endpoint.entity_id)
            if entity_id in seen_entity_ids:
                continue
            seen_entity_ids.add(entity_id)
            zones.append(endpoint.canonical_name or endpoint.query)
    return tuple(zones)


def audit_snapshot_provider_travel_frontier(
    snapshot_db: str | Path,
    zones: tuple[str, ...],
):
    """Explain provider travel compiler state through the same immutable snapshot."""
    conn = _open_immutable_snapshot(snapshot_db)
    try:
        db = SimpleNamespace(conn=conn, knowledge_writable=False)
        return ProviderTravelFrontierAudit(db).summary(zones)
    finally:
        conn.close()


def _write_json_report(path: str | Path, payload: dict) -> Path:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def write_route_report(path: str | Path, summary) -> Path:
    return _write_json_report(path, summary.as_dict())


def write_provider_travel_frontier_report(path: str | Path, summary) -> Path:
    return _write_json_report(path, summary.as_dict())


def validate_audit_options(args: argparse.Namespace) -> None:
    """Reject audit combinations that could disable or overwrite build artifacts."""
    if args.skip_route_audit and args.route_report:
        raise ValueError("--route-report cannot be used with --skip-route-audit")
    if args.skip_route_audit and args.provider_travel_frontier_report:
        raise ValueError("--provider-travel-frontier-report cannot be used with --skip-route-audit")
    if args.skip_route_audit and args.require_route_acceptance:
        raise ValueError("--require-route-acceptance cannot be used with --skip-route-audit")

    working = Path(args.working_db).expanduser().resolve()
    snapshot = Path(args.snapshot_db).expanduser().resolve()
    reports: list[tuple[str, Path]] = []
    if args.route_report:
        reports.append(("--route-report", Path(args.route_report).expanduser().resolve()))
    if args.provider_travel_frontier_report:
        reports.append(
            (
                "--provider-travel-frontier-report",
                Path(args.provider_travel_frontier_report).expanduser().resolve(),
            )
        )

    for option, report_path in reports:
        if report_path == working:
            raise ValueError(f"{option} must not overwrite --working-db")
        if report_path == snapshot:
            raise ValueError(f"{option} must not overwrite --snapshot-db")

    if len(reports) == 2 and reports[0][1] == reports[1][1]:
        raise ValueError(
            "--route-report and --provider-travel-frontier-report must use different paths"
        )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Build an EverQuestie working knowledge DB from explicitly selected providers, "
            "finalize a distributable snapshot, then audit difficult real zone-to-zone routes."
        )
    )
    p.add_argument("--working-db", required=True, help="Fresh builder/working SQLite database")
    p.add_argument("--snapshot-db", required=True, help="Distributable knowledge snapshot")
    p.add_argument("--version", required=True, help="Knowledge content/snapshot version")
    p.add_argument("--eq-install", help="EverQuest installation to import directly")
    p.add_argument(
        "--allakhazam-mirror",
        help="Local HTTrack mirror of everquest.allakhazam.com to compile builder-side",
    )
    p.add_argument(
        "--allakhazam-version",
        help="Optional mirror capture/version label retained as source provenance",
    )
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
        "--skip-route-audit",
        action="store_true",
        help="Do not run the built-in difficult real-route acceptance suite after finalization",
    )
    p.add_argument(
        "--route-report",
        help="Optional path for a machine-readable route-acceptance JSON report",
    )
    p.add_argument(
        "--provider-travel-frontier-report",
        help=(
            "Optional JSON path for provider-compiler frontier diagnostics covering the unique "
            "resolved endpoints of topology-shaped route acceptance failures"
        ),
    )
    p.add_argument(
        "--require-route-acceptance",
        action="store_true",
        help="Return exit code 2 when any built-in route acceptance case fails",
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
        validate_audit_options(args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

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
    except FileExistsError as exc:
        existing = exc.args[0] if exc.args else args.working_db
        raise SystemExit(
            f"Output already exists: {existing}. Use --force to rebuild it."
        ) from exc
    except (ValueError, FileNotFoundError) as exc:
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
    print(
        "provider zone reconciliation: "
        + ", ".join(
            f"{key}={value}"
            for key, value in sorted(report.snapshot.provider_zone_reconciliation.items())
        )
    )
    print(
        "provider zone travel: "
        + ", ".join(
            f"{key}={value}"
            for key, value in sorted(report.snapshot.provider_zone_travel.items())
        )
    )

    route_summary = None
    if not args.skip_route_audit:
        route_summary = audit_snapshot_routes(report.snapshot.path)
        print()
        print(route_acceptance_text(route_summary))
        if args.route_report:
            output = write_route_report(args.route_report, route_summary)
            print()
            print(f"route acceptance JSON: {output}")

        if args.provider_travel_frontier_report:
            frontier_zones = route_failure_frontier_zones(route_summary)
            frontier_summary = audit_snapshot_provider_travel_frontier(
                report.snapshot.path,
                frontier_zones,
            )
            output = write_provider_travel_frontier_report(
                args.provider_travel_frontier_report,
                frontier_summary,
            )
            print()
            if frontier_zones:
                print("provider travel frontier zones: " + ", ".join(frontier_zones))
                for zone in frontier_summary.zones:
                    name = zone.canonical_zone_name or zone.query
                    print(f"provider travel frontier {name}: {zone.classification}")
            else:
                print("provider travel frontier zones: none (no topology-shaped route failures)")
            print(f"provider travel frontier JSON: {output}")

    if args.require_route_acceptance and route_summary is not None and route_summary.failed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())