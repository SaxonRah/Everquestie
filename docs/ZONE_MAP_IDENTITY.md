# Canonical zone/map identity

EverQuestie treats a map filename as source evidence, not as the canonical identity of
a zone. Good, Brewall, native EverQuest maps, and future providers may all use different
or abbreviated names for the same zone.

`zone_map_bindings` is builder-produced knowledge that joins a map-pack source and map
stem to an EverQuestie canonical `zone` entity:

- `source_name` / `source_version` identify the map catalog provider
- `map_stem` is the provider's map-file stem
- `zone_entity_id` points at the canonical EverQuestie zone when resolved
- `status` is `linked`, `ambiguous`, or `unresolved`
- `reason` records why the identity decision was made

Normal application startup does not build or reconcile this table.

## Conservative resolution

The builder may link a map stem when it has conservative identity evidence:

1. an already-established canonical map-zone name;
2. an exact canonical display name, alias, or provider/client short-name hint;
3. a significant zone-name word that uniquely identifies one zone;
4. conservative name containment that still identifies only one zone.

If more than one canonical zone remains possible, the binding is stored as ambiguous.
Spelling similarity alone is not promoted to canonical identity.

This matters for names such as `qeynos`: if both North Qeynos and South Qeynos are
possible and no stronger short-name evidence exists, EverQuestie records the ambiguity
instead of silently choosing one.

## Provider enrichment

The catalog is source-independent. A current build can leave a map unresolved, and a
later provider can add a short-name alias or other canonical identity evidence to the
same zone entity. Re-running the builder then resolves the existing map binding without
changing the runtime schema.

That is also the intended integration point for a future Allakhazam DB/Wiki mirror:
those providers may enrich canonical zones with aliases, external IDs, facts, and
relationships, but the map system does not depend on those providers being available.

## Existing map-search integration

When a binding is confidently linked, the builder backfills the canonical zone name
into `map_sources` and `map_labels`. Existing current-zone filtering and map-label
entity reconciliation therefore use the stronger canonical zone identity immediately.

The map-pack builder reports linked, ambiguous, and unresolved zone-map totals so a
knowledge release can be audited for catalog coverage.
