# Allakhazam-backed knowledge build

EverQuestie's packaged runtime must not scrape or reinterpret source websites. Allakhazam is therefore a **builder-only knowledge provider**: saved mirror pages are parsed into normalized entities, relationships and provenance, then snapshot finalization compiles canonical gameplay projections and removes builder-local paths.

## One build, one acceptance report

`tools/build_knowledge_db.py` can combine the installed EverQuest client, a local Allakhazam mirror and approved map packs in one fresh build. After finalization it automatically evaluates the difficult real-route acceptance suite against the immutable snapshot.

Example on Windows PowerShell:

```powershell
python .\tools\build_knowledge_db.py `
  --working-db .\build\working.sqlite3 `
  --snapshot-db .\dist\everquestie-knowledge.sqlite3 `
  --version 2026.08.15 `
  --eq-install "C:\EverQuest" `
  --allakhazam-mirror "D:\AllakhazamMirror\everquest.allakhazam.com" `
  --allakhazam-version "2026-08-15" `
  --map-pack "Brewall=C:\EQ Maps\Brewall" `
  --map-version "Brewall=2026-08" `
  --route-report .\build\route-acceptance.json
```

Repeat `--map-pack NAME=PATH` for each approved independent map source.

The route report currently includes the representative real canonical endpoint families established for the travel project: The Hole → Labyrinth of Spite, Paineel → The Hole, Stonebrunt Mountains → Paineel, Greater Faydark → The Hole, and Stone Hive → North Freeport.

The default acceptance list deliberately uses literal EQ-client zone display names. Synthetic zones used by long/gated unit tests are never treated as real release endpoints, and the audit does not add aliases or fuzzy matching merely to make a route query resolve.

## Source boundary

The Allakhazam provider calls the existing `AllakhazamImporter` over the selected local HTTrack mirror. It records normal `source_pages` provenance and preserves structured relationships such as Connected Zones. An optional `--allakhazam-version` value is attached to imported source pages so a released knowledge artifact can state which mirror capture produced its facts.

Snapshot finalization then performs the existing conservative pipeline:

1. reconcile provider-owned zone identities against canonical EQ-client-backed zones;
2. reconcile map/zone identities and map-derived travel;
3. compile structured Allakhazam Connected Zones relationships into the shared canonical travel graph;
4. apply provider-travel v2 direction semantics (`Both`, exact `Entrance To`, exact `Exit From`);
5. compute coverage/connectivity diagnostics;
6. strip builder-local paths and runtime/player state;
7. publish the immutable knowledge snapshot.

The runtime receives only that finalized database. It does not need the mirror and does not parse source HTML.

## Route acceptance is read-only

The post-build acceptance audit opens the finalized snapshot with SQLite `mode=ro&immutable=1`. This is intentionally stronger than ordinary read-only mode: finalization already guarantees the snapshot has no WAL dependency, and the audit should not create sidecars or mutate the artifact it is evaluating.

Failures are diagnostic states rather than permission to invent travel:

- unresolved or ambiguous canonical endpoint identity;
- disconnected graph components;
- same weak component but blocked directed reachability;
- other explicitly classified topology gaps.

The pathfinder still uses only confirmed canonical edges. The acceptance report tells the builder which real-data gap to fix next.

## Gating a release

By default the build prints route acceptance but does not fail solely because the real topology is still incomplete. During active data completion this is useful because the JSON report becomes the work queue.

When the known-data graph is mature enough to make those cases release requirements, add:

```powershell
--require-route-acceptance
```

Any failed acceptance case will then return exit code `2`.

For narrow provider/debug iteration, `--skip-route-audit` disables the post-finalization route audit. It cannot be combined with `--route-report` or `--require-route-acceptance`.

## What this does not claim

Passing the synthetic and integration tests proves the builder/import/finalization/routing architecture. It does **not** claim that a particular developer mirror already contains every transition required for every representative route. The real `route-acceptance.json` produced from that mirror is the source of truth for the next topology-completion pass.
