# Entity profile availability

EverQuestie preserves one complete provenance-rich knowledge corpus and projects server/gameplay availability at read time. This layer is intentionally separate from canonical identity: a fact can remain valid knowledge even when it is not actionable in the selected gameplay profile.

## Decision states

Entity availability is tri-state rather than a simple filter:

- `AVAILABLE` — the current evidence positively supports use in the selected profile;
- `OUTSIDE PROFILE` — strong direct world evidence places a zone-defined entity outside the selected profile;
- `UNDETERMINED` / `MIXED` — the corpus does not currently support a safe yes/no lifecycle claim.

The implementation must prefer `UNDETERMINED` to inventing an era.

## Evidence boundary

The current entity projection consumes only canonical world facts that are already safe runtime evidence:

- authoritative canonical zone identity;
- safe canonicalized entity-location evidence;
- explicit normalized zone relationships (`occurs_in`, `starts_in`, `found_in`);
- structured quest-step zone fields.

Provider candidate, ambiguous, unresolved, or unmapped zone evidence is never promoted merely to classify an entity.

## Entity-kind policy

Zones use the world-profile zone decision directly.

Quests and NPCs are world-bound enough that all known direct canonical zones being blocked may support an `OUTSIDE PROFILE` decision.

Items, spells, recipes, skills, and other portable/system entities require stronger lifecycle evidence. A currently known drop/vendor/location in a blocked zone does not prove that the entity itself is absent from the selected server era, so those cases stay `UNDETERMINED`.

## Quest state boundary

Gameplay profile changes recommendation text, not observed history.

A tracked quest whose active structured step points into a blocked zone remains tracked, and matching log observations continue to advance its progress. EverQuestie suppresses the misleading travel recommendation and explains the profile conflict instead of deleting state.

## Runtime storage

The selected profile remains writable user metadata. Availability projection reads the immutable knowledge snapshot plus that user preference and does not mutate knowledge.
