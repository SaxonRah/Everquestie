# Conservative map-label travel syntax

EverQuestie's map-derived route compiler only promotes labels that contain explicit travel intent supplied by the map author. It does not infer routes from arbitrary text or from a bare zone name.

Travel catalog v2 recognizes explicit forms including:

- `To <zone>` and punctuation variants such as `To: <zone>`;
- `Zone Line to <zone>`, `Zoneline: <zone>`, `ZL to <zone>` and `Z/L <zone>`;
- suffix forms such as `<zone> Zone Line` and `<zone> ZL`;
- `Portal`, `Teleport`, `Teleporter`, `Exit` and `Entrance` forms with `to`, `:`, `-` or `=` separators.

The destination still has to resolve through EverQuestie's canonical zone identity index. Unresolved and ambiguous destinations remain stored as such rather than being guessed.

A bare label such as `Blightfire Moors` is intentionally **not** a route by itself. Maps can use zone names as landmarks, annotations or contextual labels. Bare-name topology should only be added in a future reconciliation layer when independent evidence can corroborate that the label really represents an exit.

Travel evidence remains directed unless a provider explicitly says it is bidirectional. A source-side map coordinate belongs only to the direction represented by that label.

Builder navigation catalog v3 recompiles the already-indexed `map_labels` once after this syntax expansion. It does not crawl the player's map folder. Finalized release snapshots compile the same travel parser before packaging.
