# Exact-ID relationship navigation in Knowledge

Packaged EverQuestie hides the developer Search tab, but normalized Knowledge already
contains a rich relationship graph. The Knowledge relationship navigator lets players
follow that graph in place without weakening identity rules or reviving hidden builder
UI.

## User flow

For a selected Knowledge entity, `Open related…` projects its existing normalized
relationship facts and offers the related entities in a small modal chooser.

Examples include:

- quest → starter / objective NPC / quest item;
- NPC → quest / zone / item relationship;
- item → dropper / turn-in NPC / vendor;
- spell → teacher;
- skill → trainer; and
- any other normalized relationship already represented in the shipped graph.

If several relationship facts point at the same entity, the chooser shows that entity
once and aggregates the direction-aware role labels and source provenance.

`Back` walks the in-session relationship-navigation history. The history is UI state
only; it is not persisted into the player database.

## Exact identity

Relationship navigation never resolves a displayed name.

The selected entity is already an exact database ID, and each normalized relationship
has an exact endpoint ID. The world-context projection supplies
`display_other_entity_id`; that ID is carried into the chooser and into the Knowledge
tree selection.

This matters for duplicate NPC names: two distinct `Bixie Scout` entities remain two
distinct choices even though their visible names match.

When a safely linked provider-zone relationship is projected into gameplay space,
`display_other_entity_id` already names the canonical EQ-client-backed zone. The
navigator therefore opens that canonical zone rather than silently opening the
preserved provider row.

Provider-only/candidate entities may still be browsed as knowledge where the world
projection intentionally exposes them. This feature does not turn such entities into
map targets or gameplay-zone authority.

## Lazy Knowledge topics

The Knowledge tree limits very large topic child sets for responsiveness. Exact-ID
relationship navigation must not become approximate because of that display limit.

The navigator first uses the normal filtered Knowledge tree. If the known target ID was
omitted by the lazy child cap, it inserts only that already-proven target row into the
filtered kind node and selects it directly. It never chooses a same-name substitute.

Back history is recorded only after a target was successfully opened.

## Composition with existing actions

Opening a related entity uses the normal Knowledge tree selection. Existing actions
therefore follow the newly selected exact entity automatically:

- Track / Untrack quest;
- Open source; and
- packaged `Map location`, including the current-zone safe chooser introduced by the
  existing Knowledge→Map stack.

The relationship navigator does not duplicate map resolution, current-zone filtering,
location evidence selection, tracking logic, or source opening.

## Runtime architecture

The related-entity projection is read-only over finalized knowledge. It does not:

- import or parse provider sources;
- run provider reconciliation;
- invoke MCP or Node.js;
- scan mirrors or map folders;
- mutate the immutable knowledge snapshot; or
- write navigation history to `everquestie-user.sqlite3`.

Normal users consume only the already-finalized relationship graph shipped in
`everquestie-knowledge.sqlite3`.
