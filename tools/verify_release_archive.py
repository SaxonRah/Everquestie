from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.release_archive import audit_release_archive


def _human_text(audit) -> str:
    lines = [
        "EverQuestie final release archive audit",
        f"Status: {audit.status}",
        f"Archive: {audit.archive}",
        f"Release version: {audit.release_version or '(missing)'}",
        f"Layout: {audit.layout or '(missing)'}",
        f"Manifest: {audit.manifest_member or '(missing)'}",
        f"Executable: {audit.executable_member or '(missing)'}",
        (
            f"Knowledge member: {audit.knowledge_member}"
            if audit.knowledge_member
            else "Knowledge member: embedded or unavailable"
        ),
        f"Source knowledge verified: {'yes' if audit.source_knowledge_verified else 'no'}",
        f"Archive files: {audit.archive_files}",
    ]
    if audit.errors:
        lines.append("Errors:")
        lines.extend(f"  - {error}" for error in audit.errors)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Re-open a finished EverQuestie release ZIP and verify its manifest, "
            "member paths, executable, knowledge artifact, and release-state exclusions."
        )
    )
    parser.add_argument("archive", help="EverQuestie Windows release ZIP")
    parser.add_argument(
        "--source-knowledge",
        default="",
        help="Audited source everquestie-knowledge.sqlite3 used to build the release",
    )
    parser.add_argument(
        "--require-source-knowledge",
        action="store_true",
        help="Fail unless the source knowledge snapshot is supplied and matches the manifest",
    )
    parser.add_argument(
        "--expected-version",
        default="",
        help="Fail unless release-manifest.json has this release_version",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    audit = audit_release_archive(
        args.archive,
        source_knowledge=(args.source_knowledge or None),
        expected_version=args.expected_version,
        require_source_knowledge=args.require_source_knowledge,
    )
    if args.json:
        print(json.dumps(audit.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_human_text(audit))
    return 0 if audit.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
