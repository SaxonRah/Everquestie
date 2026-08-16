# Recent Loot Relevance

Recent Loot Relevance answers a narrow player-facing question while EverQuestie is tailing the log:

> I just looted this item. Does the compiled knowledge database know why I might care about it?

It is a read-only projection over the current monitoring session plus source-backed quest relationships. It is deliberately not a vendor-trash classifier.

## Observation boundary

The feature uses the same monitoring-session boundary as Potential Pathways. Only `loot` events written after monitoring starts are considered current loot.

- older stored observations remain available to quest reconciliation and personal Knowledge history;
- restarting monitoring begins a fresh Recent Loot Relevance session;
- repeated exact loot observations are counted for context;
- the feature does not inspect inventory memory or the EverQuest UI.

## Identity boundary

A logged item name or exact normalized alias must resolve to exactly one canonical `item` entity.

If two canonical items share the same observed name/alias, EverQuestie leaves the observation unattached rather than guessing which item was looted.

## Reviewed quest relationships

Only source-backed relationships with a retained `source_page_id` participate:

- `objective_turn_in_item` — an explicit structured quest objective requires handing in the item;
- `objective_loot` — an explicit structured quest objective requires looting the item;
- `quest_item` — the source explicitly lists the item in its structured Quest Items field.

The first two are stronger semantics than the broader source-listed `quest_item` relationship and are ordered first in the UI.

Quest-step prose, item names, comments, nearby mobs and timestamps are never interpreted as item usefulness.

## Gameplay profile

A quest that is definitively outside the active gameplay/server profile is omitted. Unknown lifecycle evidence stays unknown rather than being guessed available or unavailable.

Tracked quests remain visible because a looted item can be relevant to something the player is already working on. The panel labels tracked uses explicitly.

## Live UI

The **Recent Loot Relevance** panel appears beneath the other Activity Intelligence surfaces and shows:

- the exact canonical item;
- how many times it was looted during the monitoring session;
- the known quest using it;
- whether the relationship is a turn-in item, loot objective, or source-listed quest item;
- explicit quantity where the structured relationship provides one;
- tracked/profile context.

Actions are explicit:

- **View item** — exact item-ID handoff to Knowledge;
- **View quest** — exact quest-ID handoff to Knowledge;
- **Track quest** — opt in to the existing quest tracking/reconciliation workflow;
- **Why relevant?** — display the source-backed relationship evidence.

Simply seeing or viewing an item never changes quest state.

## Important negative result

If the panel does not display an item, EverQuestie is **not** saying the item is junk.

The absence can mean any of the following:

- current knowledge coverage does not yet contain the relevant quest page;
- the item has non-quest significance not represented by the reviewed relationships above;
- canonical item identity is ambiguous;
- the relevant quest is outside the selected gameplay profile;
- no reviewed source-backed relationship exists yet.

This distinction becomes especially important while the approved Allakhazam DB/wiki mirrors are still completing.

## Runtime split

In packaged mode:

- loot observations come from writable `everquestie-user.sqlite3`;
- item/quest/relationship/profile facts come from immutable `everquestie-knowledge.sqlite3`;
- the projection performs no source access and no knowledge writes;
- no schema change is required.

The feature should gain breadth automatically when the completed mirrors are compiled into a richer shipped knowledge snapshot.
