from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.allakhazam_temporary_audit import (
    allakhazam_temporary_audit_text,
    audit_allakhazam_temporary_pages,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect HTTrack .tmp pages in a local Allakhazam mirror without renaming, "
            "importing, modifying the database, or using the network. Reports canonical "
            "identity, structured page kind, document-end signals, duplicates, and "
            "likely recovery candidates."
        )
    )
    parser.add_argument("mirror", help="Local Allakhazam DB mirror root")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable report",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print scan progress to stderr",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=8,
        help="Maximum sample paths retained for each status (default: 8)",
    )
    args = parser.parse_args(argv)

    last_reported = 0

    def progress(current: int, total: int) -> None:
        nonlocal last_reported
        if args.quiet or total <= 0:
            return
        if current != total and current - last_reported < 5000:
            return
        last_reported = current
        print(
            f"[temporary-page-audit] {current:,}/{total:,}",
            file=sys.stderr,
            flush=True,
        )

    sample_limit = max(0, int(args.sample_limit))
    if args.json:
        report = audit_allakhazam_temporary_pages(
            args.mirror,
            sample_limit=sample_limit,
            progress=progress,
        )
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            allakhazam_temporary_audit_text(
                args.mirror,
                sample_limit=sample_limit,
                progress=progress,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
