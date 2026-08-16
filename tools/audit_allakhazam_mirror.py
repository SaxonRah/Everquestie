from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.allakhazam_mirror_audit import (
    audit_allakhazam_mirror,
    format_allakhazam_mirror_audit,
)


def _write_json_report(path: str | Path, payload: dict[str, object]) -> Path:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory a local Allakhazam mirror without importing it. Reports raw "
            "file count, HTML/canonical-page coverage, structured page kinds, spell "
            "lifecycle readiness and duplicate canonical URLs. No network or database "
            "access is used."
        )
    )
    parser.add_argument("mirror", help="Local Allakhazam DB mirror root")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable report",
    )
    parser.add_argument(
        "--output",
        help=(
            "Also write the machine-readable JSON report to this path. The report is "
            "written atomically and parent directories are created as needed."
        ),
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help=(
            "Return exit code 2 when HTTrack temporary/in-progress files remain. "
            "Canonical full builds use this so an actively mirrored tree cannot be "
            "mistaken for a completed source capture."
        ),
    )
    args = parser.parse_args(argv)

    report = audit_allakhazam_mirror(args.mirror)
    payload = report.as_dict()
    if args.output:
        _write_json_report(args.output, payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_allakhazam_mirror_audit(report))

    if args.require_complete and report.temporary_files:
        print(
            "Allakhazam mirror is still in progress: "
            f"{report.temporary_files:,} temporary HTTrack file(s) remain. "
            "Wait for the mirror to finish before running a canonical full build.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
