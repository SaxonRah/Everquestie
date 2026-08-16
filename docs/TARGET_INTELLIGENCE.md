# Target Intelligence

Target Intelligence answers a live-play question without guessing:

> I just targeted or considered this NPC. What exact knowledge does EverQuestie already have about it, and can I safely navigate to it?

The model is owned by `eqquest.target_intelligence`. The Live UI is a read-only projection over that model plus the existing Knowledge Map/Travel actionability layer.

## Current-target boundary

Target Intelligence uses the same monitoring-session boundary as the rest of Activity Intelligence. Only observations after monitoring begins can establish the current target.

The newest relevant boundary event wins:

- `target_npc` establishes an NPC target;
- `consider` establishes an NPC target because the log names the exact considered NPC;
- `target_player` clears an older NPC target;
- `zone` clears an older NPC target;
- `welcome` clears an older NPC target after login/reconnect.

This prevents stale target context from surviving a player target, zone transition or new game session.

## Identity boundary

The observed target text must resolve to exactly one canonical NPC identity by:

1. exact normalized canonical NPC name; or
2. exact normalized alias when that alias belongs to exactly one canonical NPC.

Duplicate names or aliases fail closed. Target Intelligence does not use substring matching, current-zone guessing, nearby entities, quest context or fuzzy similarity to break identity ambiguity.

## Compact knowledge projection

For a resolved exact NPC, the compact Live strip can show:

- canonical NPC name;
- known level/range from canonical entity data;
- source-backed normalized relationship counts with short examples;
- canonical/linked gameplay zones only;
- personal log observation counts;
- active gameplay-profile availability status.

Relationship counts are counts of distinct related canonical entities, not counts of provenance rows. Source-less relationships are excluded from the compact strip.

Provider candidate/unresolved geography remains evidence in full Knowledge but is not promoted to a compact gameplay location.

## Live actions

The **Target Intelligence** panel exposes explicit actions:

- **View target** — open the exact canonical NPC in Knowledge;
- **Navigate** — project that same exact NPC through the existing safe Knowledge location layer;
- **Details** — show the fuller exact-identity/source-backed target summary.

`Navigate` does not invent a location:

- a safe independently sourced point in the current canonical zone is handed to Map;
- safe remote canonical locations are collapsed into explicit Travel destination choices;
- multiple safe choices require explicit player selection;
- provider candidate/unresolved coordinates stay non-actionable;
- Travel still owns route computation and route evidence.

## Refresh ownership

Target Intelligence does not run its own permanent SQLite polling loop. The UI decorates the existing Activity Intelligence refresh and reuses `_activity_session_start_event_id`.

That means one activity cadence owns:

- Potential Pathways;
- Current Activity;
- Current-zone opportunities;
- Recent Loot Relevance;
- Target Intelligence.

Starting monitoring resets the shared session boundary, and gameplay-profile refreshes flow through the same activity refresh chain.

## Runtime split

In packaged mode:

- target/consider/zone/session observations live in writable `everquestie-user.sqlite3`;
- NPC identity, relationships, locations and profile evidence come from immutable `everquestie-knowledge.sqlite3`;
- no source access, knowledge write or schema change occurs at runtime.

Breadth should increase automatically as completed builder sources add more exact NPC relationships and safe locations to future shipped snapshots.
