# Provider Travel Frontier Audit

## Purpose

`tools/audit_provider_travel_frontier.py` is a read-only diagnostic for the boundary between stored provider zone evidence and EverQuestie's canonical travel graph.

It was added after the first real post-HTTrack-fix acceptance run established that provider topology was genuinely compiling: three of five difficult real route cases became reachable, while `Labyrinth of Spite` and `North Freeport` still had zero incoming canonical travel edges. Subsequent scope review established that `North Freeport` is a historical/retired identity rather than a current-live default destination, so the CLI defaults only to the remaining current-live provider frontier, `Labyrinth of Spite`. `North Freeport` remains available for explicit historical diagnostics.

The audit answers a narrower question than route acceptance:

> Does stored provider evidence exist for this exact canonical zone, and if so, what does the current provider travel compiler do with each row?

It does **not** attempt to make a route pass.

## Ownership boundary

The audit is intentionally a projection over existing knowledge.

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
2. whether those provider entities actually have a stored source page and its provenance;
3. the binding-state counts (`linked`, `candidate`, and any other stored state);
4. every stored `connected_to` relationship touching those provider-zone entities;
5. the provider travel compiler's structured-row decision and aggregate decision counts;
6. the compiler's current direction interpretation;
7. projection of each provider endpoint to canonical gameplay zone identity;
8. whether a finalized provider travel edge references that relationship;
9. all existing canonical incoming/outgoing travel edges touching the requested zone.

Direction is interpreted by `ProviderZoneTravelCatalog` itself. The audit therefore reflects the production meanings of structured values such as `Both`, `Entrance To <exact target>`, and `Exit From <exact target>` without maintaining a second direction parser.

## Zone classifications

`compiled`
: At least one stored provider `connected_to` relationship touching the provider zone is represented by a canonical provider travel edge. Other blocked rows may still be reported alongside the compiled evidence.

`provider_rows_uncompiled`
: A stored provider relationship is structurally eligible, both endpoints have projection-safe canonical bindings, and it is not a self-edge, but no canonical provider travel edge references it. This is the strongest signal of a compiler/finalization or stale-builder defect.

`provider_rows_identity_blocked`
: Structured provider `connected_to` rows exist, but a source or target provider endpoint lacks a linked canonical gameplay binding. Fix or enrich the exact identity evidence; do not route through the unresolved provider entity.

`provider_rows_unstructured`
: `connected_to` rows exist, but none qualify as source-owned structured travel evidence. This distinguishes stored generic/inferred relationships from a missing provider page or missing extraction entirely.

`provider_rows_blocked`
: Provider rows exist but are non-routeable for another explicit compiler reason, such as both endpoints collapsing to one canonical gameplay zone. Per-row classifications give the exact reason.

`provider_page_no_connected_rows`
: A provider-zone binding and stored provider source page exist, but no `connected_to` relationship references that provider entity. This is a source-data/extraction frontier. Inspect the saved structured zone page before considering any parser expansion.

`provider_zone_missing_source_page`
: A provider-zone binding/entity exists but it has no stored source page. The gap is upstream of connected-zone extraction.

`non_provider_topology_only`
: Canonical travel edges exist for the gameplay zone, but there is no associated provider-zone binding.

`no_provider_zone`
: Neither an associated provider-zone binding nor a canonical travel edge exists. No provider-backed source fact is currently attached to this canonical endpoint through the established reconciliation rules.

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

The JSON output includes provider IDs/names, source provenance, raw direction, interpreted direction mode, canonical endpoint IDs/names, interpreted edge orientation, the matching compiled edge ID when one exists, binding-state counts, provider-source-page count, and relationship-decision counts.

## Usage

Default current-live provider frontier:

```powershell
python tools/audit_provider_travel_frontier.py release.sqlite3
```

The default audits `Labyrinth of Spite` only.

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

If a target reports `provider_zone_missing_source_page`, repair or import the exact provider page before looking at topology parsing.

If it reports `provider_page_no_connected_rows`, inspect the saved provider zone page/mirror representation for an additional **structured** transition surface. Do not parse arbitrary walkthrough prose simply to satisfy an acceptance case.

If it reports `provider_rows_unstructured`, determine whether the stored relationship really came from a structured travel surface. Do not upgrade generic or inferred rows merely because their endpoints look useful.

If it reports `provider_rows_identity_blocked`, fix the exact provider→canonical identity gap named by the relationship diagnostics. A relationship is not allowed to break identity ambiguity.

If it reports `provider_rows_uncompiled`, the source evidence and canonical bindings are already sufficient; investigate builder freshness, provider travel compilation, or snapshot finalization.

If it reports `compiled` but route acceptance still says the target has no incoming edge, compare the interpreted direction and the route-connectivity component. A correct one-way edge may still make a route unreachable in the requested direction.

Historical diagnostics should not be promoted into current-live route acceptance simply because a historical identity still resolves. This keeps source enrichment, identity reconciliation, travel compilation, lifecycle scope, and route search as separate debuggable layers.
