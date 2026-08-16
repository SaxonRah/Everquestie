# Entity profile availability

EverQuestie preserves one complete provenance-rich knowledge corpus and projects server/gameplay availability at read time. This layer is intentionally separate from canonical identity: a fact can remain valid knowledge even when it is not actionable in the selected gameplay profile.

## Decision states

Entity availability is tri-state rather than a simple filter:

- `AVAILABLE` — the current evidence positively supports use in the selected profile;
- `OUTSIDE PROFILE` — direct lifecycle evidence or strong world evidence places the entity outside the selected profile;
- `UNDETERMINED` / `MIXED` — the corpus does not currently support a safe yes/no lifecycle claim.

The implementation must prefer `UNDETERMINED` to inventing an era.

## Evidence precedence

Profile availability now has two evidence layers, in order:

1. **direct entity lifecycle evidence** — explicit top-level `expansion`, `expansion_name`, or `era` fields already compiled into the entity or its canonical structured detail;
2. **canonical world evidence fallback** — authoritative zones, safe canonical locations, explicit normalized zone relationships, and structured quest-step zones.

This order matters. A Classic item that also drops in a modern Live zone is still old content if an explicit source expansion field says `Classic`; its modern drop location does not redefine when it was introduced. Conversely, a modern NPC with an explicit post-Velious expansion statement is not made P99-compatible merely because another source places it in an older zone.

Only explicit top-level lifecycle fields are accepted. Expansion words in descriptions, names, dates, nested arbitrary metadata, or free-form prose are not promoted into lifecycle truth.

Current normalized sources already make this useful without a schema change:

- structured Allakhazam NPC rows can carry `data_json.expansion`;
- zone rows already use expansion evidence in the world-profile layer;
- rich MCP/entity detail records are eligible only when the actual stored `detail_json` contains an explicit expansion field.

An upstream interface allowing an expansion field is not itself evidence. EverQuestie classifies only the record bytes actually compiled into the knowledge database.

## Conflicting direct lifecycle evidence

If two direct source statements land on opposite sides of the P99 Velious boundary, EverQuestie reports `MIXED / UNDETERMINED` instead of picking a preferred source silently.

Direct lifecycle evidence is stronger than location fallback, but conflicting direct lifecycle evidence is not resolved by location.

## World evidence fallback

When no definitive direct entity lifecycle evidence exists, the projection may consume only canonical world facts that are already safe runtime evidence:

- authoritative canonical zone identity;
- safe canonicalized entity-location evidence;
- explicit normalized zone relationships (`occurs_in`, `starts_in`, `found_in`);
- structured quest-step zone fields.

Provider candidate, ambiguous, unresolved, or unmapped zone evidence is never promoted merely to classify an entity.

## Entity-kind policy

Zones use the world-profile zone decision directly.

When no direct lifecycle field exists, quests and NPCs are world-bound enough that all known direct canonical zones being blocked may support an `OUTSIDE PROFILE` decision.

Items, spells, recipes, skills, and other portable/system entities require stronger lifecycle evidence. A currently known drop/vendor/location in a blocked zone does not prove that the entity itself is absent from the selected server era, so those cases stay `UNDETERMINED`.

Once an item or spell actually carries an explicit source-backed expansion field, it can be classified directly rather than through location.

Live intentionally does not use origin expansion alone as retirement evidence. Knowing that an item originated in Classic does not prove that it still exists on the current Live server. Live retirement/removal needs separate lifecycle evidence or reviewed overrides.

## Quest state boundary

Gameplay profile changes recommendation text, not observed history.

A tracked quest whose active structured step points into a blocked zone remains tracked, and matching log observations continue to advance its progress. EverQuestie suppresses the misleading travel recommendation and explains the profile conflict instead of deleting state.

## Read-only lifecycle audit

Builders can measure existing direct lifecycle coverage without rescanning sources or modifying the database:

```powershell
python .\tools\audit_profile_lifecycle.py .\dist\everquestie-knowledge.sqlite3
python .\tools\audit_profile_lifecycle.py .\dist\everquestie-knowledge.sqlite3 --json
```

The audit opens SQLite with `mode=ro&immutable=1` and reports:

- entities with direct expansion/era evidence;
- evidence rows by entity kind;
- evidence rows by source kind;
- common explicit expansion values;
- direct P99 available/blocked/conflict counts.

It deliberately excludes locations and prose so the report answers only how much strong lifecycle evidence is already in the shipped corpus.

## Runtime storage

The selected profile remains writable user metadata. Availability projection reads the immutable knowledge snapshot plus that user preference and does not mutate knowledge.
