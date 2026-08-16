# Personal Observations in Knowledge

EverQuestie keeps canonical EverQuest knowledge and player-owned log history separate.

When a selected Knowledge entity has exact matching observations in the writable user-state event history, the normal player-facing detail pane appends a **Your log observations** block beneath canonical detail/profile information.

The block is explicitly labeled personal/local history. It never changes the shipped knowledge database and never becomes source provenance for a canonical fact.

## Supported entity observations

Current projections include:

- NPC: observed slain, targeted, considered, heard speaking, slain the player, merchant-sale interactions;
- item: player loot count and merchant-sale count;
- faction: standing-better / standing-worse messages;
- zone: entered messages;
- spell: player began-casting messages;
- quest: task-assigned / task-update messages.

Where timestamps exist, the block also shows the first and last matching logged observation.

## Direct corpse-source loot

Modern/live loot lines can explicitly name the corpse source. When the parser has that source:

- an NPC can list item names the player's log explicitly recorded from that NPC's corpse;
- an item can list corpse/source names explicitly recorded when that item was looted.

A generic loot line with no corpse actor is **never** associated with the currently selected NPC by timing, proximity, target, zone, or guesswork.

These observations are not converted into canonical `drops_from` relationships and are not presented as calculated drop rates.

## Identity boundary

Personal observations attach to a Knowledge entity only through exact canonical names/aliases that identify one entity of that kind.

If the same normalized NPC/item/etc. label belongs to multiple canonical entities, the observation stays unattached rather than being assigned to one duplicate.

This is deliberately stricter than saying "the player probably meant this one" and preserves the same no-fuzzy-identity architecture used by routing and source reconciliation.

## Runtime split

In packaged mode:

- entity names/aliases come from immutable `everquestie-knowledge.sqlite3` views;
- `observed_events` comes from writable `everquestie-user.sqlite3`;
- rendering the block performs no knowledge writes.

Regression coverage hashes the knowledge snapshot before/after writing and rendering a personal loot observation and verifies that the knowledge database and sidecars remain untouched.

## Presentation boundary

The personal block composes with the existing player-facing Knowledge renderer:

1. canonical/entity-specific Knowledge detail;
2. source provenance and world relationships;
3. gameplay profile availability;
4. personal log observations, when present.

The raw `--- Primary source text snapshot ---` developer dump remains suppressed in normal Knowledge exactly as before.
