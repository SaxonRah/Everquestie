# Provider zone metadata projection

EverQuestie keeps gameplay-zone identity and provider-zone evidence separate.

## Authority boundary

The EQ-client-backed zone entity remains the canonical gameplay identity used by live
zone resolution, maps, travel, nearby navigation, and user state.

A provider zone linked through `zone_provider_bindings.status='linked'` may contribute
source-specific metadata, but that metadata does **not** overwrite the gameplay-zone
row. Conflicting facts are intentionally preserved as separate evidence layers.

For example, if the EQ-client-backed Stone Hive row has level range 40-48 while the
Allakhazam zone page records 44-52, `ZoneContext.level_min/level_max` remain 40-48 and
`ZoneContext.provider_metadata` contains the Allakhazam 44-52 statement with its
source provenance.

## Projected fields

The current Allakhazam structured zone parser can provide:

- level range;
- zone type;
- expansion;
- instanced status;
- keyed status;
- hot-zone flag.

The projection also retains:

- provider zone entity ID/name/external ID;
- gameplay zone entity ID/name;
- source page ID and URL;
- source name/kind/key/version;
- binding reason and corroboration count;
- the provider zone's original normalized `data_json` payload.

Missing fields remain missing. String fields such as `Instanced` and `Keyed` are kept
as the provider recorded them rather than coerced into invented semantics.

## Projection gate

`provider_zone_metadata_for_gameplay_zone()` reads only provider bindings already
finalized as `linked`. `candidate`, `ambiguous`, and `unresolved` provider zones do not
contribute metadata to gameplay context.

The function never performs reconciliation and never writes. Reconciliation remains a
builder/finalization responsibility.

## Runtime behavior

Snapshot finalization already compiles the provider-zone reconciliation catalog. The
packaged runtime reads the finalized binding, provider entity, and source-page rows
through the immutable knowledge database.

No Allakhazam mirror, source parser, Node.js process, MCP service, or runtime database
mutation is required.

`zone_context_text()` labels these values under **Provider zone facts
(source-specific)** so they cannot be confused with canonical client-backed fields.
