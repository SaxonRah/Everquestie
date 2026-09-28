# EverQuestie Runtime Performance Baseline

This document records the repeatable synthetic performance baseline for the full-Allakhazam performance hardening work.

## Baseline environment

- GitHub Actions: `ubuntu-latest`
- Python: 3.12
- Workflow: `.github/workflows/performance-smoke.yml`
- Performance branch commit: `68fb0593dead9f8d801940ce5402129c36d1cbf2`
- Synthetic filler entities: 20,000
- Synthetic aliases per filler entity: 2
- Release-shaped runtime snapshot size: 13.379 MiB
- Benchmark iterations: 5 for repeated paths

The synthetic fixture deliberately includes one exact NPC/item/quest chain so the Live and loot projections exercise real indexed runtime paths rather than empty-result shortcuts.

## Recorded baseline

| Runtime path | Median |
| --- | ---: |
| Runtime DB open | 11.203 ms |
| Local search | 19.471 ms |
| First Live event projection | 4.889 ms |
| Steady Live projection | 0.118 ms |
| First loot relevance refresh | 0.345 ms |
| Steady loot relevance refresh | 0.104 ms |
| Incremental loot refresh | 0.150 ms |

Observed functional results:

- local search hits: 1
- Activity Pathway suggestions: 1
- loot relevance rows: 1

## Regression policy

The CI workflow uses deliberately loose ceilings intended to catch catastrophic scaling regressions, not ordinary runner variance:

- runtime DB open: 2000 ms
- local search: 2000 ms
- first Live event: 2000 ms
- steady Live projection: 500 ms
- first loot refresh: 2000 ms
- steady loot refresh: 500 ms
- incremental loot refresh: 1000 ms

Raw benchmark JSON is uploaded by the workflow as the `runtime-performance-smoke` artifact. The benchmark tool also accepts `--baseline-json` and reports median deltas, so future performance work can compare against a saved baseline without changing benchmark semantics.

This synthetic baseline does not replace testing against the real full Allakhazam snapshot on the development machine. Its purpose is to make corpus-size regressions reproducible in CI and to prove that the hot paths remain bounded as the normalized knowledge corpus grows.
