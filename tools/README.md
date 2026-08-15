# EverQuestie tools

These commands are builder/developer tooling. Normal EverQuestie users should not need them for a packaged release.

## Build a complete Windows release

Once the builder database contains the map catalog and other knowledge you want to ship, use the release coordinator rather than manually copying the working database:

```powershell
.\tools\build_release.ps1 `
  -Version 2026.08.14 `
  -WorkingDb "$HOME\.eqquest\eqquest.sqlite3"
```

or from `cmd.exe`:

```cmd
.\tools\build_release.cmd -Version 2026.08.14 -WorkingDb "%USERPROFILE%\.eqquest\eqquest.sqlite3"
```

If `-WorkingDb` is omitted, the command uses the normal source-checkout builder database at `~/.eqquest/eqquest.sqlite3`.

The release command performs the distribution boundary in one operation:

1. copies/finalizes the working database into an immutable, versioned `everquestie-knowledge.sqlite3`;
2. reruns canonical mechanics, map, zone and travel reconciliation as part of snapshot finalization;
3. strips player/session rows, builder-local paths and builder-only payloads;
4. rebuilds FTS, checks identity/integrity, removes WAL dependence and optimizes the snapshot;
5. runs the complete regression suite;
6. builds the Windows application with PyInstaller;
7. places the knowledge snapshot beside `EverQuestie.exe` in the default one-folder build;
8. writes `release-manifest.json` with SHA-256 hashes and confirms that neither the builder DB nor a user-state DB is included;
9. creates a versioned Windows ZIP suitable for distribution.

The default output is `release/<version>/EverQuestie/` plus `EverQuestie-<version>-windows.zip`. The one-folder layout is preferred because future updates can replace the application and immutable knowledge snapshot independently while preserving each player's writable `everquestie-user.sqlite3`.

Use `-OneFile` only when a single executable is specifically desired. In that mode the finalized knowledge snapshot is embedded in the executable. `-PythonExe PATH` can pin a specific Python interpreter; otherwise the release command resolves one interpreter once and uses it for finalization, tests, and PyInstaller so multi-Python Windows installations cannot silently switch environments mid-build.

`-SkipTests` exists for developer iteration but should not be used for a publishable release. `-Force` replaces an existing output directory for the same version; it never overwrites the working builder database.

## Build a release knowledge database from providers

The source-agnostic coordinator creates a fresh working database from the providers explicitly selected for that build, then finalizes a separate distributable snapshot. The local Allakhazam HTTrack mirror is a first-class builder provider, so the same build can combine exact client zone identity, Allakhazam world/quest relationships, and approved map packs before finalization:

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

Add a second `--map-pack NAME=PATH` for Good or another approved map source. MCP enrichment is optional builder infrastructure: add `--mcp-repository PATH` only when that build needs it. It requires `--eq-install` because the MCP snapshot is generated from that installation.

The default provider registry is `eqclient`, `allakhazam-mirror`, `mcp`, and `map-pack`. Allakhazam remains builder-only: its saved pages are normalized into EverQuestie's database and snapshot finalization strips builder-local file paths while retaining source provenance. Packaged runtime never scans the mirror or imports source HTML.

After finalization, `build_knowledge_db.py` automatically runs the difficult real-route acceptance suite against the immutable snapshot. That suite currently asks for The Hole → Labyrinth of Spite, Paineel → The Hole, Stonebrunt Mountains → Paineel, Greater Faydark → The Hole, and Stone Hive → North Freeport. The literals are real canonical client zone names; synthetic stress-test zones do not belong in this release audit. Failures are diagnostics, not invented routes: unresolved identities, directionality blocks, and disconnected topology remain explicit.

`--route-report PATH` writes route acceptance as machine-readable JSON. `--provider-travel-frontier-report PATH` writes a second JSON report for the unique resolved source/target zones involved in topology-shaped failures (`disconnected`, `directionality_blocked`, or `route_inconsistency`). It reuses the finalized provider-zone bindings, stored Connected Zones relationships and production provider-travel compiler semantics from the same immutable snapshot. It does not re-import source pages, rebuild topology, or guess missing edges.

Together the two files form the preferred travel-completion work queue: the route report says which player journeys fail, while the provider frontier report says whether those failed endpoints are missing structured provider topology, blocked by canonical bindings, unexpectedly uncompiled, or already compiled and therefore require investigation elsewhere.

`--require-route-acceptance` makes any failing case return exit code 2 when the data is ready to become a release gate. `--skip-route-audit` is available for narrow builder iteration and cannot be combined with either report option or the release gate.

## Build or refresh the global map catalog

For a map-only/manual refresh, run explicitly from the repository root:

```powershell
python .\tools\build_map_catalog.py --db .\build\working.sqlite3 --maps "C:\EQ Maps\Brewall" --source-name Brewall --source-version 2026-08
```

Run the command once per approved map pack/source. Catalog rows store portable relative map keys, not builder-machine file paths, so the database can later ship with EverQuestie. The user's local map root is only needed when opening/rendering the corresponding map file.

`Map catalog ready` means the catalog/reconciliation work is persisted in the builder database. It does **not** mean the builder database itself should be distributed. Run `build_release.ps1` (or explicitly finalize a snapshot) to create the immutable file users receive.

## Finalize a distributable knowledge snapshot

If the working database was populated separately and you only need the knowledge artifact, finalize from a **copy** of it:

```powershell
python .\tools\finalize_knowledge_snapshot.py --input .\build\working.sqlite3 --output .\dist\everquestie-knowledge.sqlite3 --version 2026.08.14
```

The finalizer leaves the input database untouched. The output has player/session rows and builder-local paths removed, canonical mechanics/map/zone/travel knowledge reconciled, FTS rebuilt, separate knowledge schema/content versions recorded, SQLite integrity checked, WAL sidecars eliminated, and the file vacuumed/optimized. A non-portable legacy map path is a release-blocking error rather than something the tool silently packages.

Allakhazam is optional rather than a runtime prerequisite. When an Allakhazam mirror is selected in a provider build, its normalized records and provenance are compiled before this finalization boundary just like the client and map sources.

## MCP setup

MCP is builder/developer infrastructure. If a knowledge build currently needs it, from the EverQuestie repository root on Windows run:

```powershell
.\tools\setup_mcp_submodule.cmd
```

or directly:

```powershell
.\tools\setup_mcp_submodule.ps1
```

The helper initializes the pinned `third_party/everquest1-mcp` Git submodule, runs `npm install`, and builds the MCP project. `-Update` fetches upstream metadata while retaining the commit pinned by the EverQuestie checkout unless `-Ref <tag-or-commit>` is supplied.