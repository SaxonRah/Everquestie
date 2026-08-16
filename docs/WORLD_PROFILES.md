# EverQuestie gameplay / world profiles

EverQuestie keeps one provenance-rich knowledge database and applies gameplay-profile availability at read time. Historical knowledge is not deleted merely because it is unavailable on the currently selected server ruleset.

## Default profile: Live

`Live (default)` is the normal EverQuestie gameplay profile.

- current compiled topology remains routeable;
- reviewed retired/historical identities such as `North Freeport` remain searchable knowledge but are excluded from normal Live routes;
- modern hubs such as the Plane of Knowledge remain available;
- route direction still comes only from confirmed directed/two-way evidence.

This is the profile used when no user preference has been stored or when a stored profile value is invalid.

## Classic / P99-style profile

`Classic / P99-style (Velious cap)` is the first alternate compatibility profile.

The current implementation is deliberately conservative about what the existing Live-oriented corpus can prove:

- reviewed historical classic identities such as `North Freeport` may be enabled;
- modern universal travel hubs such as the Plane of Knowledge, Guild Lobby, and Guild Hall are explicitly excluded;
- zones positively identified by compiled provider/client expansion evidence as post-Velious are excluded;
- Classic, Kunark, and Velious expansion evidence is accepted;
- a zone with no compiled era statement is not silently labelled Classic or post-Velious. It remains routeable with `era_unknown` status until stronger lifecycle evidence is compiled.

This is therefore a **P99-style routing compatibility profile over the current EverQuestie corpus**, not a claim that a Live EverQuest installation contains a byte-perfect Project 1999 dataset.

A complete server-specific knowledge experience will eventually need the same profile boundary applied to additional facts such as quests, NPC availability, item eras, spells, class/level rules, tradeskills, and mechanics. The profile ID introduced here is intentionally global user state so those projections can reuse it rather than inventing independent server selectors.

## Unrestricted / custom profile

`Unrestricted / custom` traverses every confirmed canonical travel edge in the finalized knowledge graph regardless of era.

It is useful for:

- topology diagnostics;
- custom/private server configurations that intentionally mix eras;
- inspecting whether a route failure in another profile is caused by profile availability rather than missing compiled evidence.

Unrestricted mode still does **not** invent reverse edges, fuzzy zone identities, or unconfirmed travel.

## Storage boundary

The active profile is stored under the existing user metadata interface as `world_profile`.

In packaged runtime, `RuntimeDatabase.set_meta()` writes this preference to the writable user-state database. The immutable `everquestie-knowledge.sqlite3` snapshot is never changed when the player switches profiles.

The knowledge database continues to preserve all compiled source evidence and historical identities. Profiles are read-time availability projections.

## Routing semantics

Profile filtering happens after exact canonical endpoint resolution and before breadth-first route traversal.

For a normal profile:

1. resolve start and destination through the existing canonical zone authority rules;
2. evaluate both endpoints against the active profile;
3. build adjacency only from confirmed `zone_travel_edges` whose source and target zones are allowed by that profile;
4. preserve existing directed/bidirectional semantics exactly;
5. find the shortest path within that filtered graph;
6. render hop evidence/coordinates/requirements through the existing Route Guidance layer.

If unrestricted knowledge contains a route but the selected profile blocks one or more zones on that path, Travel reports that distinction rather than describing the route as missing source topology.

## UI behavior

Travel exposes a `Gameplay profile` selector. Changing it:

- persists the new user preference;
- invalidates any cached route;
- requires route recalculation before `Map next hop` can continue;
- leaves the knowledge snapshot unchanged.

Route output is explicitly labelled with the profile. The same Travel owner is used by direct Travel queries, Knowledge → Travel handoffs, and Live tracked-objective navigation.

## Current lifecycle overrides

The initial reviewed override set is intentionally small:

- `North Freeport` — excluded from Live; enabled for Classic/P99-style;
- `The Plane of Knowledge` — excluded from Classic/P99-style;
- `Guild Lobby` — excluded from Classic/P99-style;
- `Guild Hall` — excluded from Classic/P99-style.

These overrides are runtime availability statements, not entity aliases or deletions. Expand them only with reviewed lifecycle/server evidence; do not add ad-hoc blacklist entries merely to make a route look plausible.
