from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.mcp_source_lock import inspect_local_mcp_source_lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that the local everquest1-mcp builder checkout matches EverQuestie's "
            "tracked repository lock. This command is read-only."
        )
    )
    parser.add_argument(
        "--project-root",
        default=str(REPO_ROOT),
        help="EverQuestie source checkout (default: repository root)",
    )
    parser.add_argument(
        "--mcp-path",
        help="Override the local everquest1-mcp checkout path",
    )
    args = parser.parse_args(argv)

    status = inspect_local_mcp_source_lock(
        args.project_root,
        mcp_path=args.mcp_path,
    )
    lock = status.lock_read.lock

    print("EverQuestie MCP builder source verification")
    print()
    print(f"Lock: {status.lock_read.path}")
    print(f"  present: {'yes' if status.lock_read.present else 'NO'}")
    print(f"  valid: {'yes' if status.lock_read.valid else 'NO'}")
    if lock is not None:
        print(f"  repository: {lock.repository}")
        print(f"  commit: {lock.commit}")
        print(f"  package version: {lock.package_version}")
    elif status.lock_read.error:
        print(f"  error: {status.lock_read.error}")

    print()
    print(f"Local MCP: {status.mcp_path}")
    print(f"  checkout present: {'yes' if status.checkout_present else 'NO'}")
    print(f"  Git checkout: {'yes' if status.git_checkout else 'NO'}")
    print(f"  HEAD: {status.commit or 'not available'}")
    print(f"  package version: {status.package_version or 'not available'}")
    print(f"  origin: {status.remote or 'not available'}")
    print()
    print(f"Locked builder source: {'PASS' if status.ok else 'FAIL'}")
    if not status.ok:
        print(f"Reason: {status.failure_reason()}")
        return 2
    print("Boundary: verification is read-only; it does not fetch, checkout, install, or build MCP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
