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

This is therefore a **P99-style compatibility profile over the current EverQuestie corpus**, not a claim that a Live EverQuest installation contains a byte-perfect Project 1999 dataset.

## Profile-aware Knowledge

Knowledge remains a view of the complete shipped corpus. Selecting P99-style does **not** hide or delete Live-era records.

The selected entity detail now includes a `Gameplay profile availability` section. The projection uses only direct canonical world evidence that is already safe elsewhere in EverQuestie:

- the entity's canonical zone field when it resolves authoritatively;
- canonicalized location evidence;
- explicit normalized zone relationships such as `occurs_in`, `starts_in`, and `found_in`;
- structured quest-step zone fields for quests.

Zone identities are definitive because the world-profile layer already owns zone lifecycle policy.

For quests and NPCs, if every directly evidenced canonical zone is blocked by the selected profile, Knowledge may report `OUTSIDE PROFILE`.

For portable entity kinds such as items and spells, an out-of-profile known location is **not** enough to declare the entity unavailable. The corpus may be missing another acquisition, vendor, drop, recipe, or era-specific source. Those cases remain `UNDETERMINED` until stronger lifecycle/expansion evidence is compiled.

If direct evidence spans both allowed and blocked zones, Knowledge reports `MIXED / UNDETERMINED` rather than guessing an era.

This distinction is intentional: profile compatibility is a sourced projection, not a blacklist.

## Profile-aware tracked quest guidance

Quest tracking and observed progress remain writable player state and are never discarded merely because the selected profile disagrees with the quest's known world evidence.

When an active structured quest step points at a canonical zone that is blocked by the selected profile, Live guidance:

- retains the objective text and progress;
- does not emit the old `Travel from ... to ...` recommendation for that blocked destination;
- explains that the destination is outside the selected gameplay profile;
- continues to process matching observed log events.

This matters for custom servers, stale profile choices, and real-world server differences: the log is evidence that the player did something, so EverQuestie preserves it instead of rewriting history to satisfy a profile setting.

A reviewed classic destination such as `North Freeport` remains usable under the P99-style profile even though the same identity is excluded from Live.

## Unrestricted / custom profile

`Unrestricted / custom` traverses every confirmed canonical travel edge in the finalized knowledge graph regardless of era and treats compiled entities as available for compatibility projection.

It is useful for:

- topology diagnostics;
- custom/private server configurations that intentionally mix eras;
- inspecting whether a route or entity warning in another profile is caused by profile availability rather than missing compiled evidence.

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
- immediately re-renders the currently selected Knowledge entity when possible;
- immediately refreshes tracked-quest guidance;
- leaves the knowledge snapshot unchanged.

Route output is explicitly labelled with the profile. The same Travel owner is used by direct Travel queries, Knowledge → Travel handoffs, and Live tracked-objective navigation.

## Current lifecycle overrides

The initial reviewed override set is intentionally small:

- `North Freeport` — excluded from Live; enabled for Classic/P99-style;
- `The Plane of Knowledge` — excluded from Classic/P99-style;
- `Guild Lobby` — excluded from Classic/P99-style;
- `Guild Hall` — excluded from Classic/P99-style.

These overrides are runtime availability statements, not entity aliases or deletions. Expand them only with reviewed lifecycle/server evidence; do not add ad-hoc blacklist entries merely to make a route or entity look plausible.

## Next lifecycle work

The same global profile ID can now be reused by deeper server-aware projections. The next high-value evidence is explicit lifecycle/expansion availability for quests, NPCs, items, spells, tradeskills, class/level rules, and mechanics.

Until those facts are compiled, EverQuestie should prefer `UNDETERMINED` over making a confident server-era claim from incomplete evidence.
