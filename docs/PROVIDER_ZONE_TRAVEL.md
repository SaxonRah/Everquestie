# Provider zone travel topology

EverQuestie's runtime route graph is source-agnostic. Map labels and structured provider
zone graphs are builder evidence that compile into the same canonical
`zone_travel_edges` table.

`ProviderZoneTravelCatalog` compiles provider `connected_to` relationships only after
provider-zone reconciliation is complete.

## Identity gate

Every endpoint must already be safe in canonical gameplay identity space:

- an EQ-client-backed zone can be used directly; or
- a provider zone must have a `zone_provider_bindings.status='linked'` binding.

Candidate, ambiguous and unresolved provider zones do not enter the runtime route graph.
The topology compiler does not use the relationship itself to break an identity tie.

## Evidence gate

A generic `connected_to` row is not automatically travel evidence.

- Allakhazam `Connected Zones` rows are accepted because they come from the structured
  zone-page table parser. Older imported rows may predate the explicit confidence flag.
- Other/future provider rows must carry `data_json.confidence='structured'`.
- Rows without source provenance or rows marked inferred are ignored.

The original provider relationship remains intact. The compiled edge stores its source
page, source name/kind/key/version, evidence text, provider relationship ID, provider
endpoint IDs/names/external IDs, and original relationship data.

## Directionality

A provider relationship is compiled exactly in its stored source → target direction.

One Allakhazam page saying Stone Hive is connected to Blightfire Moors therefore creates
one canonical Stone Hive → Blightfire Moors edge. It does **not** imply the reverse edge
and it is not stored as `bidirectional=1`.

If a second structured provider page independently stores Blightfire Moors → Stone Hive,
the graph contains two directed evidence rows. Runtime routing can then traverse both
directions because both directions are actually supported.

## Coordinates

Provider Connected Zones currently does not supply a safe source-side `/loc` for the
zone transition. The compiled edge therefore has no `x`, `y` or `z` coordinate.

EverQuestie never invents a map target from provider topology. A map-label edge for the
same direction may independently provide source-owned coordinates and route guidance can
prefer that more actionable evidence without changing the canonical path.

## Snapshot/runtime boundary

Snapshot finalization runs the provider topology compiler after provider-zone identity
reconciliation and map travel compilation, then computes release zone coverage over the
combined graph.

The packaged `RuntimeDatabase` only reads those finalized edges. It does not import
Allakhazam, inspect mirrors, reconcile provider identities, or compile topology.
