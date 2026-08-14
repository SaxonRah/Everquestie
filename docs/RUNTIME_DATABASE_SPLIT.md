# Runtime database split

EverQuestie runtime storage is deliberately split into two SQLite databases.

## Packaged knowledge

`everquestie-knowledge.sqlite3` is a versioned release artifact produced by the
builder/finalizer pipeline. Normal users do not compile it and do not need
`everquest1-mcp`, Node.js, an Allakhazam DB mirror, an Allakhazam Wiki mirror, or a
source checkout.

At runtime the snapshot is attached with SQLite `mode=ro&immutable=1`. It is never
migrated, indexed, reconciled, or otherwise rewritten on the player's machine. A
packaged build fails if its required knowledge snapshot is missing or incompatible.

The current source checkout retains the existing writable `Database` fallback when no
snapshot is present. That fallback is builder/developer behavior, not the release
storage model.

## Writable user state

`everquestie-user.sqlite3` contains player-specific state:

- tracked quests and objective progress
- observed log events
- runtime map/UI metadata that historically lived in `app_meta`

It may use WAL because it is intentionally writable. Updating or replacing the
knowledge snapshot does not replace this file.

On the first split-runtime launch EverQuestie can migrate player state from the legacy
combined `~/.eqquest/eqquest.sqlite3`. The legacy DB is read-only during migration and
is not deleted.

## Stable quest references

User quest state does not rely only on a knowledge table row ID. The state DB stores a
durable identity descriptor:

1. a namespaced external ID when one exists, preferring canonical/client identities;
2. otherwise the entity kind plus normalized canonical name.

Resolution also falls back to the stored canonical name when a provider identity is
temporarily absent. This is intentional future-provider behavior. For example, a
player can track a quest from today's source set, then a later knowledge snapshot can
attach an `allakhazam:quest` identity to that canonical quest without discarding the
player's progress. Conversely, migrated legacy state carrying an Allakhazam identity
can remain preserved while a current snapshot lacks that provider and resolve again
when the mirror is eventually available.

Allakhazam DB/Wiki remain optional builder enrichment providers. They are not runtime
dependencies and no normal startup path requires them.

## Map catalog

The global map catalog remains knowledge. Good/Brewall/other approved map ingestion is
an explicit builder/manual operation and the normalized catalog is shipped in the
knowledge snapshot. A player may still point the viewer at local map files as rendering
assets, but normal startup does not rebuild the global catalog.

## Release invariants

A release snapshot must:

- be finalized and marked `database_role=knowledge_snapshot`;
- have a compatible `knowledge_schema_version`;
- pass SQLite integrity checks;
- contain no player/session rows or builder-local filesystem paths;
- have its derived FTS state finalized;
- be safe to open without creating knowledge `-wal` or `-shm` sidecars.

The runtime user database has its own schema version and lifecycle.
