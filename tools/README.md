# EverQuestie tools

## MCP setup

From the EverQuestie repository root on Windows:

```powershell
.\tools\setup_mcp_submodule.cmd
```

or directly:

```powershell
.\tools\setup_mcp_submodule.ps1
```

The helper initializes the pinned `third_party/everquest1-mcp` Git submodule, runs `npm install`, and builds the MCP project. `-Update` fetches upstream metadata while retaining the commit pinned by the EverQuestie checkout unless `-Ref <tag-or-commit>` is supplied.
