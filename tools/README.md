# EverQuestie tools

These commands are builder/developer tooling. Normal EverQuestie users should not need them for a packaged release.

## Build a complete Windows release

Once the builder database contains the map catalog and other knowledge you want to ship, use the release coordinator rather than manually copying or finalizing the working database:

```powershell
.\tools\build_release.ps1 `
  -Version 2026.08.15 `
  -WorkingDb .\build\working.sqlite3
```

or from `cmd.exe`:

```cmd
.\tools\build_release.cmd -Version 2026.08.15 -WorkingDb ".\build\working.sqlite3"
```

If `-WorkingDb` is omitted, the command uses the source-checkout builder database at `build/working.sqlite3`. It no longer defaults to the legacy `~/.eqquest/eqquest.sqlite3` runtime database.

The release command performs the distribution boundary in one operation:

1. clones the source builder database into a release staging database using SQLite backup semantics, so committed WAL content is included and the source DB is never modified;
2. compiles every reviewed `builder-data/travel-supplements/*.json` manifest into that staged builder copy;
3. finalizes the staged copy into an immutable, versioned `everquestie-knowledge.sqlite3`;
4. reruns canonical mechanics, map, zone and travel reconciliation as part of snapshot finalization;
5. strips player/session rows, builder-local paths and builder-only payloads, rebuilds FTS, checks identity/integrity, removes WAL dependence and optimizes the snapshot;
6. runs the current-live canonical route-acceptance suite as a hard release gate;
7. runs the complete regression suite;
8. builds the Windows application with PyInstaller and attaches the finalized knowledge snapshot;
9. writes `release-manifest.json` with SHA-256 hashes and records that approved travel supplements were compiled and route acceptance was verified;
10. creates a versioned Windows ZIP suitable for distribution.

The default output is `release/<version>/EverQuestie/` plus `EverQuestie-<version>-windows.zip`. The one-folder layout is preferred because future updates can replace the application and immutable knowledge snapshot independently while preserving each player's writable `everquestie-user.sqlite3`.

Use `-OneFile` only when a single executable is specifically desired. In that mode the finalized knowledge snapshot is embedded in the executable. `-PythonExe PATH` can pin a specific Python interpreter; otherwise the release command resolves one interpreter once and uses it for staging, finalization, audits, tests, and PyInstaller so multi-Python Windows installations cannot silently switch environments mid-build.

`-SkipTests` and `-SkipRouteAudit` exist for developer iteration but should not be used for a publishable release. `-Force` replaces an existing output directory for the same version; it never overwrites the working builder database.

## Build a release knowledge database from providers

The source-agnostic coordinator creates a fresh working database from the providers explicitly selected for that build, compiles repository-approved travel supplements, then finalizes a separate distributable snapshot. The local Allakhazam HTTrack mirror is a first-class builder provider, so the same build can combine exact client zone identity, Allakhazam world/quest relationships, approved map packs, optional MCP enrichment, and reviewed supplemental travel evidence before finalization:

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
  --route-report .\build\route-acceptance.json `
  --provider-travel-frontier-report .\build\provider-travel-frontier.json
```

Add a second `--map-pack NAME=PATH` for Good or another approved map source. MCP enrichment is optional builder infrastructure: add `--mcp-repository PATH` only when that build needs it. It requires `--eq-install` because the MCP snapshot is generated from that installation. Canonical MCP builds also require the selected checkout to match `third_party/everquest1-mcp.lock.json`; `build_knowledge_db.py` verifies the locked repository, commit, and package version before importing MCP data.

The default provider registry is `eqclient`, `allakhazam-mirror`, `mcp`, and `map-pack`. Allakhazam remains builder-only: its saved pages are normalized into EverQuestie's database and snapshot finalization strips builder-local file paths while retaining source provenance. Packaged runtime never scans the mirror or imports source HTML.

After finalization, `build_knowledge_db.py` automatically runs the difficult current-live route acceptance suite against the immutable snapshot. That suite currently asks for The Hole → Labyrinth of Spite, Paineel → The Hole, Stonebrunt Mountains → Paineel, Greater Faydark → The Hole, and Stone Hive → West Freeport. The literals are real canonical client zone names; historical identities remain in the knowledge database but are not automatically treated as current-live acceptance targets. Failures are diagnostics, not invented routes: unresolved identities, directionality blocks, and disconnected topology remain explicit.

`--route-report PATH` writes route acceptance as machine-readable JSON. `--provider-travel-frontier-report PATH` writes a second JSON report for the unique resolved source/target zones involved in topology-shaped failures (`disconnected`, `directionality_blocked`, or `route_inconsistency`). It reuses the finalized provider-zone bindings, stored Connected Zones relationships and production provider-travel compiler semantics from the same immutable snapshot. It does not re-import source pages, rebuild topology, or guess missing edges.

Together the two files form the preferred travel-completion work queue: the route report says which player journeys fail, while the provider frontier report says whether those failed endpoints are missing structured provider topology, blocked by canonical bindings, unexpectedly uncompiled, or already compiled and therefore require investigation elsewhere.

