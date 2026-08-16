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

This prevents yesterday's kills and loot from appearing as current activity while preserving the existing event history for quest reconciliation, personal observations, and session analytics.

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
- **Why this?** — lists the exact session observation and structured objective/relationship chain that produced the suggestion;
- **Session recap** — summarizes parsed activity since monitoring started without promoting it into canonical knowledge;
- **Dismiss selected for session** — hides one opportunity until the next monitoring session without altering quest or database state.

### Navigate contact

A potential pathway is not assumed to be owned yet, so navigation prefers a structured `started_by` quest starter. If no safely navigable starter location is known, an explicit `objective_turn_in_to` NPC may be offered as a useful fallback. Kill targets and unrelated quest actors are never substituted for those roles.

The action does not create coordinates or resolve provider ambiguity itself. It delegates to the same `knowledge_map_choices` projection used by normal Knowledge actions:

- only navigable canonical location evidence can become a Map/Travel choice;
- a current-zone contact is handed to the Map owner in game-space coordinates;
- a remote contact is collapsed to a canonical destination zone and handed to Travel;
- multiple safe points or remote zones require the existing explicit chooser;
- candidate/unresolved provider locations remain evidence-only.

Simply seeing, selecting, viewing, or navigating a pathway never changes tracked quest state or quest progress.

### Session-only dismissal

Dismissal is deliberately a display preference, not knowledge or quest state.

The UI keeps dismissed quest IDs only in memory for the active monitoring session. The underlying pathway engine continues to compute the source-backed opportunity, but the Live tree and Current Activity related-pathway text filter it out. Starting monitoring again clears the dismissed set and begins a fresh session context.

This first anti-noise control intentionally avoids permanent snooze metadata or a user-state schema change. If a longer-lived ignore/snooze feature is added later, it should remain player-owned state and must never suppress canonical knowledge itself.

## Current Activity cluster

The Live tab also projects a compact **Current Activity** log pattern. This is session context, not canonical EverQuest knowledge and not a claim that the player is at a named camp.

The cluster:

- uses the same monitoring-session boundary as Potential Pathways;
- resets its segment at the latest logged zone transition, so old-zone activity does not follow the player into a new zone;
- summarizes repeated mobs observed slain and items the player looted;
- stays quiet for one-off activity;
- names only already-surfaced, non-dismissed Potential Pathways whose exact evidence overlaps the cluster;
- can show faction-standing messages that occurred in the same current-zone segment;
- continues to describe generic kill lines as `observed slain`, not guaranteed personal kills.

The initial noise threshold is deliberately conservative: at least three relevant kill/loot observations are required, plus either a repeated subject or at least five total relevant observations. Faction messages do **not** contribute to this threshold or to pathway ranking.

Faction context is deliberately temporal rather than causal. A line such as `Guards of Qeynos better ×2` means those faction messages were logged during the same current activity segment. EverQuestie does not infer that a displayed mob, item, quest, or other activity caused those faction changes unless a future reviewed source explicitly proves that relationship.

## Personal observations in Knowledge

Player-owned history is also available from normal Knowledge detail. Exact unambiguous entity names/aliases can project logged observations such as loot count, mobs observed slain, faction messages, casts, task messages, and explicit corpse-source loot.

That history remains user-state data. It never creates canonical `drops_from` relationships or calculated drop rates, and ambiguous duplicate canonical names remain unattached.

## Runtime split

In packaged mode:

- observations are read from `everquestie-user.sqlite3`;
- quest/entity/relationship knowledge is read from the immutable `everquestie-knowledge.sqlite3` snapshot;
- session dismissal is in-memory UI state only;
- the pathway, activity-cluster, recap, faction-context and personal-observation projections perform no knowledge writes.

Regression coverage hashes finalized knowledge in packaged-mode activity/personal-history tests and verifies that no knowledge WAL/SHM sidecars are created.

## Planned extensions

Future slices can build on the same evidence model without changing its trust boundary:

1. optional persistent snooze/ignore state if session-only dismissal proves insufficient;
2. longer-term encounter statistics that remain explicitly personal observations rather than canonical rates;
3. additional relationship-chain shapes only after their normalized semantics and provenance requirements are reviewed;
4. profile-aware nearby-opportunity summaries as richer quest/NPC/item coverage arrives from the completed mirrors;
5. source-backed faction causality only where a reviewed provider explicitly supplies it.

The completed Allakhazam DB/wiki mirror should increase the breadth of these pathways substantially, but Activity Pathways itself remains source-agnostic: it consumes normalized EverQuestie knowledge rather than crawling or querying providers at runtime.
