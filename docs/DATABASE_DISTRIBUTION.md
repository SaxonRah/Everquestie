# EverQuestie database distribution architecture

## Release principle

A normal EverQuestie user must not need `everquest1-mcp`, Node.js, a source checkout, a website mirror, a map-catalog build, or a local database compilation step to use the shipped knowledge base.

Source adapters are **builder/developer inputs**. EverQuestie owns the normalized schema and release artifacts.

## Runtime storage layout

EverQuestie has two independent SQLite roles:

1. **Shipped knowledge snapshot** — versioned, immutable EverQuestie knowledge produced by the release pipeline as `everquestie-knowledge.sqlite3`.
2. **User state database** — writable local state in `everquestie-user.sqlite3`, including observed log events, tracked quest progress, settings-backed bindings and other player-specific state.

Packaged runtime opens the knowledge snapshot read-only/immutable and exposes its tables through runtime views while keeping player state writable in the separate user DB. Replacing a shipped knowledge snapshot must never delete or recreate player state.

Source-checkout/developer mode can still use a writable combined builder database such as `~/.eqquest/eqquest.sqlite3`. That builder file is an input to the release process and must never be distributed as the packaged runtime database.

## Knowledge inputs and future providers

Development proceeds without waiting for the Allakhazam DB or Wiki mirrors. Current builders can populate knowledge from the installed EverQuest client, map packs, MCP-derived local snapshots, and any other approved deterministic source available to the project.

Allakhazam DB and Wiki are **optional future enrichment providers**. When those mirrors become available they plug into the same generic provenance and identity model (`source_pages`, `entity_sources`, and namespaced `entity_external_ids`) rather than requiring a new runtime database design.

The project owner has confirmed authority to incorporate and distribute information gathered from the approved project resources. Provenance is retained for reconciliation, auditing, refreshes, and conflict analysis; it is not a runtime distribution gate.

## Map catalog placement

The normalized global map catalog belongs in the shipped knowledge snapshot.

Catalog construction is performed once by the builder or by an explicit manual developer action. Normal application startup must not crawl or rebuild Good/Brewall/EverQuest map packs.

`map_sources` and `map_labels` persist portable map-pack identity (`source_name`, optional `source_version`, and a relative `source_key`). Reconciled labels retain their original coordinates/text plus canonical entity linkage status. Ambiguous/unresolved labels remain evidence but are never promoted into factual locations merely to increase coverage.

Canonical `zone_map_bindings` and compiled travel evidence make map stems/topology part of the shipped knowledge graph. The map files themselves remain rendering assets; the database does not need to duplicate every line segment merely to preserve searchable POI knowledge.

A user's selected map directory is different: it is a local rendering asset and belongs in writable user settings/state. At runtime EverQuestie can resolve a shipped catalog map identity against the player's selected map root when the matching file is present.

This separation lets the shipped DB answer global map/POI searches and `WHERE` location queries even when a player has never indexed anything locally.

`tools/audit_map_catalog.py` is the read-only publication check for this boundary. It validates the catalog already stored in a knowledge database; it never opens map-pack directories or changes the database. The Windows release builder requires the finalized snapshot to contain versioned `Goods` and `Brewall` catalog sources with portable source keys/URIs, base maps, and indexed labels before packaging can continue.

## Unified location evidence

EverQuestie deliberately preserves the difference between source facts and reconciled map evidence:

- provider/importer coordinates remain in `entity_locations`;
- confirmed Good/Brewall/native-map POIs remain in `map_labels` with `linked_entity_id` and source provenance.

The runtime location projection reads both as `LocationEvidence` in normalized game X/Y/Z coordinates. It converts native map coordinates only at read time and excludes ambiguous/unresolved map links. Player-facing `WHERE` queries can therefore combine map and provider locations without duplicating rows or losing provenance. Future mirror providers can add location evidence through the same canonical entity identities.

## Runtime behavior

Normal gameplay remains local and deterministic. Runtime EverQuestie should:

- read the shipped knowledge snapshot locally;
- write player/session state only to the user's local database;
- use the prebuilt global map catalog for map evidence/search/location queries;
- use a selected local Good/Brewall/EQ map directory only for rendering and optional user bindings;
- never require MCP, Allakhazam DB, or Allakhazam Wiki to be present;
- never perform a hidden source rebuild on startup;
- never rebuild shipped FTS or map knowledge on a player machine;
- never make background website requests.

Explicit online Search remains a separate user-triggered feature where available in developer workflows; packaged runtime does not depend on it.

## Release build pipeline

For an existing builder database, `tools/build_release.ps1` is the preferred Windows distribution boundary. It performs the following sequence in one explicit operation:

1. stage the builder DB into a separate release-working copy and compile approved release supplements;
2. finalize that staged copy into an immutable `everquestie-knowledge.sqlite3`;
3. audit recorded reviewed zone-alias/travel inputs against evidence inside the finalized snapshot;
4. audit the finalized snapshot's already-built global map catalog, requiring versioned `Goods` and `Brewall` sources without crawling or rebuilding either map pack;
5. run the finalized-snapshot route acceptance gate;
6. run the complete regression suite;
7. build the Windows application and attach the finalized snapshot;
8. emit a release manifest with hashes and both verified immutable-artifact contracts;
9. package the application and finalized snapshot into the versioned Windows ZIP.

The snapshot finalization/staging machinery remains responsible for canonical reconciliation, FTS rebuilding, integrity/identity checks, stripping user/session state and builder-only payloads, recording snapshot metadata, and eliminating WAL-sidecar dependence. Release publication consumes the resulting finalized artifact; it does not reconstruct source catalogs during packaging.

The default one-folder Windows layout keeps `everquestie-knowledge.sqlite3` beside `EverQuestie.exe`. This is intentional: a future updater can replace application/knowledge artifacts while leaving `everquestie-user.sqlite3` untouched. A one-file build may embed the immutable snapshot when specifically requested.

For a clean provider-driven build, `tools/build_knowledge_db.py` can first create the working knowledge DB from selected providers. For a map-only refresh, `tools/build_map_catalog.py` remains an explicit builder action. For snapshot-only work, `tools/finalize_knowledge_snapshot.py` remains available.

The installer/first-run path creates the writable user-state database automatically. Users should not see MCP setup, mirror setup, map catalog compilation, FTS rebuilding, or other builder infrastructure as prerequisites.

## Development tooling

MCP/client compilers, map-catalog builders, Allakhazam importers, Wiki importers, and future source adapters may remain available as developer/advanced tooling. They enrich the same EverQuestie-owned knowledge model; none is individually required for the application to function.
