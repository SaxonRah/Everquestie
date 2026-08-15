# NPC expansion reconciliation

EverQuestie's Allakhazam NPC parser records the explicit page-level `Expansion` field
in structured NPC metadata. The installed EverQuest client independently exposes the
canonical expansion inventory through `dbstr_us.txt` type 20, imported as
`eqclient:expansion` identities.

NPC expansion reconciliation connects those two evidence layers during knowledge
build/finalization so packaged users receive normal graph relationships without any
runtime provider dependency.

## Output relationship

For a structured Allakhazam NPC expansion field, the builder may compile:

`npc -> expansion | introduced_in_expansion`

Each compiler-owned relationship preserves:

- the Allakhazam NPC source page as provenance;
- the exact raw expansion name;
- `source_field=Expansion`;
- `confidence=structured`;
- `derived_from=npc_expansion_reconciliation`; and
- the exact identity policy used for the target.

The original `data_json['expansion']` value remains on the NPC entity. Reconciliation
adds a graph edge; it does not replace or discard provider metadata.

## Conservative expansion identity

A raw expansion name links only when its normalized canonical name matches **exactly
one** expansion entity with an `eqclient:expansion` identity.

Consequently:

- a provider-only same-name expansion does not compete with the unique client target;
- two client-backed same-name expansions are ambiguous and do not link;
- a missing client expansion remains unresolved; and
- no substring, fuzzy, nearest-name, numeric-ID, or provider-ID fallback is used.

Ambiguous and unresolved names remain raw structured NPC evidence for later source or
identity improvements.

## Source contract

The first compiler intentionally reads only NPC entities whose primary source page is
Allakhazam.

`data_json['expansion']` is currently an explicit structured contract of the
Allakhazam NPC parser. Arbitrary future-provider NPC JSON is not silently treated as an
expansion authority. A future provider can gain equivalent graph normalization once it
has an explicit structured source contract.

## Idempotent rebuild ownership

Before compiling current source evidence, reconciliation removes only
`introduced_in_expansion` relationships whose payload contains:

`derived_from = npc_expansion_reconciliation`

Curated/manual edges and future compilers using the same relation vocabulary survive.
If source metadata changes or disappears, stale compiler-owned edges disappear on the
next build while unrelated graph knowledge and the provider NPC record remain intact.

## Finalization and runtime

`finalize_knowledge_snapshot()` runs NPC expansion reconciliation after canonical
client identity/mechanics reconciliation and quest-faction reconciliation, before the
provider-zone/map/travel catalogs and FTS finalization.

`KnowledgeSnapshotReport.npc_expansion_reconciliation` records:

- NPCs scanned;
- structured expansion names encountered;
- linked names;
- ambiguous names;
- unresolved names; and
- stale compiler-owned edges removed.

The release finalization CLI prints those counts next to the other reconciliation
coverage.

Packaged runtime does not parse Allakhazam, read `dbstr_us.txt`, invoke MCP/Node, or run
this reconciler. `RuntimeDatabase` simply exposes the finalized ordinary
`entity_relationships` row through immutable knowledge views. Player state remains
separate in `everquestie-user.sqlite3`.
