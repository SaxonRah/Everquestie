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

## Approved release manifests

Reviewed manifests committed under:

```text
builder-data/travel-supplements/*.json
```

are part of EverQuestie's release knowledge inputs. `tools/build_knowledge_db.py`
automatically compiles every JSON manifest in that directory, in deterministic filename
order, after the selected providers have populated the working DB and before snapshot
finalization begins.

The release build fails loudly when the approved directory is missing or empty, or when
any manifest cannot resolve its endpoints through authoritative canonical zone identity.
That prevents a clean rebuild from silently dropping reviewed travel knowledge.

This remains builder-only infrastructure. Packaged EverQuestie does not scan the
manifest directory and ordinary users do not need these JSON files separately from the
versioned knowledge snapshot.

## Normal release workflow

A normal knowledge release should use the main builder command. No separate supplement
application step is required:

```powershell
python .\tools\build_knowledge_db.py `
  --working-db .\build\working.sqlite3 `
  --snapshot-db .\dist\everquestie-knowledge.sqlite3 `
  --version 2026-08-15 `
  <provider arguments> `
  --force
```

The builder sequence is:

1. import the explicitly selected knowledge providers;
2. compile all repository-approved travel supplements;
3. finalize the copied knowledge snapshot, including provider/map reconciliation;
4. run route acceptance unless explicitly skipped.

Audit the **finalized snapshot**, not the raw working DB. Provider- and map-derived travel
rows are reconciled during snapshot finalization, so route acceptance against the raw
working DB can under-report the real compiled topology.

## Manual diagnostic workflow

`tools/apply_travel_supplement.py` remains available for reviewing a new manifest or
reproducing a travel frontier against an existing writable builder DB before committing
that manifest to the approved release directory:

```powershell
python .\tools\apply_travel_supplement.py .\build\working.sqlite3 `
  .\builder-data\travel-supplements\example.json `
  --json
```

After a manual diagnostic application, create a fresh finalized test snapshot before
running route acceptance:

```powershell
python .\tools\finalize_knowledge_snapshot.py `
  --input .\build\working.sqlite3 `
  --output .\build\test-knowledge.sqlite3 `
  --version test `
  --force
```

The finalizer may rebuild map-derived and structured-provider-derived travel rows, but
the supplement uses its own `curated_travel_manifest` source kind and remains ordinary
linked travel evidence in the finalized snapshot.

Do not apply supplements to `dist\everquestie-knowledge.sqlite3`, versioned files under
`build\release`, or packaged release copies. Those are finalized knowledge snapshots and
`TravelSupplementImporter` intentionally rejects them.

## Frontier-audit use

The provider frontier audit is still the first diagnostic. Use a supplement only after
the audit establishes that the missing transition is a genuine source-coverage frontier,
not an identity, direction, or compiler defect.

For example, the Labyrinth of Spite audit showed structured Allakhazam rows only for the
base zone versus an instance. Those rows should not be reinterpreted as the missing
base-world ingress. Once the actual base-world transition is confirmed from an approved
source, that evidence can be represented explicitly here without weakening provider-zone
reconciliation.

Historical/retired zones are a different concern. They should not receive invented
current-live edges merely because an old EQ-client identity remains present in the
knowledge database.
