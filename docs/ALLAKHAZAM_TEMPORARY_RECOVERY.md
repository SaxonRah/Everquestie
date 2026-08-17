# Allakhazam temporary-page recovery

EverQuestie normally treats every HTTrack `*.tmp` page as crawler-owned in-progress state. `AllakhazamMirrorImporter.import_mirror()` continues to ignore all temporary pages, and the canonical full knowledge builder continues to require a completed mirror with no `*.tmp` files before database construction.

This document describes a separate **builder/developer recovery action** for a partial local mirror whose temporary-page audit shows a large body of likely-complete structured responses that would otherwise be unavailable for content work.

## Trust boundary

Run the read-only inventory first:

```powershell
python .\tools\audit_allakhazam_temporary_pages.py "D:\AllakhazamMirror\everquest.allakhazam.com"
```

`likely_complete_structured` is deliberately only a recovery-candidate classification. It means the temporary file has:

- a proven Allakhazam canonical URL or the production importer's structured legacy-document fallback;
- a recognized quest, NPC, item, zone, or spell identity;
- normal `</body>` and `</html>` markers near the physical end of the response;
- no canonical duplicate among already-completed non-temporary mirror pages.

Those signals do **not** make `.tmp` trusted runtime or release input automatically.

## Explicit recovery

Recovery is an opt-in write to an existing **builder/working** EverQuestie database:

```powershell
python .\tools\recover_allakhazam_temporary_pages.py `
  "D:\AllakhazamMirror\everquest.allakhazam.com" `
  --database .\build\working.sqlite3 `
  --source-version "partial-capture-2026-08-17"
```

Add `--json` for a machine-readable summary.

The recovery CLI refuses:

- a missing database;
- a database without EverQuestie's builder knowledge tables;
- a finalized `knowledge_snapshot`;
- a player/user-state database.

It never creates, renames, deletes, repairs, or promotes files inside the mirror.

## Second stability check before import

A recovery candidate does not go straight from the audit signal into SQLite. The recovery action:

1. snapshots the temporary HTML-like paths and completed canonical pages;
2. classifies every temporary page with the same canonical identity, structured-family, document-end, and production fallback rules used by the temporary audit;
3. re-scans completed pages so a page finalized by HTTrack during classification wins over its temporary peer;
4. re-reads each candidate in full while stat-checking size and modification time;
5. revalidates canonical URL, structured identity, and physical document-end markers against that full read;
6. invokes the normal `AllakhazamMirrorImporter` only after all of those checks pass.

If a candidate changes while it is being read, fails full-read revalidation, becomes a duplicate of a completed page, or cannot be parsed by the production importer, it is skipped. Duplicate temporary files with the same canonical URL are deterministic: the first stable successfully imported/unchanged candidate wins and later copies are skipped.

Recovered pages use the normal Allakhazam `source_pages` provenance model and the same entity/relationship/location/quest-step parser as completed pages. An optional `--source-version` is retained on those source rows. Builder-local `.tmp` paths remain provenance only in the working database; ordinary snapshot finalization strips builder-local paths.

## Canonical release builds stay stricter

`tools/build_full_knowledge.ps1` is intentionally **not** wired to this recovery action. It still runs `audit_allakhazam_mirror.py --require-complete` before database construction and aborts while any HTTrack `.tmp` files remain.

That distinction is deliberate:

- temporary recovery is useful for explicit content-recovery/debug work against an incomplete local capture;
- canonical full builds and releases require the source mirror to have finished normally.

Packaged EverQuestie never sees the mirror, never runs this tool, and never parses `.tmp` files at runtime.
