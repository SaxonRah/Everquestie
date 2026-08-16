# Third-party builder source trees

`third_party/everquest1-mcp` is a **builder-only** nested Git checkout of:

`https://github.com/ArtSabintsev/everquest1-mcp.git`

Its reproducible source contract is tracked in:

`third_party/everquest1-mcp.lock.json`

The lock records the exact approved upstream repository, full producer commit, and package version used by canonical EverQuestie knowledge builds. The current lock was recovered from the known-good rich knowledge snapshot's recorded MCP provenance rather than chosen from the upstream default branch.

Run:

```powershell
.\tools\setup_mcp_builder_source.ps1
```

Both a normal Git checkout and a downloaded source ZIP use the same nested-clone layout. Setup clones the approved upstream when necessary and checks out the exact tracked lock revision before installing/building it.

`-Update` refreshes upstream refs but **does not move the canonical builder off the tracked lock**. `-Ref <tag-or-commit>` is an explicit developer override for investigation; canonical/full knowledge builds reject an unlocked checkout.

The historical `setup_mcp_submodule.*` names remain compatibility aliases only. EverQuestie does not rely on a parent-repository Git submodule for MCP.

EverQuestie also honors `EVERQUEST1_MCP_PATH` where supported by builder tooling, but the selected checkout must still match the repository source lock for a canonical build.

Normal EverQuestie users do not need this repository, Node.js, npm, or MCP at runtime. The dependency exists only as builder/developer infrastructure; its compiled knowledge is shipped in the immutable EverQuestie knowledge database.
