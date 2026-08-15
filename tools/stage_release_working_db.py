from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.approved_travel_supplements import (
    stage_builder_with_approved_travel_supplements,
)


DEFAULT_SUPPLEMENT_DIR = REPO_ROOT / "builder-data" / "travel-supplements"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Clone an EverQuestie builder DB with SQLite backup semantics and compile "
            "all repository-approved travel supplements into the staged clone."
        )
    )
    p.add_argument("--input", required=True, help="Source writable builder SQLite database")
    p.add_argument("--output", required=True, help="Staged writable builder SQLite database")
    p.add_argument(
        "--supplement-dir",
        default=str(DEFAULT_SUPPLEMENT_DIR),
        help="Approved travel supplement directory",
    )
    p.add_argument("--force", action="store_true", help="Replace an existing staged output")
    p.add_argument("--json", action="store_true", help="Emit machine-readable result JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    progress = None if args.json else print
    try:
        results = stage_builder_with_approved_travel_supplements(
            args.input,
            args.output,
            args.supplement_dir,
            overwrite=bool(args.force),
            progress=progress,
        )
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc

    payload = {
        "input": str(Path(args.input).expanduser().resolve()),
        "output": str(Path(args.output).expanduser().resolve()),
        "supplement_dir": str(Path(args.supplement_dir).expanduser().resolve()),
        "manifests": len(results),
        "edges": sum(result.edges for result in results),
        "bidirectional_edges": sum(result.bidirectional_edges for result in results),
        "requirements": sum(result.requirements for result in results),
        "sources": [
            {
                "source_name": result.source_name,
                "source_version": result.source_version,
                "edges": result.edges,
                "bidirectional_edges": result.bidirectional_edges,
                "requirements": result.requirements,
            }
            for result in results
        ],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "release staging complete: "
            f"manifests={payload['manifests']}, edges={payload['edges']}, "
            f"bidirectional_edges={payload['bidirectional_edges']}, "
            f"requirements={payload['requirements']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
