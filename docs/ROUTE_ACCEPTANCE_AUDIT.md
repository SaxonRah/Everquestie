# Route acceptance audit

EverQuestie has a read-only acceptance audit for answering a concrete release question:

> Can this finalized knowledge snapshot actually route from this canonical EverQuest zone to that canonical EverQuest zone?

This is **not** another travel graph, another pathfinder, or another source-ingestion system. The audit deliberately composes the navigation systems that already own those responsibilities:

- `ZoneIdentityIndex` + the EQ-client authority rule resolve exact canonical endpoints;
- `ZoneTravelCatalog.shortest_path()` owns confirmed directed routing;
- `travel_connectivity_diagnostic()` classifies failed routes by graph topology;
- `zone_coverage.py` remains the global weak/strong-component and sink audit;
- `travel_frontier.py` remains the map-label backlog audit.

The acceptance report is therefore a regression/release view over the same facts the packaged application will use.

## Default cross-world acceptance cases

When no explicit route pairs are supplied, the command checks a deliberately varied set of real canonical endpoint families:

- **The Hole → Labyrinth of Spite**
- **Paineel → The Hole**
- **Stonebrunt Mountains → Paineel**
- **Greater Faydark → The Hole**
- **Stone Hive → North Freeport**

These names are acceptance **queries**, not hard-coded geography. The audit does not manufacture intermediate zones, edges, requirements, aliases, or reciprocal travel to make a case pass.

The default list must contain literal real EverQuest client zone display names. Synthetic zones used to stress long/gated route mechanics belong only in unit tests. This matters because an unresolved default endpoint otherwise looks like a source-data failure even when the actual defect is the acceptance question itself. Likewise, the audit keeps exact identity semantics: the canonical zone is `Stone Hive`; it does not teach the resolver to accept the noncanonical query `The Stone Hive` merely to make the audit pass.

The long synthetic route tests elsewhere in the suite prove that EverQuestie's algorithm can traverse arbitrary confirmed route lengths and gated transitions. This audit answers the separate real-data question: whether the supplied builder/finalized snapshot actually contains enough canonical source-backed topology for the requested endpoints.

## Running the audit

From the repository root:

```powershell
python .\tools\audit_route_acceptance.py .\dist\everquestie-knowledge.sqlite3
```

Audit one or more explicit pairs:

```powershell
python .\tools\audit_route_acceptance.py .\dist\everquestie-knowledge.sqlite3 `
  --route "The Hole" "Labyrinth of Spite" `
  --route "Paineel" "The Hole"
```

Show every intermediate zone for successful routes:

```powershell
python .\tools\audit_route_acceptance.py .\dist\everquestie-knowledge.sqlite3 --full-paths
```

Machine-readable output:

```powershell
python .\tools\audit_route_acceptance.py .\dist\everquestie-knowledge.sqlite3 --json
```

For CI/release gates, `--fail-unreachable` returns exit code `2` if any requested case fails:

```powershell
python .\tools\audit_route_acceptance.py .\dist\everquestie-knowledge.sqlite3 `
  --fail-unreachable `
  --route "The Hole" "Labyrinth of Spite"
```

The SQLite database is opened read-only. The command does not scan map folders, parse provider pages, invoke MCP/Node, contact Allakhazam, reconcile identities, or mutate the snapshot.

## Result classes

A case can report:

- `reachable` — both endpoints resolve canonically and a confirmed directed route exists;
- `same_zone` — both exact endpoint tokens resolve to the same canonical zone;
- `source_unresolved` / `target_unresolved` — the requested endpoint has no conservative canonical identity;
- `source_ambiguous` / `target_ambiguous` — exact identity evidence still leaves multiple safe candidates;
- `directionality_blocked` — source and destination are in the same weak evidence component, but confirmed directed edges do not permit travel in the requested direction;
- `disconnected` — the destination lies outside the source's confirmed travel component;
- `route_inconsistency` — the diagnostic directed traversal can reach the destination while the normal shortest-path query cannot, indicating an internal catalog consistency defect rather than missing source coverage.

Only `reachable` and `same_zone` are acceptance passes.

## Identity policy

The audit uses the same exact identity policy as player-facing navigation. It does not enable significant-word or containment matching merely to make a test case resolve.

If an exact display-name collision exists, the existing authority rule may choose the unique EQ-client-backed canonical zone when that is safe. Multiple client-backed same-name zones remain ambiguous. Provider candidates do not become gameplay targets simply because they would connect two graph components.

A permanent regression creates the exact client names used by the default suite and verifies that every default source and target resolves without fuzzy aliases. This prevents a synthetic stress-test name or a display-name typo from being misclassified as missing real-world knowledge again.

## Directionality and special transitions

A missing reverse route is not repaired by assuming that a zone line is reciprocal. The route must have reciprocal evidence or an explicitly two-way edge.

Likewise, level gates, keys, boats, portals, NPC interactions, object clicks, and other special transitions do not inherently cause an acceptance failure. Once a legal transition is represented as a confirmed edge, its structured requirements annotate the hop while the route remains traversable.

This means a failed far route now points primarily to one of three source-data problems:

1. a canonical zone identity/binding is missing or ambiguous;
2. a legal transition has not been compiled into `zone_travel_edges`;
3. directionality evidence is incomplete.

Before treating an identity failure as a source-data problem, the default-suite regression ensures the query itself is a real canonical endpoint.

## How this drives source enrichment

The recommended workflow is:

1. finalize or otherwise prepare the knowledge snapshot;
2. run `audit_zone_coverage.py` to understand global graph health;
3. run `audit_travel_frontier.py` for map-label evidence that is not yet compiled;
4. run `audit_route_acceptance.py` for representative player journeys;
5. investigate the exact failed component/frontier using source evidence;
6. enrich Allakhazam/map/provider normalization conservatively;
7. rebuild/finalize and rerun the acceptance suite.

For Allakhazam specifically, the current structured `Connected Zones` parser already provides source-backed endpoint and direction evidence. More complex level/key/NPC/barrier requirements should only be added when the source page exposes them reliably enough to normalize with provenance. Free-text guessing should not be used to make acceptance cases pass.
