from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
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


_HTTRACK_OUTPUT_RE = re.compile(
    r"(?:^|\s)-O1\s+(?:\"([^\"]+)\"|'([^']+)'|([^\s)]+))",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_httrack_output_root(log_text: str) -> str | None:
    match = _HTTRACK_OUTPUT_RE.search(log_text)
    if match is None:
        return None
    return next((value for value in match.groups() if value), None)


def _project_path_key(value: str | Path) -> str:
    text = str(value).strip().replace("\\", "/").rstrip("/")
    wsl = re.match(r"^/mnt/([a-zA-Z])/(.*)$", text)
    if wsl:
        text = f"{wsl.group(1)}:/{wsl.group(2)}"
    return text.casefold()


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
    logged_output_root: str | None = None
    log_project_match: bool | None = None

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
            logged_output_root = _extract_httrack_output_root(log_text)
            if logged_output_root:
                log_project_match = (
                    _project_path_key(logged_output_root) == _project_path_key(root)
                )

    if lock_present:
        run_state = "active"
    elif log_project_match is False:
        # A copied/stale hts-log.txt from a different HTTrack output project cannot
        # prove this project's completion or interruption state.
        run_state = "unknown"
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
        "httrack_logged_output_root": logged_output_root,
        "httrack_log_project_match": log_project_match,
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
            f"  Logged HTTrack output root: {payload['httrack_logged_output_root'] or 'not recorded'}",
            f"  Log matches project root: {payload['httrack_log_project_match']}",
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
    parser.add_argument(
        "--allow-unverified-clean",
        "--allow-interrupted-clean",
        dest="allow_unverified_clean",
        action="store_true",
        help=(
            "Developer-only override for rebuilding from a clean captured corpus when "
            "the project is inactive and has no temporary files, but completion "
            "provenance is interrupted or the attached hts-log belongs to a different "
            "HTTrack output project. This does NOT mark the mirror canonical-complete."
        ),
    )
    args = parser.parse_args(argv)

    report = audit_allakhazam_mirror(args.mirror)
    payload = report.as_dict()
    httrack_payload: dict[str, object] | None = None
    if args.httrack_project:
        httrack_payload = _audit_httrack_project(args.httrack_project)
        payload.update(httrack_payload)

    unverified_clean_reason: str | None = None
    unverified_clean_accepted = False
    if args.require_complete and httrack_payload is not None:
        run_state = str(httrack_payload["httrack_run_state"])
        if run_state == "interrupted":
            unverified_clean_reason = "interrupted HTTrack run"
        elif run_state == "unknown" and httrack_payload["httrack_log_project_match"] is False:
            unverified_clean_reason = "hts-log.txt belongs to a different HTTrack output project"

        unverified_clean_accepted = bool(
            args.allow_unverified_clean
            and unverified_clean_reason is not None
            and not report.temporary_files
            and not bool(httrack_payload["httrack_lock_file_present"])
            and bool(httrack_payload["httrack_log_file_present"])
            and httrack_payload["httrack_log_read_error"] is None
        )

    payload["completion_policy"] = (
        "allow-unverified-clean" if args.allow_unverified_clean else "canonical-complete"
    )
    payload["canonical_complete"] = bool(
        httrack_payload is not None
        and not report.temporary_files
        and str(httrack_payload["httrack_run_state"]) == "completed"
    )
    payload["unverified_clean_capture_accepted"] = unverified_clean_accepted
    payload["unverified_clean_capture_reason"] = unverified_clean_reason
    payload["interrupted_clean_capture_accepted"] = bool(
        unverified_clean_accepted and str(httrack_payload["httrack_run_state"]) == "interrupted"
    ) if httrack_payload is not None else False

    if args.output:
        _write_json_report(args.output, payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_allakhazam_mirror_audit(report))
        if httrack_payload is not None:
            print(_format_httrack_project_audit(httrack_payload))
        if unverified_clean_accepted:
            print(
                "\nDEVELOPER OVERRIDE: accepting a clean captured corpus with "
                f"unverified completion provenance ({unverified_clean_reason}). "
                "This mirror is NOT canonical-complete."
            )

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
    if run_state != "completed" and not unverified_clean_accepted:
        if httrack_payload["httrack_log_project_match"] is False:
            failures.append(
                "hts-log.txt belongs to a different HTTrack output project and cannot "
                "prove this mirror complete"
            )
        else:
            failures.append(f"HTTrack run state is {run_state!r}, not 'completed'")

    if failures:
        print(
            "Allakhazam mirror is not canonical-complete: " + "; ".join(failures) + ".",
            file=sys.stderr,
        )
        return 2

    if unverified_clean_accepted:
        print(
            "WARNING: proceeding with a noncanonical Allakhazam capture whose completion "
            f"provenance is unverified ({unverified_clean_reason}); do not publish this "
            "snapshot as crawl-complete.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
