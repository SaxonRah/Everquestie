# EverQuestie tools

These commands are builder/developer tooling. Normal EverQuestie users should not need them for a packaged release.

## Build or refresh the global map catalog

Run explicitly from the repository root:

```powershell
python .\tools\build_map_catalog.py --db .\build\everquestie-knowledge.sqlite3 --maps "C:\EQ Maps\Brewall" --source-name Brewall --source-version 2026-08
```

Run the command once per approved map pack/source. Catalog rows store portable relative map keys, not builder-machine file paths, so the database can later ship with EverQuestie. The user's local map root is only needed when opening/rendering the corresponding map file.

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
