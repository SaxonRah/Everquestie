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

from eqquest.allakhazam_normalization_delta import (
    allakhazam_normalization_delta,
    allakhazam_normalization_delta_text,
)


def _load_json(path: str | Path) -> dict[str, object]:
    report_path = Path(path).expanduser().resolve()
    if not report_path.is_file():
        raise FileNotFoundError(report_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("mirror audit JSON must contain a top-level object")
    return payload


def _open_read_only(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    # Immutable mode prevents even zero-byte WAL/SHM sidecars from being created by a
    # read-only artifact audit. It must never ignore uncheckpointed builder writes, so
    # fail closed when a non-empty WAL is present and require the caller to close or
    # checkpoint that builder DB first. Finalized release snapshots already guarantee
    # that they have no WAL dependency.
    wal = Path(str(db_path) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError(
            "knowledge DB has a non-empty WAL; close/checkpoint the builder database "
            "or audit the finalized snapshot"
        )

    conn = sqlite3.connect(
        db_path.as_uri() + "?mode=ro&immutable=1",
        uri=True,
    )
    conn.row_factory = sqlite3.Row
    return conn


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
            "Compare an existing Allakhazam mirror inventory JSON artifact with the "
            "Allakhazam source pages and normalized derivatives stored in a quiescent "
            "EverQuestie knowledge DB. The mirror itself is never scanned."
        )
    )
    parser.add_argument(
        "mirror_audit",
        help="JSON report previously emitted by tools/audit_allakhazam_mirror.py --output",
    )
    parser.add_argument(
        "database",
        help=(
            "Finalized or closed/checkpointed builder EverQuestie SQLite knowledge DB; "
            "a non-empty WAL is rejected"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable report",
    )
    parser.add_argument(
        "--output",
        help="Also write the machine-readable JSON report atomically to this path",
    )
    args = parser.parse_args(argv)

    try:
        mirror_payload = _load_json(args.mirror_audit)
        conn = _open_read_only(args.database)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Allakhazam normalization delta setup failed: {exc}", file=sys.stderr)
        return 2

    try:
        db = SimpleNamespace(conn=conn)
        try:
            report = allakhazam_normalization_delta(db, mirror_payload)
        except (ValueError, sqlite3.Error) as exc:
            print(f"Allakhazam normalization delta failed: {exc}", file=sys.stderr)
            return 2
        payload = report.as_dict()
        if args.output:
            _write_json_report(args.output, payload)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(allakhazam_normalization_delta_text(report))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
