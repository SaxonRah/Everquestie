# Allakhazam capture-to-normalization delta

A completed Allakhazam mirror answers a different question from the finalized EverQuestie knowledge database:

- the mirror inventory says which unique structured source pages were captured;
- the normalization coverage says which source pages were persisted and produced durable SQLite derivatives.

`tools/audit_allakhazam_normalization_delta.py` composes those two artifacts without touching the mirror filesystem.

## Canonical full-build flow

`tools/build_full_knowledge.ps1` first runs the ordinary mirror inventory with `--require-complete`. That remains the source-capture gate: any HTTrack `.tmp` file stops the canonical build before database construction.

The full build saves that inventory as:

```text
build/allakhazam-mirror-audit.json
```

After the immutable knowledge snapshot is finalized, the builder passes that existing JSON artifact and the finalized SQLite snapshot to:

```powershell
python .\tools\audit_allakhazam_normalization_delta.py `
  .\build\allakhazam-mirror-audit.json `
  .\dist\everquestie-knowledge.sqlite3 `
  --output .\build\allakhazam-normalization-delta.json
```

The delta step does not rescan, rename, repair, or otherwise modify the mirror. The database is opened read-only.

## What the report measures

For each structured Allakhazam family (`quest`, `npc`, `item`, `zone`, `spell`) the report records:

1. **captured pages** — unique structured pages in the completed mirror inventory;
2. **persisted pages** — matching Allakhazam `source_pages` retained in EverQuestie's database;
3. **normalized pages** — persisted pages with at least one durable identity, graph, detail, support, or lifecycle derivative.

It then reports two separate work queues:

- **captured but not persisted**: source pages that did not cross the importer/capture boundary;
- **persisted but not normalized**: provenance records that reached SQLite but did not produce a normalized derivative.

Persisted pages that are not represented by the supplied mirror inventory are shown separately rather than silently folded into a percentage. This matters when comparing different capture artifacts or developer recovery experiments.

The report also includes downstream Allakhazam derivative counts for canonical entity links, relationships, locations, quest steps, rich details, and source-granular lifecycle records.

## Precision rules

The completed-mirror inventory uses the same URL-first identity policy as the production importer, including the conservative document fallback used by legacy generic Bestiary/NPC pages. This prevents the capture side from under-counting pages that the builder can actually import.

Source-granular spell lifecycle records count as normalized derivatives even when they remain intentionally unattached to a canonical spell. Exact numeric spell identity plus exact normalized name corroboration is still required before canonical attachment; an unresolved lifecycle record is preserved source evidence, not an importer failure.

Canonical entity counts are not expected to equal source-page counts. One source page can discover or link multiple entities, and provider reconciliation can intentionally preserve source facts before canonical attachment.

## Diagnostic, not an arbitrary release threshold

The delta is a measurement artifact. It fails only when its input report is malformed/internally inconsistent or the database cannot be read. It does **not** impose minimum item/NPC/quest/spell counts and does not turn a nonzero gap into an automatic release failure.

When a new completed mirror is built, compare `allakhazam-normalization-delta.json` across builds to identify the highest-value parser/importer gaps from actual captured source data.
