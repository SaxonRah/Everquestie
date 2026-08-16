# EverQuestie Source Policy

EverQuestie owns the normalized SQLite knowledge database. External/local datasets are evidence sources; they do not become the runtime data model.

## Network boundary

Normal play, log parsing, maps, Knowledge, local Search, quest progress, and the compiled database are local-only. Community websites are contacted only by an explicit user action in the Search tab. A local-client compile loads only the configured EverQuest installation through the configured local `everquest1-mcp` repository.

## Field-level preference

Preferences are intentionally field-specific rather than "one source wins everything":

- **EverQuest client files:** preferred for client IDs, spell mechanics, local progression tables, zone identity, and other mechanics physically shipped with the selected client.
- **Allakhazam local mirror:** quest walkthroughs/objectives, NPC/item/zone relationships, community locations, and reviewed structured lifecycle fields after the builder explicitly imports a completed local mirror.
- **Good/Brewall/EQ map files:** geometry, labels and map POIs for the selected map pack.
- **Explicit online search:** temporary lookup results. They are not silently inserted into SQLite.

## Lifecycle fields require semantic review

A field name such as `expansion` or `era` is not automatically gameplay-profile evidence. Direct lifecycle use is approved at the combination of **source + entity kind + field + parser semantics**.

Current reviewed direct lifecycle fields are explicit structured Allakhazam local-mirror values:

- NPC and zone `Expansion`;
- item metadata `Expansion`;
- quest `Era`;
- spell `Quick Facts → Expansion`.

The first three continue to live on their source-owned normalized entities. Spell lifecycle uses the source-granular `entity_lifecycle_records` surface because the canonical spell identity/detail is owned by client/MCP data. This prevents one Allakhazam lifecycle fact from replacing the spell's canonical primary source or rich mechanics detail.

Allakhazam spell lifecycle attaches to a canonical `eqclient:spell` only when **both** the numeric spell ID and normalized spell name match exactly. A matching number alone, name-only match, fuzzy match, substring, or level-derived approximation is never sufficient. If canonical identity is not available yet, the source record remains unattached and can be reconciled later; provider order therefore does not decide whether the source fact is preserved.

Canonical rich-detail JSON is fail-closed for lifecycle use until a source/field combination is separately reviewed. This is particularly important for `everquest1-mcp`: the repository-locked 1.2.1 local spell parser does not supply a direct spell expansion field, and its expansion grouping helper explicitly approximates eras from class minimum-level ranges. Those groups are useful reference output but are not direct spell lifecycle evidence.

The lifecycle audit reports rejected lifecycle-looking candidates separately and resolves reviewed source-granular spell records only through the same exact identity rule used at runtime. This makes source drift visible without allowing an upstream schema change to silently alter Live/P99/TLP behavior.

## Conflicts

EverQuestie retains source provenance instead of silently deleting contradictory evidence. Stable external IDs are preferred for identity; zones may merge by normalized name where the client and community source clearly describe the same zone. A later UI can expose competing field values/evidence when multiple sources disagree.

Only conflicts between lifecycle statements that individually pass the reviewed source policy are treated as direct lifecycle conflicts. An unreviewed candidate cannot overrule or conflict with reviewed evidence.

## Mirror safety

Mirror import is manual. EverQuestie does not watch, scan, index, or modify configured HTTrack mirror directories in the background. In-progress `*.tmp` files are ignored by the manual Allakhazam importer. Spell lifecycle compilation reads only recognized spell pages already present in the explicitly selected mirror; packaged runtime never fetches or rescans them.
