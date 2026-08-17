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

from eqquest.release_input_audit import (
    REVIEWED_RELEASE_META_KEYS,
    TRAVEL_RELEASE_META_KEYS,
    ZONE_ALIAS_RELEASE_META_KEYS,
    audit_reviewed_release_inputs,
)


def open_read_only(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _family_recorded(metadata: dict[str, int | None], keys: tuple[str, ...]) -> bool:
    return all(metadata.get(key) is not None for key in keys)


def publish_ready(audit) -> bool:
    return (
        audit.ok
        and _family_recorded(audit.metadata, ZONE_ALIAS_RELEASE_META_KEYS)
        and _family_recorded(audit.metadata, TRAVEL_RELEASE_META_KEYS)
    )


def audit_text(audit, *, require_release_inputs: bool = False) -> str:
    alias_recorded = _family_recorded(audit.metadata, ZONE_ALIAS_RELEASE_META_KEYS)
    travel_recorded = _family_recorded(audit.metadata, TRAVEL_RELEASE_META_KEYS)
    ready = publish_ready(audit)

    lines = [
        "EverQuestie reviewed release-input audit",
        f"Status: {audit.status}",
        (
            "Reviewed zone aliases: "
            f"{audit.actual['zone_aliases']} alias(es) from "
            f"{audit.actual['zone_alias_supplements']} supplement(s)"
            if alias_recorded
            else "Reviewed zone aliases: not recorded"
        ),
        (
            "Reviewed travel: "
            f"{audit.actual['travel_edges']} edge(s) from "
            f"{audit.actual['travel_supplements']} supplement(s)"
            if travel_recorded
            else "Reviewed travel: not recorded"
        ),
        f"Publish-ready reviewed inputs: {'yes' if ready else 'no'}",
    ]
    if audit.errors:
        lines.append("Errors:")
        lines.extend(f"  - {error}" for error in audit.errors)
    if require_release_inputs and not ready and not audit.errors:
        missing = []
        if not alias_recorded:
            missing.append("zone-alias")
        if not travel_recorded:
            missing.append("travel")
        lines.append(
            "Publish gate: missing required reviewed input family/families: "
            + ", ".join(missing)
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit reviewed zone-alias/travel release counters against persisted provenance "
            "inside an EverQuestie SQLite knowledge database. The database is opened "
            "read-only and is never rebuilt or modified."
        )
    )
    parser.add_argument("database", help="Builder or finalized EverQuestie SQLite knowledge DB")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable report",
    )
    parser.add_argument(
        "--require-release-inputs",
        action="store_true",
        help=(
            "Return exit code 2 unless both reviewed input families are recorded and "
            "self-consistent. Use this for publishable release artifacts."
        ),
    )
    args = parser.parse_args(argv)

    conn = open_read_only(args.database)
    try:
        db = SimpleNamespace(conn=conn, knowledge_writable=False)
        audit = audit_reviewed_release_inputs(db)
        ready = publish_ready(audit)
        payload = audit.as_dict()
        payload["publish_ready"] = ready
        payload["required_meta_keys"] = list(REVIEWED_RELEASE_META_KEYS)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(audit_text(audit, require_release_inputs=args.require_release_inputs))
    finally:
        conn.close()

    if not audit.ok:
        return 2
    if args.require_release_inputs and not ready:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
