# EverQuestie tools

These commands are builder/developer tooling. Normal EverQuestie users should not need them for a packaged release.

## Build a release knowledge database

The source-agnostic coordinator creates a fresh working database from the providers explicitly selected for that build, then finalizes a separate distributable snapshot:

```powershell
python .\tools\build_knowledge_db.py `
  --working-db .\build\working.sqlite3 `
  --snapshot-db .\dist\everquestie-knowledge.sqlite3 `
  --version 2026.08.14 `
  --eq-install "C:\EverQuest" `
  --map-pack "Brewall=C:\EQ Maps\Brewall" `
  --map-version "Brewall=2026-08"
```

Add a second `--map-pack NAME=PATH` for Good or another approved map source. MCP enrichment is optional builder infrastructure: add `--mcp-repository PATH` only when that build needs it. It requires `--eq-install` because the MCP snapshot is generated from that installation.

The coordinator itself has a provider registry. Today the default providers are `eqclient`, `mcp`, and `map-pack`. A future Allakhazam DB/Wiki mirror can register new providers against the same normalized EverQuestie DB without turning those mirrors into runtime dependencies or requiring the coordinator to be redesigned.

## Build or refresh the global map catalog

For a map-only/manual refresh, run explicitly from the repository root:

```powershell
python .\tools\build_map_catalog.py --db .\build\working.sqlite3 --maps "C:\EQ Maps\Brewall" --source-name Brewall --source-version 2026-08
```

Run the command once per approved map pack/source. Catalog rows store portable relative map keys, not builder-machine file paths, so the database can later ship with EverQuestie. The user's local map root is only needed when opening/rendering the corresponding map file.

## Finalize a distributable knowledge snapshot

If the working database was populated separately, finalize from a **copy** of it:

```powershell
python .\tools\finalize_knowledge_snapshot.py --input .\build\working.sqlite3 --output .\dist\everquestie-knowledge.sqlite3 --version 2026.08.14
```

The finalizer leaves the input database untouched. The output has player/session rows and builder-local paths removed, map links reconciled, FTS rebuilt, separate knowledge schema/content versions recorded, SQLite integrity checked, WAL sidecars eliminated, and the file vacuumed/optimized. A non-portable legacy map path is a release-blocking error rather than something the tool silently packages.

Allakhazam DB/Wiki mirrors are not prerequisites for this process. If those providers are available in a future build, their normalized records and provenance can be present before finalization just like any other source.

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
