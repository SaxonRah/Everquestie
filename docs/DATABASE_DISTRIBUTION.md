# EverQuestie database distribution architecture

## Release principle

A normal EverQuestie user must not need `everquest1-mcp`, Node.js, a source checkout, a website mirror, or a local database compilation step to use the shipped knowledge base.

Source adapters are **builder/developer inputs**. EverQuestie owns the normalized schema and release artifacts.

## Target release layout

EverQuestie is moving toward two SQLite roles:

1. **Shipped knowledge snapshot** — versioned, read-only/read-mostly EverQuestie knowledge produced by the release pipeline.
2. **User state database** — writable local state such as observed log events, tracked quest progress, settings, map-root selection, manual bindings, view state, and user overrides.

Replacing a shipped knowledge snapshot must never delete or recreate player state.

The current v0.13 development database still combines these roles in one SQLite file. Do not silently overwrite that file with a release snapshot until the content/user-state split or a safe upgrader exists.

## Knowledge inputs and future providers

Development must proceed without waiting for the Allakhazam DB or Wiki mirrors. Current builders can populate knowledge from the installed EverQuest client, map packs, MCP-derived local snapshots, and any other approved deterministic source available to the project.

Allakhazam DB and Wiki are **optional future enrichment providers**. When those mirrors become available they plug into the same generic provenance and identity model (`source_pages`, `entity_sources`, and namespaced `entity_external_ids`) rather than requiring a new runtime database design.

The project owner has confirmed authority to incorporate and distribute information gathered from the approved project resources. Provenance is retained for reconciliation, auditing, refreshes, and conflict analysis; it is not a runtime distribution gate.

## Map catalog placement

The normalized global map catalog belongs in the shipped knowledge snapshot.

Catalog construction is performed once by the builder or by an explicit manual developer action. Normal application startup must not crawl or rebuild Good/Brewall/EverQuest map packs.

`map_sources` and `map_labels` persist portable map-pack identity (`source_name`, optional `source_version`, and a relative `source_key`). They must not require a builder-machine absolute path after the snapshot is built.

A user's selected map directory is different: it is a local rendering asset and belongs in writable user state/settings. At runtime EverQuestie can resolve a catalog `source_key` against that local map root when the matching map file is present.

This separation lets the shipped DB answer global map/POI searches even when a player has not locally indexed anything.

## Runtime behavior

Normal gameplay remains local and deterministic. Runtime EverQuestie should:

- read the shipped knowledge snapshot locally;
- write player/session state only to the user's local database;
- use the prebuilt global map catalog for map evidence/search;
- use a selected local Good/Brewall/EQ map directory only for rendering and optional user overrides;
- never require MCP, Allakhazam DB, or Allakhazam Wiki to be present;
- never perform a hidden source rebuild on startup;
- never make background website requests.

Explicit online Search remains a separate user-triggered feature.

## Release build pipeline

Before a packaged release, the reproducible builder should:

1. create a fresh EverQuestie knowledge database;
2. import all currently available approved source inventories (with Allakhazam DB/Wiki optional);
3. build/refresh the global map catalog explicitly;
4. run identity and relationship reconciliation;
5. rebuild FTS;
6. run database integrity and identity audits;
7. strip user/session state and builder-local paths;
8. record source versions, build timestamp, schema version, and knowledge snapshot version;
9. `VACUUM`/optimize the SQLite file;
10. run the complete regression suite against that snapshot;
11. package the snapshot with the Windows application.

The installer/first-run path creates the writable user-state database automatically. Users should not see MCP setup, mirror setup, map catalog compilation, or other builder infrastructure as prerequisites.

## Development tooling

MCP/client compilers, map-catalog builders, Allakhazam importers, Wiki importers, and future source adapters may remain available as developer/advanced tooling. They enrich the same EverQuestie-owned knowledge model; none is individually required for the application to function.
