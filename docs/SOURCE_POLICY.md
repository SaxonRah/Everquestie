# EverQuestie Source Policy

EverQuestie owns the normalized SQLite knowledge database. External/local datasets are evidence sources; they do not become the runtime data model.

## Network boundary

Normal play, log parsing, maps, Knowledge, local Search, quest progress, and the compiled database are local-only. Community websites are contacted only by an explicit user action in the Search tab. A local-client compile loads only the configured EverQuest installation through the configured local `everquest1-mcp` repository.

## Field-level preference

Preferences are intentionally field-specific rather than "one source wins everything":

- **EverQuest client files:** preferred for client IDs, spell mechanics, local progression tables, zone identity, and other mechanics physically shipped with the selected client.
- **Allakhazam local mirror:** quest walkthroughs/objectives, NPC/item/zone relationships, community locations and other world/quest evidence after the user explicitly imports a completed local mirror.
- **Good/Brewall/EQ map files:** geometry, labels and map POIs for the selected map pack.
- **Explicit online search:** temporary lookup results. They are not silently inserted into SQLite.

## Conflicts

EverQuestie retains source provenance instead of silently deleting contradictory evidence. Stable external IDs are preferred for identity; zones may merge by normalized name where the client and community source clearly describe the same zone. A later UI can expose competing field values/evidence when multiple sources disagree.

## Mirror safety

Mirror import is manual. EverQuestie does not watch, scan, index, or modify configured HTTrack mirror directories in the background. In-progress `*.tmp` files are ignored by the manual Allakhazam importer.
