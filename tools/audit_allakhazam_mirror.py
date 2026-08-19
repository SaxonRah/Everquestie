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


_HTTRACK_INTERRUPTION_MARKERS = (
    "exit requested by shell or user",
    "mirror stopped by user",
    "mirror aborted",
    "exit requested by engine",
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


def _audit_httrack_project(folder: str | Path) -> dict[str, object]:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    lock_path = root / "hts-in_progress.lock"
    log_path = root / "hts-log.txt"
    lock_present = lock_path.is_file()
    log_present = log_path.is_file()
    log_read_error: str | None = None
    completion_summary_present = False
    interruption_markers: list[str] = []

    if log_present:
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log_read_error = str(exc)
        else:
            folded = log_text.casefold()
            completion_summary_present = "mirror complete in" in folded
            interruption_markers = [
                marker for marker in _HTTRACK_INTERRUPTION_MARKERS if marker in folded
            ]

    if lock_present:
        run_state = "active"
    elif interruption_markers:
        run_state = "interrupted"
    elif log_present and log_read_error is None and completion_summary_present:
        run_state = "completed"
    else:
        run_state = "unknown"

    return {
        "httrack_project_root": str(root),
        "httrack_run_state": run_state,
        "httrack_lock_file_present": lock_present,
        "httrack_log_file_present": log_present,
        "httrack_log_read_error": log_read_error,
        "httrack_completion_summary_present": completion_summary_present,
        "httrack_interruption_markers": interruption_markers,
    }


def _format_httrack_project_audit(payload: dict[str, object]) -> str:
    markers = payload["httrack_interruption_markers"]
    marker_text = ", ".join(str(marker) for marker in markers) if markers else "none"
    read_error = payload["httrack_log_read_error"] or "none"
    return "\n".join(
        [
            "",
            "HTTrack project completion evidence:",
            f"  Project root: {payload['httrack_project_root']}",
            f"  Run state: {payload['httrack_run_state']}",
            f"  hts-in_progress.lock present: {payload['httrack_lock_file_present']}",
            f"  hts-log.txt present: {payload['httrack_log_file_present']}",
            f"  Completion summary present: {payload['httrack_completion_summary_present']}",
            f"  Interruption markers: {marker_text}",
            f"  Log read error: {read_error}",
        ]
    )


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
        "--httrack-project",
        help=(
            "Explicit HTTrack project root containing hts-log.txt, hts-cache, and "
            "hts-in_progress.lock. Required with --require-complete; the audit never "
            "guesses this directory from the mirror path."
        ),
    )
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
            "Return exit code 2 unless completed mirror files and explicit HTTrack run "
            "evidence both prove a naturally completed capture. Requires "
            "--httrack-project and fails closed for active, interrupted, or unknown runs."
        ),
    )
    args = parser.parse_args(argv)

    report = audit_allakhazam_mirror(args.mirror)
    payload = report.as_dict()
    httrack_payload: dict[str, object] | None = None
    if args.httrack_project:
        httrack_payload = _audit_httrack_project(args.httrack_project)
        payload.update(httrack_payload)

    if args.output:
        _write_json_report(args.output, payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_allakhazam_mirror_audit(report))
        if httrack_payload is not None:
            print(_format_httrack_project_audit(httrack_payload))

    if not args.require_complete:
        return 0

    if httrack_payload is None:
        print(
            "Canonical completion requires --httrack-project so HTTrack run state is "
            "verified explicitly instead of inferred from the mirror directory.",
            file=sys.stderr,
        )
        return 2

    failures: list[str] = []
    if report.temporary_files:
        failures.append(
            f"{report.temporary_files:,} temporary HTTrack file(s) remain in the mirror"
        )
    run_state = str(httrack_payload["httrack_run_state"])
    if run_state != "completed":
        failures.append(f"HTTrack run state is {run_state!r}, not 'completed'")

    if failures:
        print(
            "Allakhazam mirror is not canonical-complete: " + "; ".join(failures) + ".",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
