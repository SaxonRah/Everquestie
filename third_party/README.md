# Third-party source trees

`third_party/everquest1-mcp` points at:

`https://github.com/ArtSabintsev/everquest1-mcp.git`

Run:

```powershell
.\tools\setup_mcp_submodule.ps1
```

The helper supports both EverQuestie distribution forms:

- **Git checkout:** installs/initializes `third_party/everquest1-mcp` as a real Git submodule.
- **Downloaded ZIP:** a ZIP cannot carry the parent repository's `160000` gitlink, so the helper creates a normal nested clone at the exact same path and builds it. EverQuestie uses that clone identically at runtime.

Use `-Update` only when you explicitly want the helper to update an existing MCP checkout/clone. `-Ref <tag-or-commit>` can select a particular upstream ref before building.

EverQuestie also honors `EVERQUEST1_MCP_PATH` if the MCP repository lives elsewhere.

The MCP server is not required while monitoring EverQuest. It is used only for explicit MCP searches and as an optional parser/reference dependency.
