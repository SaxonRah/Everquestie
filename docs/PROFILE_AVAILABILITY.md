# Entity profile availability

EverQuestie preserves one complete provenance-rich knowledge corpus and projects server/gameplay availability at read time. This layer is intentionally separate from canonical identity: a fact can remain valid knowledge even when it is not actionable in the selected gameplay profile.

## Decision states

Entity availability is tri-state rather than a simple filter:

- `AVAILABLE` — the current evidence positively supports use in the selected profile;
- `OUTSIDE PROFILE` — reviewed direct lifecycle evidence or strong world evidence places the entity outside the selected profile;
- `UNDETERMINED` / `MIXED` — the corpus does not currently support a safe yes/no lifecycle claim.

The implementation must prefer `UNDETERMINED` to inventing an era.

## Evidence precedence

Profile availability has two evidence layers, in order:

1. **reviewed direct entity lifecycle evidence** — explicit top-level `expansion`, `expansion_name`, or `era` fields whose source + entity kind + field + parser semantics have been approved for lifecycle use;
2. **canonical world evidence fallback** — authoritative zones, safe canonical locations, explicit normalized zone relationships, and structured quest-step zones.

This order matters. A Classic item that also drops in a modern Live zone is still old content if a reviewed explicit source expansion field says `Classic`; its modern drop location does not redefine when it was introduced. Conversely, a modern NPC with reviewed post-cap expansion evidence is not made compatible with an older expansion-capped profile merely because another source places it in an older zone.

A lifecycle-looking key is not evidence by name alone. Expansion words in descriptions, names, dates, nested arbitrary metadata, free-form prose, source-less normalized rows, or unreviewed structured-detail fields are not promoted into lifecycle truth.

Current reviewed direct entity lifecycle inputs are deliberately narrow:

- Allakhazam local-mirror NPC `Expansion` → normalized `data_json.expansion`;
- Allakhazam local-mirror zone `Expansion` → normalized `data_json.expansion`;
- Allakhazam local-mirror item metadata `Expansion` → normalized `data_json.expansion`;
- Allakhazam local-mirror quest `Era` → normalized `data_json.era`.

Zone availability also has its separate reviewed world-profile evidence/override layer.

### MCP spell boundary

`everquest1-mcp` remains valuable builder input for local identities and rich mechanics, but its rich detail JSON is **not** currently a reviewed direct lifecycle source.

The repository-locked MCP 1.2.1 implementation does not populate an expansion field in its local spell record. Its `getClassSpellsByExpansion()` helper labels its groups as approximate expansion eras and derives them from hard-coded class minimum-level ranges. EverQuestie therefore does not promote an MCP rich-detail key named `expansion` into spell-era truth.

A future MCP/source revision must be reviewed at the field/parser-semantic level before it can be added to the lifecycle source policy. Merely adding an `expansion` property to an interface or payload is not sufficient.

## Conflicting direct lifecycle evidence

If two **reviewed** direct source statements land on opposite sides of the active expansion-capped profile's boundary, EverQuestie reports `MIXED / UNDETERMINED` instead of picking a preferred source silently.

P99 is currently the only visible expansion-capped profile, so its active boundary is Velious. The classifier itself is profile-owned and can support a future reviewed Luclin/PoP/TLP cap without changing the lifecycle source-trust rules.

Reviewed direct lifecycle evidence is stronger than location fallback, but conflicting reviewed direct lifecycle evidence is not resolved by location.

## World evidence fallback

When no definitive reviewed direct entity lifecycle evidence exists, the projection may consume only canonical world facts that are already safe runtime evidence:

- authoritative canonical zone identity;
- safe canonicalized entity-location evidence;
- explicit normalized zone relationships (`occurs_in`, `starts_in`, `found_in`);
- structured quest-step zone fields.

Provider candidate, ambiguous, unresolved, or unmapped zone evidence is never promoted merely to classify an entity.

## Entity-kind policy

Zones use the world-profile zone decision directly.

When no direct lifecycle field exists, quests and NPCs are world-bound enough that all known direct canonical zones being blocked may support an `OUTSIDE PROFILE` decision.

Items, spells, recipes, skills, and other portable/system entities require stronger lifecycle evidence. A currently known drop/vendor/location in a blocked zone does not prove that the entity itself is absent from the selected server era, so those cases stay `UNDETERMINED`.

Once a portable entity carries a lifecycle field from an explicitly reviewed source/field/parser combination, it can be classified directly rather than through location.

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

The default remains the current P99/Velious cap for release compatibility. An expansion-capped profile can also be selected explicitly:

```powershell
python .\tools\audit_profile_lifecycle.py .\dist\everquestie-knowledge.sqlite3 --profile p99 --json
```

The audit intentionally rejects `live` and `unrestricted`: origin expansion alone is not a Live retirement statement, and unrestricted has no era cap. Future reviewed expansion-capped profiles can reuse the same audit with their profile ID.

The audit opens SQLite with `mode=ro&immutable=1` and reports:

- the audited profile and expansion cap;
- entities with reviewed direct expansion/era evidence;
- accepted evidence rows by entity/source kind;
- lifecycle-looking candidate fields rejected by source policy;
- rejected candidate counts by source kind and policy reason;
- common reviewed expansion values;
- direct available/blocked/conflict/undetermined counts for the selected expansion-capped profile.

For the default P99 report, legacy `p99_*` JSON fields remain as aliases so existing build/report consumers do not break while the generic `available_direct`, `blocked_direct`, `conflict`, and `undetermined_direct` fields become the canonical schema.

It deliberately excludes locations and prose so the report answers how much strong lifecycle evidence is already in the shipped corpus while making untrusted lifecycle-looking source drift visible.

## Runtime storage

The selected profile remains writable user metadata. Availability projection reads the immutable knowledge snapshot plus that user preference and does not mutate knowledge.
