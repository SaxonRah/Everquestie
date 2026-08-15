# NPC and quest world entity context

EverQuestie exposes a read-only entity-centric projection over finalized knowledge so
NPCs, quests and items can be understood as part of the world graph without requiring
runtime source parsing.

## Conservative identity resolution

`build_world_entity_context()` accepts only:

- an exact canonical entity name; or
- an exact stored alias.

A unique substring is not promoted to identity. If multiple entities have the same
exact name or alias, the result remains ambiguous.

This is intentionally stricter than a discovery/search UI. Context projection should
not become more confident merely because today's corpus happens to contain one partial
match.

## Relationship facts

The projection reads normalized `entity_relationships` directly and preserves:

- relationship direction;
- the raw relationship name;
- the other entity's ID, kind and name;
- quantity;
- evidence text;
- relationship payload;
- structured/derived markers when present;
- preview/shown/total metadata;
- source page/provider provenance.

Human-readable labels are direction-aware. For example, the canonical forward fact
`item -> npc : drops_from` renders as `Drops from` for the item and `Drops item` for
the NPC. No reverse graph row is manufactured.

The relationship list is explicitly described as evidence-backed and not exhaustive.

## Zone relationships

Provider zone entities remain distinct source entities. When a relationship points to
a zone:

- an EQ-client-backed zone is already canonical;
- a provider zone with a finalized `linked` binding is displayed in the linked gameplay
  zone identity while the provider zone ID remains on the fact;
- `candidate`, `ambiguous`, `unresolved`, and unmapped provider zones remain provider
  evidence only and are not promoted into gameplay identity.

## Location facts

Entity locations preserve the originally stored zone entity and source provenance.
The projection separately records a gameplay-zone target when that target is safe.

A location is `navigable` only when:

1. its stored zone is already EQ-client-backed or safely projects through a finalized
   `linked` provider binding; and
2. both EQ game-space X and Y coordinates are present.

A coordinate-bearing fact in a candidate/unresolved provider zone remains visible as
knowledge, but is marked not map-targetable. EverQuestie does not use coordinates to
break zone identity ambiguity.

## Quest context

Quest context includes normalized `quest_steps` as knowledge facts, not player
progress. This keeps the projection independent from the writable user database.

For directly related NPC actors such as starters, kill targets, source creatures,
turn-in NPCs and conversation targets, the projection can also expose their explicit
`entity_locations`. These actor locations obey the same gameplay-zone safety rule.

## Runtime architecture

The projection performs no writes, reconciliation, import, filesystem scan, or source
lookup. It works through finalized immutable `RuntimeDatabase` views over:

- `entities`;
- `entity_aliases`;
- `entity_external_ids`;
- `entity_sources` / `source_pages`;
- `entity_relationships`;
- `entity_locations`;
- `quest_steps`;
- finalized `zone_provider_bindings`.

The packaged application therefore needs no Allakhazam mirror, Node.js process, MCP
service, or source checkout to provide this context.
