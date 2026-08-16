from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.mcp_source_provenance import (
    audit_mcp_source_provenance,
    mcp_source_provenance_text,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare an EverQuestie snapshot's recorded MCP producer commit with "
            "the local MCP checkout and parent-repository gitlink state. Read-only."
        )
    )
    parser.add_argument("snapshot", help="EverQuestie knowledge snapshot")
    parser.add_argument(
        "--project-root",
        default=str(REPO_ROOT),
        help="EverQuestie source checkout (default: repository root)",
    )
    parser.add_argument(
        "--mcp-path",
        help="Override local everquest1-mcp checkout path",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    report = audit_mcp_source_provenance(
        args.snapshot,
        project_root=args.project_root,
        mcp_path=args.mcp_path,
    )
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(mcp_source_provenance_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