`--require-route-acceptance` makes any failing case return exit code 2 when the data is ready to become a release gate. `--skip-route-audit` is available for narrow builder iteration and cannot be combined with either report option or the release gate.

## Stage an existing builder database for release

If a working database was populated separately — for example through manual MCP, Allakhazam, client, or map imports — do **not** finalize it directly for packaging. First create a staged copy with all approved travel manifests compiled:

```powershell
python .\tools\stage_release_working_db.py `
  --input .\build\working.sqlite3 `
  --output .\build\release-working.sqlite3 `
  --force
```

This uses SQLite's backup API, leaves the source builder DB untouched, and fails if any approved travel manifest cannot resolve against the staged canonical identities. `build_release.ps1` performs this staging step automatically.

## Build or refresh the global map catalog

For a map-only/manual refresh, run explicitly from the repository root:

```powershell
python .\tools\build_map_catalog.py --db .\build\working.sqlite3 --maps "C:\EQ Maps\Brewall" --source-name Brewall --source-version 2026-08
```

Run the command once per approved map pack/source. Catalog rows store portable relative map keys, not builder-machine file paths, so the database can later ship with EverQuestie. The user's local map root is only needed when opening/rendering the corresponding map file.

`Map catalog ready` means the catalog/reconciliation work is persisted in the builder database. It does **not** mean the builder database itself should be distributed. Run `build_release.ps1` to stage approved supplements, verify route acceptance, and create the immutable file users receive.

## Finalize a distributable knowledge snapshot

The low-level finalizer operates on exactly the database you give it; it does **not** discover or compile repository travel manifests. For a release-quality snapshot from an existing builder DB, stage first:

```powershell
python .\tools\stage_release_working_db.py `
  --input .\build\working.sqlite3 `
  --output .\build\release-working.sqlite3 `
  --force

python .\tools\finalize_knowledge_snapshot.py `
  --input .\build\release-working.sqlite3 `
  --output .\dist\everquestie-knowledge.sqlite3 `
  --version 2026.08.15 `
  --force

python .\tools\audit_route_acceptance.py `
  .\dist\everquestie-knowledge.sqlite3 `
  --full-paths `
  --fail-unreachable
```

The finalizer leaves its input database untouched. The output has player/session rows and builder-local paths removed, canonical mechanics/map/zone/travel knowledge reconciled, FTS rebuilt, separate knowledge schema/content versions recorded, SQLite integrity checked, WAL sidecars eliminated, and the file vacuumed/optimized. A non-portable legacy map path is a release-blocking error rather than something the tool silently packages.

Allakhazam is optional rather than a runtime prerequisite. When an Allakhazam mirror is selected in a provider build, its normalized records and provenance are compiled before this finalization boundary just like the client, maps, and approved travel supplements.

## MCP builder source setup

MCP is builder/developer infrastructure only. Normal EverQuestie launch and packaged runtime never bootstrap MCP, Node.js, npm, or a third-party source checkout.

When a knowledge build needs MCP enrichment, initialize the repository-locked nested builder source from the EverQuestie repository root:

```powershell
.\tools\setup_mcp_builder_source.cmd
```

or directly:

```powershell
.\tools\setup_mcp_builder_source.ps1
```

The tracked contract lives at `third_party/everquest1-mcp.lock.json`. Setup verifies the approved upstream repository, checks out the exact locked commit, runs `npm install`, and builds the builder source. `-Update` refreshes upstream refs without moving the canonical lock. `-Ref <tag-or-commit>` is an explicit developer override; canonical knowledge builds reject an unlocked checkout.

Verify the local checkout without fetching, checking out, installing, or building anything:

```powershell
python .\tools\verify_mcp_builder_source.py
```

The historical `setup_mcp_submodule.*` and `verify_submodule.ps1` filenames remain compatibility aliases only; EverQuestie no longer uses a parent-repository Git submodule for MCP.

## Source-checkout runtime launcher

A source checkout can be launched without MCP:

```cmd
.\tools\run_source_app.cmd
```

The legacy `run_with_submodule.cmd` filename remains only as a compatibility alias and no longer initializes, installs, verifies, or builds MCP. It simply launches the source application.


## Rebuilding from a clean mirror with unverified HTTrack provenance

The canonical full build still requires HTTrack evidence that belongs to the selected
project and proves a naturally completed crawl. The audit now reads the HTTrack
`-O1` output directory from `hts-log.txt` when present; a log copied from a different
HTTrack project is reported as stale/mismatched and is not allowed to prove the current
mirror either complete or interrupted.

For development or corpus inspection, a captured corpus can still be imported explicitly
when all of the following are true:

- no `hts-in_progress.lock` is present;
- the HTTrack log is readable;
- the mirror contains zero temporary HTTrack files;
- completion provenance is either an interrupted run for this project or a stale/mismatched
  `hts-log.txt` from another HTTrack output project.

Use the explicit developer override:

```powershell
.\tools\build_full_knowledge.ps1 -AllowUnverifiedMirror
```

`-AllowInterruptedMirror` remains an alias for the same switch.

The generated build version is suffixed `-full-unverified-mirror`. The mirror audit
JSON records `canonical_complete: false`, the reason completion provenance could not
be verified, and whether the clean-corpus override was accepted. The final console
summary also warns that the snapshot is not canonical crawl-complete. Do not publish
such a snapshot as a crawl-complete release artifact until matching completion evidence
is recovered.

You do not need to run the cleanup script again after a completion-gate failure that
occurred before the database build stage.

## Builder path resolution

The full knowledge build reads the same `%USERPROFILE%\.eqquest\settings.ini`
used by the EverQuestie UI for local source paths. Before starting a long rebuild,
you can print exactly what the builder will use:

```powershell
python .\tools\resolve_builder_paths.py
```

The resolver reads:

- `everquest_install`
- `allakhazam_db_mirror`
- `mcp_repository`
- `map_root`

For Allakhazam, `allakhazam_db_mirror` may point either to the HTTrack project
directory or directly to its `everquest.allakhazam.com` child; the builder derives
both paths. For maps, a parent maps directory or either Good's/Brewall pack directory
is accepted and the sibling pack is derived.

## Clean full knowledge rebuild

The canonical full build already writes a new `build\working.sqlite3.building`
database and atomically replaces the old working DB only after provider compilation
succeeds. For an explicit cleanup of generated artifacts before a from-scratch build:

```powershell
.\tools\clean_knowledge_build.ps1
.\tools\build_full_knowledge.ps1
```

Default cleanup removes the canonical builder DB/snapshot, SQLite sidecars, temporary
builder DB, and full-build audit reports. It deliberately preserves source inputs and
all player state.

Useful opt-in cleanup switches:

```powershell
# Also delete the legacy mutable DB used by plain source-checkout launches.
.\tools\clean_knowledge_build.ps1 -IncludeSourceCheckoutDb

