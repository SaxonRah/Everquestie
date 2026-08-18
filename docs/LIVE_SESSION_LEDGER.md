# Live session ledger

EverQuestie's Live tab keeps the parsed EQ event tail as the chronological source of truth and can annotate kill and loot rows with conservative local intelligence.

The left-hand `Observed EQ events` surface is labeled **Live session ledger** when this layer is installed. The parent row remains the original `Event.summary()` text. Derived rows are visibly indented with `↳` and never replace or rewrite the parsed observation.

## Kill tracking

For each persisted `kill` event after the current monitoring-session boundary, the ledger counts observations of that exact mob text in the current session.

The parser distinguishes two cases:

- `You have slain <mob>!` becomes a kill whose recorded killer is `You`. The ledger labels this a **personal kill**.
- `<mob> has been slain by <name>!` is only an **observed slain** event unless `<name>` is `You`. The ledger names the observed killer when available and explicitly says that no personal kill credit is inferred.

This matches the quest-progress safety rule: generic slain lines can inform activity/pathway discovery but cannot mutate a tracked kill objective as though the player received credit.

## Loot tracking

Each loot row shows the exact item name and its count since monitoring began. If the EQ log supplied an explicit corpse source, the ledger retains that personal observation as context.

A corpse source is not promoted into a canonical drop relationship or drop-rate claim. Canonical item/source knowledge remains owned by reviewed knowledge relationships.

## Potential pathways

The ledger reuses the existing `ActivityPathwayEngine` session counters and its current source-backed `PathwaySuggestion` objects. Matching kill/loot rows can therefore show `POTENTIAL PATHWAY` annotations immediately beneath the observation.

The annotation preserves the same boundaries as the dedicated Potential Pathways panel:

- exact structured quest objectives only;
- reviewed normalized relationship chains only;
- no fuzzy/prose quest inference;
- zone-bound kill objectives require matching explicit current zone context;
- tracked quests are not re-presented as potential unowned pathways.

The full Potential Pathways panel remains the owner of `View quest`, `Track quest`, and navigation actions.

## Tracked quest context

A kill or loot row can show `TRACKED QUEST CONTEXT` when its exact subject matches a source-backed structured step of an already tracked quest.

This annotation deliberately does **not** say that the row increased progress. Current progress remains owned by the quest tracker. In particular, a generic slain line explicitly states that the observation does not prove the player's kill credit.

A future progress-journal feature can add durable event-to-progress provenance. The ledger will not reconstruct that causality after the fact.

## Item relevance

Loot rows also reuse the existing Recent Loot Relevance projection. Exact canonical items with reviewed source-backed quest relationships can show `ITEM RELEVANCE` annotations such as:

- turn-in item;
- loot objective;
- source-listed quest item.

Tracked quest uses are labeled. An item with no displayed relationship is never classified as vendor trash or useless.

## Runtime and storage boundary

The ledger adds no crawler, provider, or source access. It reads:

- `observed_events` from writable player state;
- immutable packaged entities, quest steps, aliases, profile decisions, and reviewed relationships through the existing runtime database projection.

It adds no new user-state schema and writes no derived ledger rows to knowledge. Starting a new monitoring session resets the ledger boundary to the same event ID used by Potential Pathways, so old observations do not inflate the new session's kill or loot counts.
