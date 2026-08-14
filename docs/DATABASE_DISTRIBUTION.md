# EverQuestie database distribution architecture

## Release principle

A normal EverQuestie user must not need `everquest1-mcp`, Node.js, a source checkout, or a local database compilation step in order to use the shipped knowledge base.

`everquest1-mcp` and other source adapters are **builder/developer inputs**. EverQuestie owns its normalized schema and release artifacts.

## Target release layout

EverQuestie should move toward two SQLite roles:

1. **Shipped content snapshot** — versioned, read-mostly EverQuestie knowledge produced by the release/build pipeline.
2. **User state database** — writable local state such as observed log events, tracked quest progress, map-pack indexing/linkage, manual bindings, and other machine/user-specific data.

Keeping those roles separate lets a new EverQuestie release replace or upgrade the shipped knowledge snapshot without deleting a player's history or tracked-quest state.

The current v0.13 development database still combines these roles in one SQLite file. Do not silently overwrite that file with a release snapshot until the content/user-state split or a safe merge/upgrader exists.

## Builder inputs

The release builder may use source adapters such as:

- installed EverQuest client files;
- `everquest1-mcp` local parsers/compiler support;
- permitted local Allakhazam imports;
- other explicitly permitted/local deterministic sources.

These are evidence inputs only. The published artifact is an EverQuestie-owned SQLite schema, not an MCP database.

Only material for which redistribution is permitted should be included in a public shipped snapshot. Permission to locally mirror or parse a source must not automatically be treated as permission to redistribute it.

## Runtime behavior

Normal gameplay remains local and deterministic. Runtime EverQuestie should:

- read the shipped content snapshot locally;
- write player/session state only to the user's local database;
- index the user's selected Good/Brewall/EQ map pack into the user database;
- reconcile map evidence against shipped/local normalized knowledge;
- never require MCP to be running;
- never make background website requests.

Explicit online Search remains a separate user-triggered feature.

## Map catalog placement

`map_sources` / `map_labels` are derived from the user's selected local map pack and therefore belong in writable user state, not the immutable shipped content snapshot.

Entity links from map labels may be recomputed when the shipped knowledge version changes.

## Release build pipeline

Before a public packaged release, add a reproducible builder that:

1. creates a fresh EverQuestie knowledge database;
2. imports approved source inventories;
3. runs identity/relationship reconciliation;
4. rebuilds FTS;
5. runs database integrity and identity audits;
6. strips user/session state;
7. records source versions, build timestamp, schema version, and knowledge snapshot version;
8. VACUUMs/optimizes the SQLite file;
9. runs the complete regression suite against that snapshot;
10. packages the snapshot with the Windows application.

The installer/first-run path should then create the writable user-state database automatically. Users should not see MCP setup as part of the normal installation path.

## Development tooling

The current MCP/client compilation controls may remain available as developer/advanced-source tooling while EverQuestie is being built, but they should not be presented as a prerequisite for a normal release install.
