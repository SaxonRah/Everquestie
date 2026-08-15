# Shattering of Ro travel supplement

## Purpose

This builder-only evidence set fills the current source-coverage frontier that remains
after structured provider and map travel compilation: reaching `Labyrinth of Spite`
through confirmed Shattering of Ro world transitions and attaching that chain to the
established world travel network at `West Freeport`.

The manifests live at:

```text
builder-data/travel-supplements/plane-of-knowledge-city-portals.json
builder-data/travel-supplements/shattering-of-ro.json
```

They are not read by the packaged EverQuestie runtime. During builder/release work they
are compiled into ordinary `zone_travel_edges` by `TravelSupplementImporter`, after
which the normal knowledge-snapshot finalization path packages those compiled rows.

## Reviewed Shattering of Ro transitions

The 2026-08-15 evidence review records these transitions as forward-only:

1. `West Freeport` -> `Arcstone, Shattered Isles`
   - portal/travel evidence from Fanra's Shattering of Ro travel documentation;
   - requires completion of `Partisan of Candlemaker's Workshop`;
   - source: `https://everquest.fanra.info/wiki/Shattering_of_Ro`
2. `Arcstone, Shattered Isles` -> `Ruined Relic`
   - official EverQuest January 21, 2026 update notes refer to the Ruined Relic zone-in from Arcstone, Shattered Isles;
   - source: `https://www.everquest.com/update-notes/eq-update-notes-1-21-26`
3. `Ruined Relic` -> `The Vortex`
   - current Shattering of Ro player travel discussion explicitly identifies the Relic-to-Vortex zoneline;
   - source: `https://www.redguides.com/community/threads/sor-arcstone.95428/`
4. `The Vortex` -> `Labyrinth of Spite`
   - the same current travel discussion explicitly identifies the Vortex-to-Labyrinth-of-Spite zoneline;
   - source: `https://www.redguides.com/community/threads/sor-arcstone.95428/`

The community travel report also describes the complete sequence of zonelines from
Arcstone through Relic and Vortex to Labyrinth of Spite. The official Ruined Relic
patch-note wording independently corroborates the Arcstone-to-Ruined-Relic transition.

## Plane of Knowledge to West Freeport bridge

The first finalized-snapshot validation with only the four Shattering of Ro edges moved
`Labyrinth of Spite` into the established weak travel component, but `West Freeport`
still had zero incoming canonical edges. That correctly exposed the next frontier instead
of just making the acceptance test pass.

EverQuest's official November 30, 2007 teleportation-system guide provides explicit
bidirectional evidence for the missing bridge:

- city Plane of Knowledge book statues teleport players to the Plane of Knowledge;
- Plane of Knowledge city stones teleport players to the named city's book statue;
- the official Plane of Knowledge portal list explicitly includes `West Freeport`.

Source:

```text
https://www.everquest.com/news/imported-eq-enus-50703
```

That evidence is kept in the separate
`plane-of-knowledge-city-portals.json` manifest with an explicit bidirectional edge:

```text
The Plane of Knowledge <-> West Freeport
```

Keeping this core portal fact separate avoids misattributing it to Shattering of Ro and
provides a clean home for future source-reviewed Plane of Knowledge city portal entries.

## Direction policy

Every edge in `shattering-of-ro.json` has `bidirectional: false`.

That is intentional. A physical zoneline may in practice permit return travel, but
EverQuestie does not infer reciprocity from a one-direction observation. Reverse edges
should be added only when reviewed evidence explicitly supports that direction.

The Plane of Knowledge/West Freeport edge is different: the official source describes
both travel directions, so `plane-of-knowledge-city-portals.json` explicitly sets
`bidirectional: true`.

## Applying the manifests

From the repository root, apply both manifests to the real writable builder database:

```powershell
python .\tools\apply_travel_supplement.py `
  .\build\working.sqlite3 `
  .\builder-data\travel-supplements\plane-of-knowledge-city-portals.json `
  --json

python .\tools\apply_travel_supplement.py `
  .\build\working.sqlite3 `
  .\builder-data\travel-supplements\shattering-of-ro.json `
  --json
```

Then finalize a fresh test snapshot:

```powershell
python .\tools\finalize_knowledge_snapshot.py `
  --input .\build\working.sqlite3 `
  --output .\build\sor-test-knowledge.sqlite3 `
  --version 2026-08-15-sor-test `
  --force
```

Run route acceptance against the **finalized snapshot**. The raw working DB is not the
correct route-acceptance surface because structured provider/map travel reconciliation
happens during snapshot finalization.

```powershell
python .\tools\audit_route_acceptance.py `
  .\build\sor-test-knowledge.sqlite3 `
  --full-paths
```

Do not apply either supplement directly to an already-finalized knowledge snapshot;
`TravelSupplementImporter` rejects that operation.

## Regression coverage

`tests/test_shattering_of_ro_travel_manifest.py` creates exact EQ-client-backed canonical
identities for the reviewed Shattering of Ro zones and verifies that:

- all four manifest rows compile;
- the chain routes from West Freeport through Arcstone, Ruined Relic and The Vortex to Labyrinth of Spite;
- no reverse path is inferred for the reviewed one-way evidence;
- the West Freeport -> Arcstone progression requirement survives compilation;
- source keys and source version remain present on the compiled travel rows.

`tests/test_plane_of_knowledge_city_portals.py` independently verifies that the official
Plane of Knowledge/West Freeport portal row compiles in both directions and retains its
source provenance.
