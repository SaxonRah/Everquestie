# EverQuestie Full-Allakhazam Performance Checklist

This checklist tracks the performance hardening required now that the knowledge corpus includes the full Allakhazam mirror.

## P0 — restore normal client responsiveness

- [x] Defer full SQLite integrity checks; never run `PRAGMA integrity_check` during normal startup.
- [x] Version database migrations so historical backfills run once instead of on every `Database(...)` open.
- [x] Make `Database.entity()` a lightweight normalized-entity lookup; fetch archived source text only on explicit demand.
- [x] Replace Recent Loot's full item + alias corpus scan with indexed lookups for only observed item names.
- [x] Replace runtime tracked-quest scans with indexed state-key/name/external-ID lookup.
- [x] Cache immutable runtime profile/zone decisions.
- [x] Add/verify runtime indexes for location-by-zone, observed-event cursoring, quest-step zone lookup, and source classification.

## P1 — remove remaining corpus-size work from interactive paths

- [x] Make entity resolution exact-first; use substring/FTS only as a bounded fallback.
- [x] Remove N+1 alias queries from local search ranking.
- [x] Precompile Activity Pathway objective/drop indexes into the release knowledge DB.
- [x] Precompile canonical quest-step zone IDs for Zone Opportunities.
- [x] Cursor Activity Cluster so refresh cost depends on new events, not total session history.\n- [ ] Cursor any remaining session projections that still rescan accumulated observations.
- [ ] Cache other immutable runtime projections that currently rebuild from normalized knowledge.

## P2 — shrink and isolate the shipped runtime artifact

- [x] Strip raw HTML from finalized runtime snapshots.
- [ ] Decide whether runtime should retain full source-page plain text, bounded excerpts, or a separate optional source archive.
- [ ] Ensure normal packaged EverQuestie never needs an Allakhazam mirror path.
- [ ] Keep source import/rebuild/finalization strictly builder-only.
- [ ] Keep map-catalog construction builder/manual only; runtime consumes the shipped catalog.

## P3 — builder/import responsiveness

- [x] Move full Allakhazam DB mirror import off Tk's UI thread.\n- [ ] Move Wiki/saved-folder import variants off Tk's UI thread.
- [ ] Avoid `sorted(rglob(...))` full-mirror materialization where ordering is unnecessary.
- [x] Add incremental manifest/hash metadata so unchanged mirror files do not require expensive repeated parsing.
- [ ] Add progress/cancellation to long builder operations.
- [ ] Keep full integrity/audit/VACUUM work in explicit release/diagnostic commands.

## Validation

- [x] Add regression tests proving repeated DB opens do not replay legacy backfills.
- [x] Add tests proving entity reads do not materialize source bodies unless explicitly requested.
- [x] Add tests for exact/ambiguous item identity in optimized Recent Loot lookup.
- [x] Add runtime split tests for tracked quest identity across snapshot row-ID/provider changes.
- [ ] Add performance smoke fixtures with a large synthetic entity/alias corpus.
- [ ] Record startup, DB-open, first-live-event, search, and loot-refresh benchmarks before/after.
