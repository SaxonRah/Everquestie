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
- HTTrack query-page filenames whose basename still begins with a known Allakhazam DB entity stem (`zone`, `quest`, `item`, `npc`, `spell`) and whose query contains the expected structured identity key.

For the last case, only the local rewritten basename is restored to the corresponding `/db/<kind>.html` source path. The structured query string is preserved.

Spell pages are a narrower lifecycle-only case. A numeric `/db/spell.html?spell=<id>` canonical URL makes the page structurally recognizable, but its lifecycle value is accepted only from the labeled Quick Facts `Expansion` field. Comments, descriptions, dates, levels and arbitrary prose are not promoted into spell lifecycle evidence.

## Safety boundaries

The recovery layer does **not** turn arbitrary local or external URLs into source evidence.

- `file:`, `javascript:`, `data:` and other non-web schemes are not promoted.
- A resolved URL must still belong to exactly `everquest.allakhazam.com` before the normal importer will accept it.
- A rewritten `/db/` basename is canonicalized only when its basename begins with a known entity stem and its query contains an expected key for that entity family.
- No display-name fuzzy matching is introduced.
- Allakhazam spell lifecycle attaches to a canonical client spell only after exact numeric ID **and** exact normalized-name corroboration.
- No travel edge is invented by the recovery layer. It only allows an existing structured Connected Zones row to reach the existing provider-zone reconciliation and provider-travel compilers.
- Existing direction semantics (`Both`, exact `Entrance To`, exact `Exit From`, conservative forward-only fallback) remain owned by provider travel compilation.

## Regression contract

The permanent travel tests use a mirror-shaped Connected Zones href such as:

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

Spell regressions separately cover an HTTrack-shaped spell link, exact client-spell attachment, and rejection of comment/prose `Expansion:` lookalikes.

The travel fixture contains an external-host lookalike and proves it is not imported as a relationship target.

## Read-only mirror coverage audit

Before rebuilding knowledge from a manually refreshed mirror, inspect what the completed HTTrack tree actually contains:

```powershell
python .\tools\audit_allakhazam_mirror.py "C:\path\to\everquest.allakhazam.com"
```

Use `--json` for machine-readable output. The audit performs no network access and no database writes. In addition to unique structured pages by kind, it reports:

- `spell_pages`: unique numeric Allakhazam spell pages present in the mirror;
- `spell_pages_with_expansion`: spell pages whose Quick Facts contain the reviewed `Expansion` field;
- `spell_pages_missing_expansion`: captured spell pages that are structurally recognizable but do not currently supply that reviewed lifecycle fact.

The lifecycle-ready count uses the same Quick Facts parser as the production mirror importer. A comment containing the word `Expansion` therefore does not increase coverage.

## Build diagnostics

`tools/build_knowledge_db.py` prints the finalized provider-zone reconciliation and provider-zone travel counters directly after snapshot integrity. In particular, the next real build exposes:

- provider zones `linked`, `candidate`, `ambiguous`, `unresolved`;
- provider travel `relationships_scanned`, `linked`, `ignored_unstructured`, `blocked_source`, `blocked_target`, and `self_edges`.

These counters distinguish three failure classes immediately:

1. the mirror did not produce structured Connected Zones relationships (`relationships_scanned=0`);
2. relationships exist but provider endpoints are not projection-safe (`blocked_source` / `blocked_target`);
3. relationships successfully reach the canonical travel graph (`linked>0`).

For spell lifecycle, run the mirror coverage audit before import and the profile lifecycle audit after import/finalization. The first establishes what source pages were captured; the second establishes which reviewed facts reached profile-aware knowledge.

The route acceptance audit remains the downstream player-journey check after those source/compiler diagnostics are healthy.
