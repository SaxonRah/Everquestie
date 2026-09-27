from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
import sys
import tempfile
import time
from typing import Callable, Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.activity_pathways import ActivityPathwayEngine
from eqquest.events import Event
from eqquest.local_search import search_local_hits
from eqquest.loot_relevance import LootSessionObservationIndex, recent_loot_relevance
from eqquest.runtime import RuntimeDatabase


def _measure(fn: Callable[[], Any], iterations: int) -> tuple[dict[str, float], Any]:
    values: list[float] = []
    last = None
    for _ in range(max(1, int(iterations))):
        started = time.perf_counter()
        last = fn()
        values.append((time.perf_counter() - started) * 1000.0)
    return (
        {
            "median_ms": round(median(values), 3),
            "min_ms": round(min(values), 3),
            "max_ms": round(max(values), 3),
            "iterations": len(values),
        },
        last,
    )


def _metric_median(payload: dict, name: str) -> float | None:
    value = payload.get("metrics", {}).get(name, {})
    try:
        return float(value["median_ms"])
    except (KeyError, TypeError, ValueError):
        return None


def _comparison(current: dict, baseline: dict) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for name in current.get("metrics", {}):
        now = _metric_median(current, name)
        before = _metric_median(baseline, name)
        if now is None or before is None or before == 0:
            continue
        result[name] = {
            "baseline_median_ms": round(before, 3),
            "current_median_ms": round(now, 3),
            "delta_ms": round(now - before, 3),
            "delta_percent": round(((now - before) / before) * 100.0, 2),
        }
    return result


def benchmark_snapshot(
    snapshot: str | Path,
    *,
    query: str,
    kill_npc: str,
    loot_item: str,
    zone: str,
    iterations: int = 5,
) -> dict:
    knowledge = Path(snapshot).expanduser().resolve()
    if not knowledge.is_file():
        raise FileNotFoundError(knowledge)

    result: dict[str, Any] = {
        "snapshot": str(knowledge),
        "snapshot_size_mib": round(knowledge.stat().st_size / (1024 * 1024), 3),
        "inputs": {
            "query": query,
            "kill_npc": kill_npc,
            "loot_item": loot_item,
            "zone": zone,
        },
        "metrics": {},
        "observations": {},
    }

    with tempfile.TemporaryDirectory(prefix="everquestie-perf-state-") as tempdir:
        state_root = Path(tempdir)

        # Fresh user-state DB each iteration approximates first-open runtime overhead
        # without ever mutating the immutable knowledge snapshot.
        open_counter = 0

        def open_once():
            nonlocal open_counter
            open_counter += 1
            state = state_root / f"open-{open_counter}.sqlite3"
            db = RuntimeDatabase(knowledge, state, migrate_legacy=False)
            db.close()

        result["metrics"]["runtime_db_open"] = _measure(open_once, iterations)[0]

        state = state_root / "benchmark-user.sqlite3"
        db = RuntimeDatabase(knowledge, state, migrate_legacy=False)
        try:
            search_metric, hits = _measure(
                lambda: search_local_hits(db, query, limit=25),
                iterations,
            )
            result["metrics"]["local_search"] = search_metric
            result["observations"]["search_hits"] = len(hits or ())

            boundary_row = db.conn.execute(
                "SELECT COALESCE(MAX(id),0) AS n FROM observed_events"
            ).fetchone()
            boundary = int(boundary_row["n"] if boundary_row is not None else 0)
            engine = ActivityPathwayEngine(db)
            engine.reset_session(boundary, starting_zone=zone)

            db.add_event(
                Event(
                    kind="kill",
                    raw=f"performance kill: {kill_npc}",
                    actor=kill_npc,
                    target="You",
                )
            )

            def first_live_projection():
                engine.refresh_observations()
                return engine.suggestions(zone, limit=25)

            live_first_metric, suggestions = _measure(first_live_projection, 1)
            result["metrics"]["first_live_event"] = live_first_metric
            result["observations"]["pathway_suggestions"] = len(suggestions or ())

            steady_metric, _ = _measure(
                lambda: (
                    engine.refresh_observations(),
                    engine.suggestions(zone, limit=25),
                ),
                iterations,
            )
            result["metrics"]["steady_live_projection"] = steady_metric

            loot_boundary_row = db.conn.execute(
                "SELECT COALESCE(MAX(id),0) AS n FROM observed_events"
            ).fetchone()
            loot_boundary = int(
                loot_boundary_row["n"] if loot_boundary_row is not None else 0
            )
            loot_index = LootSessionObservationIndex()
            loot_index.reset(loot_boundary)
            db.add_event(
                Event(
                    kind="loot",
                    raw=f"performance loot: {loot_item}",
                    item=loot_item,
                    actor=kill_npc,
                )
            )

            loot_first_metric, relevance = _measure(
                lambda: recent_loot_relevance(
                    db,
                    loot_boundary,
                    limit_items=25,
                    observation_index=loot_index,
                ),
                1,
            )
            result["metrics"]["first_loot_refresh"] = loot_first_metric
            result["observations"]["loot_relevance_rows"] = len(relevance or ())

            loot_steady_metric, _ = _measure(
                lambda: recent_loot_relevance(
                    db,
                    loot_boundary,
                    limit_items=25,
                    observation_index=loot_index,
                ),
                iterations,
            )
            result["metrics"]["steady_loot_refresh"] = loot_steady_metric

            db.add_event(
                Event(
                    kind="loot",
                    raw=f"performance loot 2: {loot_item}",
                    item=loot_item,
                    actor=kill_npc,
                )
            )
            loot_incremental_metric, relevance = _measure(
                lambda: recent_loot_relevance(
                    db,
                    loot_boundary,
                    limit_items=25,
                    observation_index=loot_index,
                ),
                1,
            )
            result["metrics"]["incremental_loot_refresh"] = loot_incremental_metric
            result["observations"]["loot_count_after_second"] = (
                int(relevance[0].observed_count) if relevance else 0
            )
        finally:
            db.close()

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark bounded EverQuestie runtime paths against a finalized knowledge snapshot."
        )
    )
    parser.add_argument("snapshot", help="Finalized everquestie-knowledge.sqlite3")
    parser.add_argument("--query", default="Performance Token")
    parser.add_argument("--kill-npc", default="Performance Rat")
    parser.add_argument("--loot-item", default="Performance Token")
    parser.add_argument("--zone", default="South Qeynos")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json-out")
    parser.add_argument(
        "--baseline-json",
        help="Optional earlier benchmark JSON; adds median delta percentages.",
    )
    args = parser.parse_args(argv)

    payload = benchmark_snapshot(
        args.snapshot,
        query=args.query,
        kill_npc=args.kill_npc,
        loot_item=args.loot_item,
        zone=args.zone,
        iterations=args.iterations,
    )

    if args.baseline_json:
        baseline = json.loads(
            Path(args.baseline_json).expanduser().read_text(encoding="utf-8")
        )
        payload["comparison"] = _comparison(payload, baseline)

    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.json_out:
        output = Path(args.json_out).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
