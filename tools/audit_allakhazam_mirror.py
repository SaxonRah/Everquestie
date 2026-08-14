from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.allakhazam_mirror_audit import (
    allakhazam_mirror_audit_text,
    audit_allakhazam_mirror,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory a local Allakhazam mirror without importing it. Reports raw "
            "file count, HTML/canonical-page coverage, structured page kinds and "
            "duplicate canonical URLs. No network or database access is used."
        )
    )
    parser.add_argument("mirror", help="Local Allakhazam DB mirror root")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable report",
    )
    args = parser.parse_args(argv)

    if args.json:
        report = audit_allakhazam_mirror(args.mirror)
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(allakhazam_mirror_audit_text(args.mirror))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
