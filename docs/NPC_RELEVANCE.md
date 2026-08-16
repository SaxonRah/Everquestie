# Recent NPC Relevance

Recent NPC Relevance answers a live-play question:

> I just targeted or considered this NPC. Does the compiled knowledge database know why this NPC matters to quests?

It is a source-backed projection over intentional current-session NPC observations. It does not infer quest relevance from nearby speech, generic combat text, NPC names, or prose.

## Observation boundary

Only log events after the current monitoring-session boundary participate, and only these event kinds are accepted:

- `target_npc` — the player explicitly targeted an NPC;
- `consider` — the player explicitly considered an NPC.

The initial version intentionally excludes:

- `npc_say`, because nearby NPC speech does not prove player interaction;
- generic `kill`, because Potential Pathways already owns activity-to-quest projection and a generic slain line does not necessarily mean the player killed the NPC;
- proximity guesses, chat-name extraction and fuzzy matching.

Repeated target/consider observations are counted only as player context; they never create a knowledge relationship.

## Identity boundary

The logged NPC name or exact normalized alias must resolve to exactly one canonical `npc` entity.

If the same observed name/alias belongs to multiple canonical NPC identities, the observation remains unattached. Current zone, quest context and substring similarity are not used to break that ambiguity.

## Reviewed quest connections

Only source-backed incoming quest relationships with a retained `source_page_id` participate:

- `started_by` — this NPC is an explicit quest starter;
- `objective_turn_in_to` — this NPC is an explicit turn-in contact;
- `objective_speak` — this NPC is an explicit speak objective;
- `objective_kill` — this NPC is an explicit kill objective.

Tracked quests are kept and ranked first because an observed NPC may be immediately relevant to work the player already chose to track. Untracked quests are discovery opportunities. A quest definitively outside the active gameplay profile is omitted; unknown lifecycle evidence remains unknown rather than being guessed.

## Live UI

The **Recent NPC Relevance** panel appears beneath the other Activity Intelligence surfaces and shows:

- exact canonical NPC;
- current-session target/consider counts;
- connected quest;
- explicit relationship type;
- tracked/profile context.

Actions are explicit:

- **View NPC** — open the exact NPC in Knowledge;
- **View quest** — open the exact quest in Knowledge;
- **Track quest** — opt in to normal quest tracking/reconciliation;
- **Navigate NPC** — use the existing Knowledge safe-location projection; current-zone evidence goes to Map, remote canonical evidence goes to Travel;
- **Why relevant?** — show the observed signal and source-backed relationship evidence.

Seeing or viewing a relevance row never changes quest state.

## Navigation boundary

The quest relationship explains why the NPC is interesting. It does not create a coordinate.

`Navigate NPC` asks the existing `knowledge_map_choices()` projection for independently sourced, canonical, navigable NPC locations. Therefore all existing safeguards remain in force:

- provider candidate/unresolved coordinates stay non-actionable;
- ambiguous current zone identity is not guessed;
- multiple safe points require explicit selection;
- a remote safe location is handed to Travel as a canonical destination zone;
- Travel owns route computation and route evidence.

## Runtime split

In packaged mode:

- target/consider observations come from writable `everquestie-user.sqlite3`;
- NPC, quest, relationship, profile and location facts come from immutable `everquestie-knowledge.sqlite3`;
- no source access or knowledge write occurs at runtime;
- no schema change is required.

Like the other Activity Intelligence surfaces, breadth should increase automatically as the completed Allakhazam DB/wiki mirrors add more structured NPC and quest relationships to future shipped knowledge snapshots.
