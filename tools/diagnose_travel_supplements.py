from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import traceback

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.approved_travel_supplements import approved_travel_manifest_paths
from eqquest.db import Database
from eqquest.travel_supplement import TravelSupplementImporter


DEFAULT_WORKING_DB = REPO_ROOT / "build" / "working.sqlite3"
DEFAULT_SUPPLEMENT_DIR = REPO_ROOT / "builder-data" / "travel-supplements"


def _sqlite_clone(source: Path, target: Path) -> None:
    source_conn = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reproduce approved travel-supplement compilation against a disposable "
            "clone of an existing builder DB. The source DB is never modified."
        )
    )
    parser.add_argument(
        "--working-db",
        default=str(DEFAULT_WORKING_DB),
        help="Existing provider-built working DB to clone.",
    )
    parser.add_argument(
        "--supplement-dir",
        default=str(DEFAULT_SUPPLEMENT_DIR),
        help="Approved travel supplement directory.",
    )
    parser.add_argument(
        "--keep-debug-db",
        help="Optional path to retain the disposable diagnostic clone.",
    )
    args = parser.parse_args(argv)

    source = Path(args.working_db).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"working DB not found: {source}")

    manifests = approved_travel_manifest_paths(args.supplement_dir)
    keep_path = (
        Path(args.keep_debug_db).expanduser().resolve()
        if args.keep_debug_db
        else None
    )

    with tempfile.TemporaryDirectory(prefix="everquestie-travel-debug-") as tempdir:
        clone = Path(tempdir) / "travel-debug.sqlite3"
        print(f"[travel-debug] cloning: {source}")
        _sqlite_clone(source, clone)

        db = Database(clone)
        importer = TravelSupplementImporter(db)
        try:
            for manifest in manifests:
                print(f"[travel-debug] testing: {manifest.name}", flush=True)
                try:
                    result = importer.import_manifest(manifest)
                except Exception:
                    print(
                        f"[travel-debug] FAILED: {manifest.name}",
                        file=sys.stderr,
                        flush=True,
                    )
                    traceback.print_exc()
                    if keep_path is not None:
                        keep_path.parent.mkdir(parents=True, exist_ok=True)
                        db.close()
                        shutil.copy2(clone, keep_path)
                        print(
                            f"[travel-debug] retained diagnostic DB: {keep_path}",
                            file=sys.stderr,
                        )
                        return 2
                    return 2
                print(
                    "[travel-debug] PASS: "
                    f"{manifest.name} edges={result.edges} "
                    f"bidirectional={result.bidirectional_edges} "
                    f"requirements={result.requirements}",
                    flush=True,
                )
        finally:
            try:
                db.close()
            except Exception:
                pass

        if keep_path is not None:
            keep_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(clone, keep_path)
            print(f"[travel-debug] retained diagnostic DB: {keep_path}")

    print("[travel-debug] all approved travel supplements compiled successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
