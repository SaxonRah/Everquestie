# Map-ready world locations in Knowledge

EverQuestie's Knowledge detail already consumes the canonical entity-ID-based world
projection. This UI layer adds one actionable subset beneath that detail: locations that
are safe to hand to the existing Map owner.

## Parent authority

`world_entity_detail.build_world_entity_context_for_id()` owns selected-entity identity
and the canonical Knowledge detail projection.

The location UI does not re-resolve display names. This matters because distinct NPC
records can legitimately share a name; selecting one Knowledge row must keep that exact
entity identity.

## Map-ready subset

The picker is populated only from:

- `WorldEntityContext.navigable_locations`; and
- `WorldEntityContext.navigable_related_locations` for explicit quest actor evidence.

A location reaches those collections only when it has explicit EQ game-space X/Y and a
safe gameplay-zone identity. The zone must be either EQ-client-backed directly or
project through a finalized `zone_provider_bindings.status='linked'` provider binding.

Provider `candidate`, `ambiguous`, `unresolved`, and unmapped locations remain visible
in the normal Knowledge detail as evidence, but they never receive a map action.
Coordinates never resolve zone ambiguity.

## Map ownership

`Map selected location` sends only:

- canonical gameplay zone name;
- EQ game-space X/Y/Z; and
- a display label

to the existing `_focus_navigation_map_target(...)` boundary installed by runtime map
policy.

Knowledge does not inspect Good/Brewall folders, resolve filenames, choose map variants,
convert coordinates, or draw markers. The Map owner keeps responsibility for:

- checking that the target still belongs to the live current zone;
- local-map readiness and safe variant selection;
- loading the local rendering asset;
- converting EQ game coordinates into map geometry;
- centering and drawing the navigation marker.

This is the same ownership boundary used by Travel and Nearby navigation.

## Runtime architecture

The feature is read-only over finalized knowledge. It performs no provider import,
reconciliation, filesystem scan, MCP/Node invocation, knowledge write, or map-catalog
build.

The shipped knowledge snapshot remains immutable and the writable player database stays
separate.
