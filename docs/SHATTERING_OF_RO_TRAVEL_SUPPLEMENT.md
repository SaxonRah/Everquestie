# Shattering of Ro travel supplement

## Purpose

This builder-only manifest fills the current source-coverage frontier that remains after structured provider and map travel compilation: reaching `Labyrinth of Spite` through confirmed Shattering of Ro world transitions.

The manifest lives at:

```text
builder-data/travel-supplements/shattering-of-ro.json
```

It is not read by the packaged EverQuestie runtime. During builder/release work it is compiled into ordinary `zone_travel_edges` by `TravelSupplementImporter`, after which the normal knowledge-snapshot finalization path packages those compiled rows.

## Reviewed transitions

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

The community travel report also describes the complete sequence of zonelines from Arcstone through Relic and Vortex to Labyrinth of Spite. The official Ruined Relic patch-note wording independently corroborates the Arcstone-to-Ruined-Relic transition.

## Direction policy

Every edge in this manifest has `bidirectional: false`.

That is intentional. A physical zoneline may in practice permit return travel, but EverQuestie does not infer reciprocity from a one-direction observation. Reverse edges should be added only when reviewed evidence explicitly supports that direction.

The manifest therefore improves current-live reachability without weakening the travel compiler's existing direction semantics.

## Applying the manifest

From the repository root, apply it to a writable builder/working database:

```powershell
python .\tools\apply_travel_supplement.py `
  .\build\everquestie-working.sqlite3 `
  .\builder-data\travel-supplements\shattering-of-ro.json `
  --json
```

Then finalize a fresh release snapshot through the normal release path:

```powershell
python .\tools\finalize_knowledge_snapshot.py `
  --input .\build\everquestie-working.sqlite3 `
  --output .\dist\everquestie-knowledge.sqlite3 `
  --version 2026-08-15 `
  --force
```

Do not apply the supplement directly to an already-finalized knowledge snapshot; `TravelSupplementImporter` rejects that operation.

## Regression coverage

`tests/test_shattering_of_ro_travel_manifest.py` creates exact EQ-client-backed canonical identities for the reviewed zones and verifies that:

- all four manifest rows compile;
- the chain routes from West Freeport through Arcstone, Ruined Relic and The Vortex to Labyrinth of Spite;
- no reverse path is inferred for the reviewed one-way evidence;
- the West Freeport -> Arcstone progression requirement survives compilation;
- source keys and source version remain present on the compiled travel rows.