# Also delete packaged writable player state (tracked quests, observed history, bindings).
.\tools\clean_knowledge_build.ps1 -IncludeUserState

# Also remove generated release staging/output directories.
.\tools\clean_knowledge_build.ps1 -IncludeReleaseArtifacts

# Deliberate total local DB/release reset while preserving source inputs/settings.
.\tools\clean_knowledge_build.ps1 `
  -IncludeSourceCheckoutDb `
  -IncludeUserState `
  -IncludeReleaseArtifacts
```

The cleanup helper never deletes the EQ installation, Allakhazam HTTrack mirror,
everquest1-mcp checkout, Good/Brewall map packs, or `%USERPROFILE%\.eqquest\settings.ini`.

After rebuilding, test the new finalized database with:

```powershell
.\tools\run_packaged.ps1
```

Do not use plain `py EverQuestie.py` to validate a freshly built runtime snapshot
unless you intentionally want source-checkout mode; that launcher may use
`%USERPROFILE%\.eqquest\eqquest.sqlite3` instead of the new `dist` snapshot.

## Full-corpus performance smoke

Use the synthetic fixture when you want a repeatable large knowledge corpus without depending on a local Allakhazam mirror:

```powershell
python .\tools\create_performance_smoke_fixture.py `
  --working-db .\build\perf-working.sqlite3 `
  --snapshot-db .\build\perf-knowledge.sqlite3 `
  --entities 50000 `
  --aliases-per-entity 2 `
  --force
```

The fixture includes 50,000 filler entities by default, two aliases per filler, and a small exact NPC/item/quest chain named `Performance Rat`, `Performance Token`, and `Performance Quest`. It compiles the same Activity Pathway catalog used by release snapshots and finalizes an immutable runtime knowledge DB.

Benchmark the finalized snapshot without modifying it:

```powershell
python .\tools\benchmark_runtime_performance.py `
  .\build\perf-knowledge.sqlite3 `
  --iterations 10 `
  --json-out .\build\perf-after.json
```

The benchmark creates temporary user-state databases and reports median/min/max timings for runtime DB open, local search, first Live projection, steady-state Live projection, first loot refresh, steady-state loot refresh, and one-new-event loot refresh. It also records snapshot size and result counts so a suspiciously fast empty lookup is visible.

For the real full-Allakhazam release snapshot, provide representative names that exist in that corpus:

```powershell
python .\tools\benchmark_runtime_performance.py `
  .\dist\everquestie-knowledge.sqlite3 `
  --query "Bone Chips" `
  --loot-item "Bone Chips" `
  --kill-npc "a decaying skeleton" `
  --zone "South Qeynos" `
  --iterations 10 `
  --json-out .\build\full-allakhazam-after.json
```

To compare against an older build, benchmark the old snapshot into a baseline JSON first, then pass `--baseline-json PATH`. The output adds median millisecond and percentage deltas for metrics present in both runs. Keep real-corpus benchmark JSON under `build/` or another local artifact directory unless it is intentionally being added as release evidence.
