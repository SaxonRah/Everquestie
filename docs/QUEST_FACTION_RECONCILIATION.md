# Quest faction reconciliation

EverQuestie's Allakhazam quest parser already extracts the explicit `Factions Raised`
and `Factions Lowered` fields into structured quest metadata. The client/MCP knowledge
snapshot independently provides canonical `faction` entities.

Quest faction reconciliation connects those two evidence layers during **knowledge
build/finalization** so packaged users receive normal source-aware graph relationships
without any runtime provider dependency.

## Output relationships

For a structured Allakhazam quest field, the builder may compile:

- `quest -> faction | raises_faction`; or
- `quest -> faction | lowers_faction`.

Each compiler-owned relationship preserves:

- the Allakhazam quest source page as provenance;
- the exact raw faction name from the source field;
- the source-field label (`Factions Raised` / `Factions Lowered`);
- `confidence=structured`;
- `derived_from=quest_faction_reconciliation`; and
- the identity policy used to select the target.

The raw `factions_raised` / `factions_lowered` arrays remain on the quest entity. The
compiler does not replace or discard provider evidence.

## Conservative faction identity

A raw faction name links only when its normalized canonical name matches **exactly one**
client-backed faction entity with an `eqclient:faction` external identity.

This deliberately means:

- a provider-only same-name faction does not compete with the unique client target;
- two client-backed same-name factions are ambiguous and do not link;
- a missing client faction remains unresolved; and
- no substring, fuzzy, numeric-ID or nearest-name fallback is used.

Ambiguous and unresolved raw names remain visible in the quest's structured metadata so
future source enrichment can reconcile them without losing evidence.

## Source contract

The first compiler intentionally reads only quest entities whose primary source page is
`Allakhazam`.

Today the `factions_raised` / `factions_lowered` keys are an explicit structured
contract of the Allakhazam quest parser. A future provider can gain equivalent graph
normalization once it has its own structured source contract; arbitrary third-party
quest JSON is not silently reinterpreted as faction authority.

## Idempotent rebuild ownership

Reconciliation is rebuildable. Before compiling the current structured quest data it
removes only faction relationships whose relationship payload contains:

`derived_from = quest_faction_reconciliation`

Native provider relationships, curated/manual faction edges, and future compilers using
the same relation vocabulary are not removed.

If a quest source changes, stale compiler-owned edges disappear on the next build while
the original quest metadata and unrelated graph facts remain intact.

## Finalization and runtime

`finalize_knowledge_snapshot()` runs quest faction reconciliation after canonical client
mechanics/identities are available and before FTS finalization.

The resulting relationships are ordinary rows in `entity_relationships` and therefore
work through the same packaged read projections as every other world relationship.
Normal runtime does not:

- invoke Allakhazam or read a mirror;
- invoke MCP or Node.js;
- run faction reconciliation;
- mutate faction/quest identity; or
- write to the immutable knowledge snapshot.

`RuntimeDatabase` simply exposes the finalized relationships through read-only knowledge
views while player state remains separate in `everquestie-user.sqlite3`.

## Release diagnostics

`KnowledgeSnapshotReport.quest_faction_reconciliation` reports:

- quests scanned;
- structured faction names encountered;
- linked names;
- ambiguous names;
- unresolved names; and
- stale compiler-owned edges removed during the rebuild.

These counts describe reconciliation coverage; ambiguous/unresolved names are retained
evidence, not release failures.
