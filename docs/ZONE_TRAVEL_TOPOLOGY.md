# Canonical zone travel topology

EverQuestie compiles zone travel into the shipped knowledge database. Normal runtime
never crawls maps, parses map labels, or rebuilds the travel graph.

## Provider-neutral graph

`zone_travel_edges` stores source-aware evidence between canonical `zone` entities.
The runtime route/query API consumes only this table and does not care which builder
provider supplied an edge.

Each edge records:

- canonical source zone
- canonical target zone when resolved
- connection kind (`travel`, `zone_line`, `portal`, `exit`, etc.)
- directed vs. explicitly bidirectional behavior
- linked / ambiguous / unresolved status
- portable source identity and version
- human-readable evidence
- optional source page and map-label metadata
- optional source-zone coordinates

Explicit provider connections can be added without any map catalog being present. This
is important for future EQ-client/MCP topology sources and a later Allakhazam/wiki
mirror.

## Map labels as one evidence source

Good/Brewall/native map labels can provide useful topology without becoming canonical
identity themselves. The builder currently recognizes deliberately conservative travel
cues such as:

- `To <zone>`
- `Zone to <zone>` / `Zone Line to <zone>`
- `Exit to <zone>` / `Entrance to <zone>`
- `Portal to <zone>` / `Teleport to <zone>`
- `<zone> Zone Line`

Travel cues are read from the original map label text. This is separate from
`map_labels.clean_text`, which intentionally removes decorators such as `To` for normal
NPC/item/place search.

After extracting the destination text, EverQuestie requires an exact canonical zone
name, alias, short-name hint, or canonical map-stem identity. It does not use spelling
similarity to invent travel edges.

If the destination matches more than one canonical zone, the candidate remains
`ambiguous`. If it matches none, it remains `unresolved`. A later provider can add an
alias or identity and the finalizer will re-run topology reconciliation after all
providers have completed.

## Directionality

A map label such as `To Blightfire Moors` proves an outbound connection from the source
map; it does not prove that the reverse trip exists. Map-derived edges are therefore
directed by default.

A provider that knows a connection is genuinely two-way can set `bidirectional=true`.
Runtime pathfinding follows directed evidence and only adds the reverse direction for
explicitly bidirectional edges.

This avoids silently treating one-way portals, scripted transports, or other special
travel as ordinary reciprocal zone lines.

## Finalization

The knowledge finalizer performs reconciliation in this order after all configured
providers have run:

1. ensure the portable map schema exists;
2. reconcile map stems to canonical zones;
3. reconcile map labels against canonical entities;
4. rebuild map-derived zone travel candidates;
5. strip player/builder-local state;
6. rebuild FTS and complete the normal snapshot integrity/optimization pipeline.

This ordering makes provider order non-semantic. A future Allakhazam/wiki importer can
enrich zone aliases or add explicit travel evidence without becoming a runtime
dependency and without requiring a new route schema.
