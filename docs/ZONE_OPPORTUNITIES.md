# Zone Opportunities

Zone Opportunities answers a narrow player-facing question:

> What untracked quests does the compiled knowledge database explicitly place in my current zone?

It is a read-only projection over structured quest-step zones and canonical zone identity. It does not infer quest ownership and does not search objective prose for place names.

## Difference from Activity Pathways

These two Live-tab discovery surfaces intentionally have different evidence triggers:

- **Potential Pathways** starts from player activity: an exact kill/loot observation matches a structured objective or reviewed source-backed relationship chain.
- **Zone Opportunities** starts from player location: one or more compiled quest steps explicitly name a zone that authoritatively resolves to the player's current canonical zone.

Recent Pathways evidence can rank or annotate a quest that already qualifies as a Zone Opportunity. Activity alone can never create a Zone Opportunity.

## Identity boundary

The player's current zone and every stored quest-step zone string are resolved through EverQuestie's authoritative canonical zone policy.

- exact canonical/client-backed identity is accepted;
- reviewed exact aliases can resolve through the existing zone identity index;
- ambiguous or unresolved zone strings are excluded;
- no substring, containment, fuzzy, prose or nearest-name matching is used.

This keeps provider display-name differences useful where they have canonical identity evidence without allowing a similar-looking zone name to become quest-location truth.

## Quest/profile boundary

A displayed opportunity must satisfy all of the following:

1. the entity is a canonical quest;
2. at least one structured quest step resolves to the current canonical zone;
3. the quest is not already tracked (normal Guidance owns tracked quests);
4. the active gameplay profile does not definitively block the quest.

Unknown lifecycle/profile evidence remains visible and labeled rather than guessed away.

A session-dismissed Potential Pathway quest is also filtered from this Live projection so the player's anti-noise choice does not immediately resurface in another opportunity panel. Session dismissal still changes display only; it does not suppress canonical Knowledge.

## Ranking

Ranking is deterministic context, not a recommendation probability:

1. already-visible recent Activity Pathways matches rank first;
2. quests with more structured objectives in the current zone rank next;
3. quest name/entity ID provide stable tie-breaking.

The panel currently displays up to 15 opportunities.

## Player actions

The Live-tab **What can I accomplish from here?** panel provides:

- **View quest** — exact quest-ID handoff to Knowledge;
- **Track quest** — explicit opt-in to existing quest tracking/reconciliation;
- **Map objective** — delegates the selected structured step to the existing quest-objective navigation projection;
- **Why here?** — shows the structured current-zone steps and profile status that qualified the opportunity.

`Map objective` passes the opportunity's exact step order. The quest does not have to be tracked first. Map/Travel actionability still requires the same canonical target/location evidence as normal quest objective navigation; missing coordinates stay missing rather than being invented.

## Runtime split

Zone Opportunities performs no source access and no knowledge writes at runtime.

- quest/zone/profile facts come from the immutable shipped knowledge database;
- tracked-quest and session-dismiss state are player-owned runtime state;
- viewing or mapping an opportunity changes nothing;
- tracking changes quest state only after the player explicitly chooses **Track quest**.

The feature is useful with synthetic/current quest coverage today and should become substantially broader once the approved Allakhazam DB/wiki mirrors finish and the full knowledge snapshot is rebuilt.
