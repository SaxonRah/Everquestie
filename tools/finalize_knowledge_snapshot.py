from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.knowledge_snapshot import create_knowledge_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a distributable EverQuestie knowledge snapshot from a copy of a working DB. "
            "Player state and builder-local paths are stripped from the output only."
        )
    )
    parser.add_argument("--input", required=True, help="Working EverQuestie SQLite database")
    parser.add_argument("--output", required=True, help="Versioned knowledge snapshot to create")
    parser.add_argument("--version", required=True, help="Knowledge content/snapshot version")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing output snapshot; never modifies the input DB",
    )
    args = parser.parse_args()

    report = create_knowledge_snapshot(
        Path(args.input),
        Path(args.output),
        snapshot_version=args.version,
        overwrite=args.force,
    )
    print(f"knowledge snapshot: {report.path}")
    print(f"content version: {report.snapshot_version}")
    print(f"schema version: {report.schema_version}")
    print(f"built at: {report.built_at}")
    print(f"FTS rows: {report.fts_rows:,}")
    print(
        "stripped user rows: "
        + ", ".join(f"{name}={count}" for name, count in report.stripped_user_rows.items())
    )
    print(f"stripped source paths: {report.stripped_source_paths:,}")
    print(f"stripped runtime/meta rows: {report.stripped_meta_rows:,}")
    print(f"stripped builder payloads: {report.stripped_builder_payloads:,}")
    print(
        "mechanics reconciliation: "
        + ", ".join(
            f"{name}={value}"
            for name, value in report.mechanics_reconciliation.items()
            if name not in {"class_ids_seen", "skill_ids_seen"}
        )
    )
    print(
        "quest faction reconciliation: "
        + ", ".join(
            f"{name}={value}"
            for name, value in report.quest_faction_reconciliation.items()
        )
    )
    print(
        "provider zone reconciliation: "
        + ", ".join(
            f"{name}={value}"
            for name, value in report.provider_zone_reconciliation.items()
        )
    )
    print(
        "provider zone travel: "
        + ", ".join(
            f"{name}={value}"
            for name, value in report.provider_zone_travel.items()
        )
    )
    print(
        "zone coverage: "
        + ", ".join(
            f"{name}={value}"
            for name, value in report.zone_coverage.items()
            if not name.startswith("zones_without_")
        )
    )
    print(
        "map reconciliation: "
        + ", ".join(f"{name}={count}" for name, count in report.map_reconciliation.items())
    )
    print(f"integrity: {report.diagnostics.get('integrity')}")
    print()
    print(report.identity_audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
