# Travel Supplement Builder

## Purpose

EverQuestie's normal travel graph is compiled from structured provider relationships
and explicit map travel labels. Some real EverQuest transitions are documented by an
approved source but are not exposed through those structured surfaces.

A **travel supplement** is the builder-only escape hatch for that gap.

It is deliberately not a routing override. A supplement is a versioned JSON evidence
manifest that resolves exact canonical EverQuest zone identities and compiles ordinary
`zone_travel_edges`. Packaged runtime continues to read the same source-independent
travel graph.

## Safety boundary

`TravelSupplementImporter` is intentionally conservative:

- it runs only against a writable builder/working database;
- every source and target must resolve through the existing authoritative zone policy;
- it creates no zones, aliases, fuzzy identity matches, or reverse edges;
- `bidirectional` is false unless the manifest explicitly says otherwise;
- every edge requires a stable `source_key` and non-empty evidence text;
- the complete manifest is validated before any previous rows for that supplement
  source are replaced;
- provenance and travel requirements are retained on the compiled edge.

This is appropriate when source evidence is trustworthy but the source's structured
HTML/map representation is incomplete. It is not a mechanism for making an acceptance
test pass by assertion.

## Manifest format

Schema version 1:

```json
{
  "schema_version": 1,
  "source_name": "Approved EverQuest travel notes",
  "source_version": "2026-08-15",
  "source_url": "https://example.invalid/source-page",
  "edges": [
    {
      "source_key": "stable-source-owned-key",
      "source": "Exact Canonical Source Zone",
      "target": "Exact Canonical Target Zone",
      "connection_kind": "portal",
      "bidirectional": false,
      "evidence": "Concise source-backed statement describing this transition.",
      "travel_requirements": [
        {
          "kind": "minimum_level",
          "minimum_level": 125,
          "text": "Minimum level 125",
          "direction": "forward"
        }
      ]
    }
  ]
}
```

`source_url` may be set once at the manifest root or overridden per edge. It is retained
inside the edge's `data_json`; the manifest's local filesystem path is not written into
the distributable knowledge graph.

`travel_requirements` uses the existing EverQuestie requirement format consumed by
`travel_requirements_for_hop`. Requirements are informational gates on a confirmed
transition; they do not silently remove the edge from pathfinding.

## Manual builder workflow

Apply a manifest to an existing working knowledge database:

```powershell
python .\tools\apply_travel_supplement.py .\build\everquestie-working.sqlite3 `
  .\builder-data\travel-supplement.json
```

Machine-readable statistics:

```powershell
python .\tools\apply_travel_supplement.py .\build\everquestie-working.sqlite3 `
  .\builder-data\travel-supplement.json --json
```

Then create a fresh finalized snapshot through the existing release path:

```powershell
python .\tools\finalize_knowledge_snapshot.py `
  --input .\build\everquestie-working.sqlite3 `
  --output .\dist\everquestie-knowledge.sqlite3 `
  --version 2026-08-15 `
  --force
```

The finalizer may rebuild map-derived and structured-provider-derived travel rows, but
the supplement uses its own `curated_travel_manifest` source kind and remains ordinary
linked travel evidence in the finalized snapshot.

## Frontier-audit use

The provider frontier audit is still the first diagnostic. Use a supplement only after
the audit establishes that the missing transition is a genuine source-coverage frontier,
not an identity, direction, or compiler defect.

For example, the current Labyrinth of Spite audit shows structured Allakhazam rows only
for the base zone versus an instance. Those rows should not be reinterpreted as the
missing base-world ingress. Once the actual base-world transition is confirmed from an
approved source, that evidence can be represented explicitly here without weakening
provider-zone reconciliation.

Historical/retired zones are a different concern. They should not receive invented
current-live edges merely because an old EQ-client identity remains present in the
knowledge database.
