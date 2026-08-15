# Provider zone world context

EverQuestie can project structured NPC, quest and item relationships from a reconciled
provider zone into the canonical EQ-client gameplay zone without merging the provider
entity or requiring the provider mirror at runtime.

This is a read projection over normalized knowledge already stored in the snapshot. It
does not create another compiled copy of the relationship graph.

## Supported relationship statements

The first world-context projection intentionally uses only normalized entity → zone
relations with unambiguous orientation:

- `found_in` — NPCs/items associated with the zone;
- `starts_in` — quests starting in the zone;
- `occurs_in` — quests occurring in the zone.

Provider `connected_to` relationships are handled separately by the canonical travel
compiler and are not duplicated here.

## Identity gate

Facts stored directly against the canonical gameplay-zone entity remain ordinary
knowledge.

A fact stored against a provider zone crosses into gameplay context only when that
provider zone has a finalized `zone_provider_bindings.status='linked'` binding.

Candidate, ambiguous and unresolved provider zones do not project their relationships.
A same-name provider row is therefore never enough on its own.

## Evidence gate

A safe provider-zone binding does not make every relationship attached to that provider
zone trustworthy.

Provider-crossing facts must themselves be structured source evidence:

- Allakhazam rows are accepted because the supported zone/NPC/item/quest extractors are
  structured parsers; older rows may predate an explicit confidence marker;
- other/future providers must mark the normalized relationship
  `data_json.confidence='structured'`;
- inferred rows and rows without source provenance are excluded from provider
  projection.

This prevents identity confidence from laundering weak relationship evidence into
player-facing truth.

## Canonical identity and provenance

`ZoneRelatedEntity.zone_entity_id` / `zone_name` always describe the canonical gameplay
zone presented to the player.

The normalized relationship's original zone identity is retained separately as:

- `original_zone_entity_id` / `original_zone_name`;
- `projected_from_zone_entity_id` when the fact crossed a provider binding.

Source name/kind/key/version, source page, evidence text, confidence and the original
relationship payload are also retained.

## Preview semantics

Allakhazam zone pages expose several tab tables as previews rather than exhaustive
lists. Their normalized relationships already carry `preview`, `shown` and `total`
metadata, and the world-context projection preserves those values.

Player-facing text therefore labels NPC/quest/item sections as **evidence-backed; not
exhaustive** and renders preview counts when known. A `25 of 342` preview is never
presented as though the zone contains exactly 25 NPCs.

## Locations are separate

A relationship statement is not a coordinate. `found_in` can establish that an NPC or
item is associated with a zone, but it does not create a `/loc` or map target.

`entity_locations` and linked map labels remain the coordinate-bearing evidence used by
Nearby and map handoff. The richer relationship context augments world knowledge without
weakening those navigation rules.

## Snapshot/runtime boundary

Provider-zone reconciliation happens builder-side before finalization. Relationship
projection itself is read-only and operates over the finalized normalized graph plus the
shipped provider-zone bindings.

`RuntimeDatabase` therefore exposes the same NPC/quest/item context from immutable
knowledge without importing Allakhazam, opening a mirror, running a parser, or writing a
knowledge row.
