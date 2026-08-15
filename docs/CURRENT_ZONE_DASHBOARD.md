# Current-zone knowledge dashboard

EverQuestie's Travel surface includes an actionable `What's here…` view for the
currently selected or live zone. The dashboard is a read-only player projection over
existing canonical `ZoneContext`; it is not another importer, search index, map owner or
pathfinder.

## Zone ownership

Travel owns choosing the current/selected zone. The dashboard asks `ZoneContext` to
resolve that token using the same canonical zone rules used elsewhere.

If zone identity is ambiguous, the dashboard refuses to open a chooser. It does not use
an NPC name, a coordinate, a map filename, or provider evidence to break the ambiguity.

## Evidence-backed entities

The dashboard aggregates normalized zone relationship facts by exact entity ID.
Supported structured roles include, among other normalized knowledge:

- NPCs known in the zone;
- items associated with the zone;
- quests starting in the zone; and
- quests occurring in the zone.

If several facts point at the same exact entity, their role labels, source provenance,
relationship IDs and preview markers are retained on one dashboard row.

Allakhazam preview rows remain explicitly preview evidence. The dashboard never claims
that a provider preview is a complete spawn, item or quest inventory.

Independent `LocationEvidence` is also included. An entity that has a confirmed
location row but no zone-relationship row may appear as `Located here`; the dashboard
does not invent a stronger semantic role for it.

Selecting a dashboard row hands its exact entity ID to the existing Knowledge owner.
Knowledge remains responsible for entity display, relationship browsing, quest
tracking, source opening, Map location and remote Travel routing.

## Neighboring-zone evidence

`ZoneContext` may contain several travel evidence rows for the same canonical neighbor.
This is expected after finalization when, for example, explicit map evidence and
provider Connected Zones evidence independently describe the same transition.

The dashboard therefore aggregates travel evidence by exact canonical neighboring-zone
ID for presentation only.

For each neighbor it retains:

- all underlying edge IDs;
- all direction/connection-kind role labels;
- all source labels; and
- all evidence strings.

The underlying `zone_travel_edges` graph is not modified or deduplicated.

A neighboring zone is considered a usable exit in the dashboard when at least one
underlying edge is usable from the current zone. It is considered mappable when at
least one usable edge has explicit X/Y owned by the current source zone.

An incoming-only edge remains visible as evidence but never becomes a usable or
mappable exit merely because its opposite endpoint stores coordinates.

This keeps the same coordinate-ownership rule used by Route Guidance and `Map next
hop`.

## UI boundary

`What's here…` renders the evidence summary in Travel and opens a small chooser built
entirely from precomputed exact-ID dashboard rows.

The chooser does not:

- query or fuzzy-resolve names;
- search hidden developer tabs;
- inspect provider source files;
- resolve local map files;
- calculate a route; or
- convert coordinates.

After a player chooses a row, Travel invokes the composed app's exact-ID Knowledge
handoff. The normal Knowledge selection then owns all subsequent actions.

## Runtime architecture

The projection works against both the writable builder database and finalized immutable
`RuntimeDatabase` views. Normal packaged use performs no knowledge write, provider
reconciliation, mirror scan, map-catalog rebuild, MCP call, Node.js invocation or
source checkout operation.

The shipped `everquestie-knowledge.sqlite3` remains immutable, and player state remains
separate in `everquestie-user.sqlite3`.
