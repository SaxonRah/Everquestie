# Provider Travel Frontier Audit

## Purpose

`tools/audit_provider_travel_frontier.py` is a read-only diagnostic for the boundary between stored provider zone evidence and EverQuestie's canonical travel graph.

It was added after the first real post-HTTrack-fix acceptance run established that provider topology was genuinely compiling: three of five difficult real route cases became reachable, while `Labyrinth of Spite` and `North Freeport` still had zero incoming canonical travel edges. Subsequent scope review established that `North Freeport` is a historical/retired identity rather than a current-live default destination, so the CLI now defaults only to the remaining current-live provider frontier, `Labyrinth of Spite`. `North Freeport` remains available for explicit historical diagnostics.

The audit answers a narrower question than route acceptance:

> Does stored provider evidence exist for this exact canonical zone, and if so, what does the current provider travel compiler do with each row?

It does **not** attempt to make a route pass.

## Ownership boundary

The audit is intentionally a projection over existing finalized knowledge.

It does not:

- import or rescan an Allakhazam mirror;
- scan map folders;
- perform network requests;
- reconcile provider zone identities;
- compile or repair travel edges;
- create reverse edges;
- infer a transition from prose;
- weaken canonical zone identity rules.

The database is opened using SQLite URI `mode=ro` by the CLI.

## Exact zone resolution

Requested zones go through the existing `ZoneIdentityIndex` and the established unique EQ-client authority preference. This is the same conservative endpoint policy used by route acceptance.

Substring, nearest-name, significant-word and other fuzzy fallbacks are not used.

## Evidence traced

For each requested canonical gameplay zone the audit reports:

1. provider-zone bindings whose recorded gameplay target is the requested canonical zone;
2. the provider zone's source page/provenance when available;
3. every stored `connected_to` relationship touching those provider-zone entities;
4. the provider travel compiler's structured-row decision;
5. the compiler's current direction interpretation;
6. projection of each provider endpoint to canonical gameplay zone identity;
7. whether a finalized provider travel edge references that relationship;
8. all existing canonical incoming/outgoing travel edges touching the requested zone.

Direction is interpreted by `ProviderZoneTravelCatalog` itself. The audit therefore reflects the production meanings of structured values such as `Both`, `Entrance To <exact target>`, and `Exit From <exact target>` without maintaining a second direction parser.

## Zone classifications

`compiled`
: At least one stored provider `connected_to` relationship touching the provider zone is represented by a finalized canonical provider travel edge.

`provider_rows_uncompiled`
: A stored provider relationship is structurally eligible, both endpoints have projection-safe canonical bindings, and it is not a self-edge, but no finalized provider travel edge references it. This is the strongest signal of a compiler/finalization defect.

`provider_rows_blocked`
: Provider `connected_to` rows exist, but none currently compile. Per-row classifications explain whether the source or target binding is blocked, the relationship is unstructured, or both endpoints collapse to one canonical zone.

`no_structured_provider_topology`
: A provider-zone binding/page is associated with the canonical zone, but no stored `connected_to` relationship references that provider entity. This is a source-data/extraction frontier rather than a route-search failure.

`non_provider_topology_only`
: Canonical travel edges exist for the gameplay zone, but there is no associated provider-zone binding.

`no_provider_zone`
: Neither an associated provider-zone binding nor a canonical travel edge exists.

`ambiguous_zone` / `unresolved_zone`
: The requested audit endpoint itself does not resolve to one authoritative canonical gameplay zone. The audit refuses to guess.

## Relationship classifications

Each provider relationship is independently classified as:

- `compiled`;
- `compiler_eligible_missing_edge`;
- `blocked_source`;
- `blocked_target`;
- `self_edge`;
- `ignored_unstructured`.

The JSON output includes provider IDs/names, source provenance, raw direction, interpreted direction mode, canonical endpoint IDs/names, interpreted edge orientation, and the matching compiled edge ID when one exists.

## Usage

Default current-live provider frontier:

```powershell
python tools/audit_provider_travel_frontier.py release.sqlite3
```

The default currently audits `Labyrinth of Spite` only.

Machine-readable output:

```powershell
python tools/audit_provider_travel_frontier.py release.sqlite3 --json
```

One or more explicit exact zones, including historical/retired identities:

```powershell
python tools/audit_provider_travel_frontier.py release.sqlite3 `
  --zone "Labyrinth of Spite" `
  --zone "North Freeport" `
  --json
```

## How to interpret a frontier

For the real route-acceptance loop, run this audit before changing importer or routing behavior.

If a target reports `no_structured_provider_topology`, inspect the saved Allakhazam zone page/mirror representation for an additional structured transition surface. Do not parse arbitrary walkthrough prose simply to satisfy the acceptance case.

If it reports `provider_rows_blocked`, fix the exact binding/evidence gap named by the relationship diagnostics.

If it reports `provider_rows_uncompiled`, the source evidence and canonical bindings are already sufficient; investigate the provider travel compiler/finalization path.

If it reports `compiled` but route acceptance still says the target has no incoming edge, compare the interpreted direction and the route-connectivity component. A correct one-way edge may still make a route unreachable in the requested direction.

Historical diagnostics should not be promoted into current-live route acceptance simply because a historical identity still resolves. This keeps source enrichment, identity reconciliation, travel compilation, lifecycle scope, and route search as separate debuggable layers.
