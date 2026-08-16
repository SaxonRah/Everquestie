# Session Activity Recap

The Live-tab **Session recap** action summarizes the monitoring session that began when the player pressed **Start monitoring**.

It is a read-only projection over EverQuestie's existing writable `observed_events` user-state history. No knowledge rows are created or changed, and no new user-state schema is required.

## Session boundary

At monitoring start EverQuestie records:

- the current highest observed-event ID;
- the zone recovered from the selected log by normal startup/bootstrap logic.

Only later stored events count toward the recap. The preserved starting zone plus later `zone` events allow a session path such as `South Qeynos → Qeynos Catacombs` without replaying older history or claiming a zone visit that was not part of the current monitoring session.

Stopping monitoring keeps the last session boundary in memory so the recap remains viewable until another monitoring session begins.

## Reported observations

The current recap includes:

- zones seen/current;
- mobs observed slain and the most frequently observed mob names;
- items the player looted and the most frequently looted item names;
- faction standing-change messages, separated into better/worse counts;
- deaths;
- levels gained/lost;
- task assignments/updates;
- merchant sales observed;
- the number of Potential Pathways currently surfaced.

Names are normalized only for counting case/spacing variants; the displayed label remains an observed log label.

## Truth boundary

Generic EverQuest kill lines can represent mobs killed by another visible/group player. The recap therefore says **mobs observed slain**, not personal kills.

Faction messages are contemporaneous observations. The recap does not say that a specific mob kill caused a faction change unless a separate canonical knowledge source explicitly supports that causal relationship.

The recap is session analytics, not canonical EverQuest knowledge. Persistent personal encounter history can build on the same user-state observations later without altering the shipped knowledge database.
