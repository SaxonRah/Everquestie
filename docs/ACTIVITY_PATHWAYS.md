# Activity Pathways

Activity Pathways turns the live EverQuest log into a conservative discovery surface for existing EverQuestie knowledge.

The feature does **not** invent quests, infer undocumented relationships, or assume a suggested quest is currently owned. It projects player observations through structured knowledge that is already present in the shipped database.

## Supported signals

The direct implementation uses two exact log-derived signals:

- `kill` observations matched to a structured quest step with an exact NPC target;
- `loot` observations matched to a structured quest step with an exact item target.

The graph layer also supports reviewed source-backed chains:

- looted item → `objective_turn_in_item` → quest;
- observed NPC slain → `drops_from` item → `objective_loot` or `objective_turn_in_item` → quest.

Every graph relationship must retain source-page provenance. Graph chains also require the observed NPC/item name or alias to resolve to exactly one canonical entity of that kind. If two canonical NPCs or items share the same observed name, EverQuestie leaves the chain unresolved rather than choosing one.

Quest-step prose is never searched for mob or item names. A description mentioning an NPC without a structured NPC target is not enough to create a direct pathway, and arbitrary relationship names are not accepted as graph semantics.

Generic EQ kill messages can describe a mob slain by another visible player or group member, so Activity Pathways describes those as **observed slain** rather than claiming every death was the player's personal kill. Loot messages are direct player observations.

## Session boundary

EverQuestie already writes parsed log events to the writable user-state database. When monitoring starts, Activity Pathways records the current highest observed-event ID and considers only later events part of the new monitoring session.

This prevents yesterday's kills and loot from appearing as current activity while preserving the existing event history for quest reconciliation and future session analytics.

No new user-state schema is required for the current feature.

## Knowledge boundary

The shipped knowledge database remains immutable at runtime.

The opportunity indexes are built lazily after the first relevant session observation. Direct matching uses structured `quest_steps.match_json` targets. Graph matching uses only the reviewed normalized relationship semantics listed above. Exact entity-backed targets can use canonical entity names/aliases; literal direct targets use exact normalized text.

Already tracked quests are omitted because normal quest Guidance owns those. Quests definitively outside the active gameplay/server profile are also omitted. Unknown lifecycle evidence remains unknown rather than being guessed away.

## Ranking

Ranking is a relevance aid, not a probability or recommendation model.

Current signals are intentionally simple:

- direct loot objective matches start strongest;
- direct kill objectives follow;
- possessing an explicit turn-in item is a strong secondary signal;
- mob → drop → quest chains are useful but deliberately weaker than direct observed objectives;
- repeated exact observations increase the signal, with bounded repeat bonuses;
- an exact current-zone match adds a small contextual bonus to direct objectives;
- multiple independent exact signals supporting the same quest accumulate.

The UI labels the resulting strength as `new`, `medium`, or `high`; these labels mean strength of observed evidence only.

## Player actions

The Live-tab **Potential Pathways** panel provides:

- **View quest** — exact entity-ID handoff to Knowledge;
- **Track quest** — explicit opt-in to existing tracking/reconciliation;
- **Navigate contact** — find an evidence-backed quest contact and delegate safely to Map or Travel;
- **Why this?** — lists the exact session observation and structured objective/relationship chain that produced the suggestion.

### Navigate contact

A potential pathway is not assumed to be owned yet, so navigation prefers a structured `started_by` quest starter. If no safely navigable starter location is known, an explicit `objective_turn_in_to` NPC may be offered as a useful fallback. Kill targets and unrelated quest actors are never substituted for those roles.

The action does not create coordinates or resolve provider ambiguity itself. It delegates to the same `knowledge_map_choices` projection used by normal Knowledge actions:

- only navigable canonical location evidence can become a Map/Travel choice;
- a current-zone contact is handed to the Map owner in game-space coordinates;
- a remote contact is collapsed to a canonical destination zone and handed to Travel;
- multiple safe points or remote zones require the existing explicit chooser;
- candidate/unresolved provider locations remain evidence-only.

Simply seeing, selecting, viewing, or navigating a pathway never changes tracked quest state or quest progress.

## Runtime split

In packaged mode:

- observations are read from `everquestie-user.sqlite3`;
- quest/entity/relationship knowledge is read from the immutable `everquestie-knowledge.sqlite3` snapshot;
- the pathway engine performs no knowledge writes.

Regression coverage hashes the finalized knowledge snapshot before/after a packaged pathway observation and verifies that no knowledge WAL/SHM sidecars are created.

## Planned extensions

Future slices can build on the same evidence model without changing its trust boundary:

1. faction-change context correlated with nearby activity, clearly labeled as observation unless canonical causality is known;
2. session summaries (zones visited, mobs observed slain, loot, faction changes, quest progress);
3. personal encounter/drop history stored only in user state;
4. camp/activity clustering based on repeated observations, labeled as inferred session context rather than canonical knowledge;
5. additional relationship-chain shapes only after their normalized semantics and provenance requirements are reviewed.

The completed Allakhazam DB/wiki mirror should increase the breadth of these pathways substantially, but Activity Pathways itself remains source-agnostic: it consumes normalized EverQuestie knowledge rather than crawling or querying providers at runtime.
