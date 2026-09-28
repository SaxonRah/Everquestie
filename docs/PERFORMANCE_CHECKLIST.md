# EverQuestie Full-Allakhazam Performance Checklist

This checklist tracks the performance hardening required now that the knowledge corpus includes the full Allakhazam mirror.

## P0 — restore normal client responsiveness

- [x] Defer full SQLite integrity checks; never run `PRAGMA integrity_check` during normal startup.
- [x] Defer detailed source/provenance aggregate scans during builder and packaged startup.
- [x] Version database migrations so historical backfills run once instead of on every `Database(...)` open.
- [x] Make `Database.entity()` a lightweight normalized-entity lookup; fetch archived source text only on explicit demand.
- [x] Replace Recent Loot's full item + alias corpus scan with indexed lookups for only observed item names.
- [x] Replace runtime tracked-quest scans with indexed state-key/name/external-ID lookup.
- [x] Cache immutable runtime profile/zone decisions.
- [x] Add/verify runtime indexes for location-by-zone, observed-event cursoring, quest-step zone lookup, and source classification.
- [x] Remove synchronous tracked-quest history replay from startup; replay once per packaged knowledge revision on a split worker connection.

## P1 — remove remaining corpus-size work from interactive paths

- [x] Make entity resolution exact-first; use substring/FTS only as a bounded fallback.
- [x] Remove N+1 alias queries from local search ranking.
- [x] Precompile Activity Pathway objective/drop indexes into the release knowledge DB.
- [x] Precompile canonical quest-step zone IDs for Zone Opportunities.
- [x] Cursor Activity Cluster so refresh cost depends on new events, not total session history.
- [x] Cursor remaining monitoring hot paths that rescan accumulated observations (Recent Loot and Session Ledger); keep explicit Session Recap/history dialogs on-demand.
- [x] Cache immutable runtime world-entity contexts used repeatedly by Target Intelligence and Knowledge detail.
- [x] Audit lower-frequency immutable projections; cache runtime location evidence and base/profile travel graphs.

## P2 — shrink and isolate the shipped runtime artifact

- [x] Strip raw HTML from finalized runtime snapshots.
- [x] Retain bounded 20k source-page text excerpts in runtime; full text/raw HTML remain builder-only.
- [x] Ensure normal packaged EverQuestie never needs an Allakhazam mirror path.
- [x] Keep source import/rebuild/finalization strictly builder-only.
- [x] Keep map-catalog construction builder/manual only; runtime consumes the shipped catalog.

## P3 — builder/import responsiveness

- [x] Move full Allakhazam DB mirror import off Tk's UI thread.
- [x] Move Wiki/saved-folder import variants off Tk's UI thread.
- [x] Avoid `sorted(rglob(...))` full-mirror materialization where ordering is unnecessary.
- [x] Add incremental manifest/hash metadata so unchanged mirror files do not require expensive repeated parsing.
- [x] Add streaming processed-file progress/cancellation to Allakhazam DB and Wiki mirror operations.
- [ ] Consider cancellation for MCP full compile and generic saved-folder import if real builder runs show a need.
- [x] Keep full integrity/audit/VACUUM work in explicit release/diagnostic commands.

## Validation

- [x] Add regression tests proving repeated DB opens do not replay legacy backfills.
- [x] Add tests proving entity reads do not materialize source bodies unless explicitly requested.
- [x] Add tests for exact/ambiguous item identity in optimized Recent Loot lookup.
- [x] Add runtime split tests for tracked quest identity across snapshot row-ID/provider changes.
- [x] Add performance smoke fixtures with a configurable large synthetic entity/alias corpus.
- [x] Record a repeatable large-corpus runtime baseline for DB open, search, first/steady Live projection, and loot refresh; preserve raw JSON for future delta comparisons.

## Field validation / runtime continuity

- [x] Harden continuous EQ log following across repeated appends, truncation, and pathname replacement.
- [x] Add regression coverage proving the log follower observes more than the first post-start append.
- [x] Add regression coverage proving repeated live zone changes trigger Map's current-zone reload path.
- [x] Add an explicit clean-knowledge-build helper that preserves builder inputs and player state by default.
- [ ] Exercise continuous Live + automatic map changes against the real EQ client/log on the development machine.
