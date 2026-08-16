# Activity Pathways

Activity Pathways turns the live EverQuest log into a conservative discovery surface for existing EverQuestie knowledge.

The feature does **not** invent quests, infer undocumented relationships, or assume a suggested quest is currently owned. It projects player observations through structured knowledge that is already present in the shipped database.

## First supported signals

The initial implementation uses two exact log-derived signals:

- `kill` observations matched to a structured quest step with an exact NPC target;
- `loot` observations matched to a structured quest step with an exact item target.

Quest-step prose is never searched for mob or item names. A description mentioning an NPC without a structured NPC target is not enough to create a pathway.

Generic EQ kill messages can describe a mob slain by another visible player or group member, so Activity Pathways describes those as **observed slain** rather than claiming every death was the player's personal kill. Loot messages are direct player observations.

## Session boundary

EverQuestie already writes parsed log events to the writable user-state database. When monitoring starts, Activity Pathways records the current highest observed-event ID and considers only later events part of the new monitoring session.

This prevents yesterday's kills and loot from appearing as current activity while preserving the existing event history for quest reconciliation and future session analytics.

No new user-state schema is required for the initial feature.

## Knowledge boundary

The shipped knowledge database remains immutable at runtime.

The opportunity index is built lazily after the first relevant session observation and uses only structured `quest_steps.match_json` targets. Exact entity-backed targets can use canonical entity names/aliases; literal targets use exact normalized text.

Already tracked quests are omitted because normal quest Guidance owns those. Quests definitively outside the active gameplay/server profile are also omitted. Unknown lifecycle evidence remains unknown rather than being guessed away.

## Ranking

Ranking is a relevance aid, not a probability or recommendation model.

Current signals are intentionally simple:

- loot objective matches start stronger than generic kill observations;
- repeated exact observations increase the signal, with a bounded repeat bonus;
- an exact current-zone match adds a small contextual bonus;
- multiple exact objectives supporting the same quest accumulate.

The UI labels the resulting strength as `new`, `medium`, or `high`; these labels mean strength of observed evidence only.

## Player actions

The Live-tab **Potential Pathways** panel provides:

- **View quest** — exact entity-ID handoff to Knowledge;
- **Track quest** — explicit opt-in to existing tracking/reconciliation;
- **Why this?** — lists the exact session observation and structured quest objective that produced the suggestion.

Simply seeing or selecting a pathway never changes tracked quest state or quest progress.

## Runtime split

In packaged mode:

- observations are read from `everquestie-user.sqlite3`;
- quest/entity knowledge is read from the immutable `everquestie-knowledge.sqlite3` snapshot;
- the pathway engine performs no knowledge writes.

Regression coverage hashes the finalized knowledge snapshot before/after a packaged pathway observation and verifies that no knowledge WAL/SHM sidecars are created.

## Planned extensions

Future slices can build on the same evidence model without changing its trust boundary:

1. item → quest relationships beyond direct objective steps;
2. NPC → dropped item → quest chains when all graph edges are source-backed;
3. quest starter / turn-in NPC map and Travel actions;
4. faction-change context correlated with nearby activity, clearly labeled as observation unless canonical causality is known;
5. session summaries (zones visited, mobs observed slain, loot, faction changes, quest progress);
6. personal encounter/drop history stored only in user state;
7. camp/activity clustering based on repeated observations, labeled as inferred session context rather than canonical knowledge.

The completed Allakhazam DB/wiki mirror should increase the breadth of these pathways substantially, but Activity Pathways itself remains source-agnostic: it consumes normalized EverQuestie knowledge rather than crawling or querying providers at runtime.
