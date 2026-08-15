# Allakhazam mirror relationship link resolution

EverQuestie's Allakhazam integration is builder-only. The packaged application consumes normalized, finalized knowledge and never depends on the local HTTrack mirror.

## Why mirror links need a source-URL recovery layer

A mirrored page has two different identities:

1. its local HTTrack filename, which exists only so the mirror can be browsed offline;
2. its canonical Allakhazam URL, which is the provenance/identity EverQuestie is allowed to normalize.

HTTrack's normal mirror mode rewrites same-site links to local relative filenames. Query-bearing URLs can receive a generated suffix in that local filename while retaining the query string. A saved Connected Zones row can therefore point at a local-looking relative href even though the page itself has a valid canonical `everquest.allakhazam.com` source URL.

The original structured importer accepted a relationship target only when the href was already an absolute `http(s)://everquest.allakhazam.com/...` URL. That was safe for hand-authored fixtures but incorrect for the actual mirror provider: the page itself could import successfully from its canonical URL while its Connected Zones relationships were silently skipped.

## Mirror-specific recovery policy

`AllakhazamMirrorImporter` leaves the ordinary Allakhazam parser and all relationship semantics unchanged. It only presents source-safe URLs to that parser while a local mirror page is being extracted.

`normalize_allakhazam_mirror_href()` supports:

- ordinary absolute Allakhazam links;
- protocol-relative Allakhazam links;
- root-relative links;
- relative links resolved against the page's already-proven canonical Allakhazam URL;
- HTTrack query-page filenames whose basename still begins with a known Allakhazam DB entity stem (`zone`, `quest`, `item`, `npc`) and whose query contains the expected structured identity key.

For the last case, only the local rewritten basename is restored to the corresponding `/db/<kind>.html` source path. The structured query string is preserved.

## Safety boundaries

The recovery layer does **not** turn arbitrary local or external URLs into source evidence.

- `file:`, `javascript:`, `data:` and other non-web schemes are not promoted.
- A resolved URL must still belong to exactly `everquest.allakhazam.com` before the normal importer will accept it.
- A rewritten `/db/` basename is canonicalized only when its basename begins with a known entity stem and its query contains an expected key for that entity family.
- No display-name fuzzy matching is introduced.
- No travel edge is invented by the recovery layer. It only allows an existing structured Connected Zones row to reach the existing provider-zone reconciliation and provider-travel compilers.
- Existing direction semantics (`Both`, exact `Entrance To`, exact `Exit From`, conservative forward-only fallback) remain owned by provider travel compilation.

## Regression contract

The permanent tests use a mirror-shaped Connected Zones href such as:

```text
zone4B54.html?zone=166
```

rather than an unrealistic fully absolute fixture link. They prove the complete path:

```text
HTTrack relative href
  -> canonical same-host Allakhazam relationship URL
  -> structured connected_to relationship
  -> conservative provider-zone binding
  -> provider travel compilation
  -> finalized canonical bidirectional travel edge
```

The same fixture contains an external-host lookalike and proves it is not imported as a relationship target.

## Build diagnostics

`tools/build_knowledge_db.py` prints the finalized provider-zone reconciliation and provider-zone travel counters directly after snapshot integrity. In particular, the next real build exposes:

- provider zones `linked`, `candidate`, `ambiguous`, `unresolved`;
- provider travel `relationships_scanned`, `linked`, `ignored_unstructured`, `blocked_source`, `blocked_target`, and `self_edges`.

These counters distinguish three failure classes immediately:

1. the mirror did not produce structured Connected Zones relationships (`relationships_scanned=0`);
2. relationships exist but provider endpoints are not projection-safe (`blocked_source` / `blocked_target`);
3. relationships successfully reach the canonical travel graph (`linked>0`).

The route acceptance audit remains the downstream player-journey check after those source/compiler diagnostics are healthy.
