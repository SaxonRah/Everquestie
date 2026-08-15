# Provider travel direction semantics

EverQuestie compiles source-owned zone relationships into one canonical travel graph. The graph must preserve explicit source direction without inventing reciprocal travel or using provider-only identities as gameplay targets.

## Allakhazam Connected Zones

The Allakhazam zone importer already stores the structured `Direction` cell from each `Connected Zones` row in the relationship `data_json` as `direction`. Provider travel catalog version 2 consumes that field when the relationship can be projected safely onto exact canonical gameplay zones.

The compiler recognizes only topology meanings that are explicit in the structured value:

| Structured direction | Canonical travel edge |
| --- | --- |
| `Both` | source ↔ target |
| `Entrance To <exact target>` | source → target |
| `Exit From <exact target>` | target → source |
| any other value | source → target, one-way |

`<exact target>` must match the structured relationship target name after case-folding and whitespace normalization. A string such as `Exit From Somewhere Else` does not reverse an edge whose target is `Blightfire Moors`.

## Why unknown values remain forward-only

The Direction column can also contain descriptive or compass-like text. Those values are useful provenance but do not by themselves prove reciprocity or reverse orientation. The conservative fallback therefore preserves the historical source-to-target orientation and leaves the edge one-way.

This is deliberately different from assuming that every zone connection can be traversed in both directions. A reverse route exists only when the source explicitly supplies reciprocal semantics (`Both`), the structured direction explicitly identifies an `Exit From` the exact target, or another confirmed edge independently supplies the reverse direction.

## Canonical identity boundary

Direction semantics are applied only after both provider endpoints pass the existing projection-safe canonical zone reconciliation:

- EQ-client-backed zone IDs are accepted directly;
- linked provider-zone bindings may project onto their canonical gameplay zone;
- unresolved and ambiguous provider zones remain blocked;
- direction text is never used to choose among ambiguous identities;
- a self-edge after canonical projection is still discarded.

The direction parser therefore changes orientation, not identity confidence.

## Provenance

Every compiled provider edge retains the original relationship payload and additionally records:

```json
{
  "provider_direction": {
    "raw": "Both",
    "mode": "both",
    "reversed": false,
    "bidirectional": true
  }
}
```

Modes currently emitted are:

- `both`
- `entrance_to_target`
- `exit_from_target`
- `forward_unclassified`

This makes it possible to inspect why the canonical edge has its orientation without reparsing source prose at runtime.

## Snapshot/runtime behavior

Provider topology remains builder-owned. Snapshot finalization reruns provider-zone reconciliation and provider travel compilation, so rebuilding a knowledge snapshot upgrades stored provider edges to catalog version 2 automatically.

The packaged `RuntimeDatabase` does not reinterpret direction strings and does not mutate topology. It reads the finalized `zone_travel_edges` table. A catalog-v2 `Both` edge is therefore naturally traversable in both directions by the existing `ZoneTravelCatalog.shortest_path()` implementation.

## Interaction with special travel requirements

This change only establishes the legal orientation of a confirmed transition. Keys, level gates, NPC dialogue, object interaction, portals, boats, quest state, and other requirements remain separate annotations on legal travel edges.

Future provider enrichment should attach those requirements as structured source-backed relationship data. It should not infer them from arbitrary walkthrough prose merely to make a route pass.

## Acceptance workflow

After rebuilding/finalizing a real knowledge snapshot, use the existing route acceptance audit to measure the effect on end-to-end travel coverage:

```text
python tools/audit_route_acceptance.py <snapshot.sqlite3> --full-paths
```

A route that still fails after catalog-v2 direction compilation is then a real next investigation target: missing provider coverage, unresolved canonical identity, a genuinely one-way transition, or another missing source-backed topology edge rather than an artifact of discarded `Direction` data.
