# Allakhazam-backed knowledge build

EverQuestie's packaged runtime must not scrape or reinterpret source websites. Allakhazam is therefore a **builder-only knowledge provider**: saved mirror pages are parsed into normalized entities, relationships and provenance, then snapshot finalization compiles canonical gameplay projections and removes builder-local paths.

## Audit the completed mirror before rebuilding

EverQuestie consumes an explicitly selected local HTTrack mirror; it does not own or run the crawler. After a manual mirror refresh, audit the completed filesystem before spending time on a full knowledge build:

```powershell
python .\tools\audit_allakhazam_mirror.py "D:\AllakhazamMirror\everquest.allakhazam.com"
```

Add `--json` when another build step needs machine-readable output. The audit is read-only: it performs no network access, creates no database, and does not modify the mirror.

The ordinary audit is deliberately diagnostic, so it can also be run against an active mirror and will report HTTrack `.tmp` files without failing. A canonical full knowledge build is stricter: `tools/build_full_knowledge.ps1` invokes the same audit with `--require-complete` and stops before database construction while any `.tmp` files remain. Those files are HTTrack-owned in-progress state and are expected to become normal completed HTML as the mirror finishes; EverQuestie does not rename, repair or promote them.

The report separates raw HTTrack files/assets from unique canonical structured pages and reports recognized page counts by kind. For spell lifecycle it additionally reports:

- unique numeric Allakhazam spell pages captured;
- spell pages with the reviewed Quick Facts `Expansion` field;
- captured spell pages missing that field.

The lifecycle-ready count uses the same structured Quick Facts parser as the production mirror importer. Comments or other prose containing `Expansion:` are not counted. A low spell count therefore means the mirror capture itself lacks coverage; a high spell-page count with many missing expansions means the captured source pages do not expose the reviewed field. Neither case is permission to infer eras from levels or MCP expansion groupings.

## One build, one acceptance report

`tools/build_knowledge_db.py` can combine the installed EverQuest client, a local Allakhazam mirror and approved map packs in one fresh build. After finalization it automatically evaluates the difficult real-route acceptance suite against the immutable snapshot.

Example on Windows PowerShell:

```powershell
python .\tools\build_knowledge_db.py `
  --working-db .\build\working.sqlite3 `
  --snapshot-db .\dist\everquestie-knowledge.sqlite3 `
  --version 2026.08.15 `
  --eq-install "C:\EverQuest" `
  --allakhazam-mirror "D:\AllakhazamMirror\everquest.allakhazam.com" `
  --allakhazam-version "2026-08-15" `
  --map-pack "Brewall=C:\EQ Maps\Brewall" `
  --map-version "Brewall=2026-08" `
  --route-report .\build\route-acceptance.json `
  --provider-travel-frontier-report .\build\provider-travel-frontier.json
```

Repeat `--map-pack NAME=PATH` for each approved independent map source.

The route report currently includes the representative real canonical endpoint families established for the travel project: The Hole → Labyrinth of Spite, Paineel → The Hole, Stonebrunt Mountains → Paineel, Greater Faydark → The Hole, and Stone Hive → West Freeport.

The default acceptance list deliberately uses literal EQ-client zone display names. Synthetic zones used by long/gated unit tests are never treated as real release endpoints, and the audit does not add aliases or fuzzy matching merely to make a route query resolve.

When `--provider-travel-frontier-report PATH` is supplied, the same build also explains the provider/compiler boundary for the unique resolved endpoints of route failures whose status is actually topology-shaped:

- `disconnected`;
- `directionality_blocked`;
- `route_inconsistency`.

Successful route endpoints are not re-audited, and unresolved/ambiguous identity failures remain identity failures rather than being obscured by unrelated provider diagnostics. The frontier report reuses the finalized provider bindings, stored Connected Zones relationships, production direction semantics, and compiled canonical travel edges. It does not re-import the mirror, mutate reconciliation, or create travel edges.

This makes the normal completion loop one build producing two complementary artifacts:

1. `route-acceptance.json` says which representative player journeys succeed or fail;
2. `provider-travel-frontier.json` says why the resolved endpoints of topology failures did or did not reach the canonical provider travel graph.

## Source boundary

The Allakhazam provider calls the existing `AllakhazamMirrorImporter` over the selected local HTTrack mirror. It records normal `source_pages` provenance and preserves structured relationships such as Connected Zones. It also recognizes numeric Allakhazam spell pages and preserves only their reviewed Quick Facts `Expansion` field as source-granular lifecycle evidence. Spell lifecycle attaches to a canonical client spell only after exact numeric ID and exact normalized-name corroboration, so Allakhazam cannot overwrite or replace MCP/client spell mechanics by coincidence.

An optional `--allakhazam-version` value is attached to imported source pages so a released knowledge artifact can state which mirror capture produced its facts.

Snapshot finalization then performs the existing conservative pipeline:

1. reconcile provider-owned zone identities against canonical EQ-client-backed zones;
2. reconcile exact source-granular spell lifecycle records against canonical client spells;
3. reconcile map/zone identities and map-derived travel;
4. compile structured Allakhazam Connected Zones relationships into the shared canonical travel graph;
5. apply provider-travel v2 direction semantics (`Both`, exact `Entrance To`, exact `Exit From`);
6. compute coverage/connectivity diagnostics;
7. strip builder-local paths and runtime/player state;
8. publish the immutable knowledge snapshot.

The runtime receives only that finalized database. It does not need the mirror and does not parse source HTML.

## Route acceptance and frontier diagnostics are read-only

The post-build acceptance and provider-frontier audits open the finalized snapshot with SQLite `mode=ro&immutable=1`. This is intentionally stronger than ordinary read-only mode: finalization already guarantees the snapshot has no WAL dependency, and the audits should not create sidecars or mutate the artifact they are evaluating.

Route failures are diagnostic states rather than permission to invent travel:

- unresolved or ambiguous canonical endpoint identity;
- disconnected graph components;
- same weak component but blocked directed reachability;
- other explicitly classified topology gaps.

For topology-shaped failures, the provider frontier then distinguishes conditions such as:

- no provider zone/page associated with the canonical zone;
- a provider page exists but exposes no structured Connected Zones rows;
- stored provider rows are blocked by unresolved canonical bindings;
- a row is compiler-eligible but a finalized edge is missing;
- provider rows compiled successfully and the remaining gap lies elsewhere.

The pathfinder still uses only confirmed canonical edges. These reports tell the builder which real-data gap to fix next.

For profile/lifecycle coverage, `tools/audit_profile_lifecycle.py` is the corresponding post-import read-only audit. Compare its accepted spell evidence with the pre-build mirror audit to distinguish capture gaps from reconciliation/profile-classification gaps.

## Gating a release

By default the build prints route acceptance but does not fail solely because the real topology is still incomplete. During active data completion this is useful because the JSON reports become the work queue.

The source-capture boundary is different: `tools/build_full_knowledge.ps1` refuses an Allakhazam mirror that still contains HTTrack `.tmp` files. This gate says only that the selected source capture has finished; it does not claim the completed mirror contains every entity or lifecycle fact.

When the known-data graph is mature enough to make those cases release requirements, add:

```powershell
--require-route-acceptance
```

Any failed acceptance case will then return exit code `2`.

For narrow provider/debug iteration, `--skip-route-audit` disables the post-finalization route audit. It cannot be combined with `--route-report`, `--provider-travel-frontier-report`, or `--require-route-acceptance`.

## What this does not claim

Passing the synthetic and integration tests proves the builder/import/finalization/routing architecture. It does **not** claim that a particular developer mirror already contains every transition or spell lifecycle page required for complete coverage. The read-only mirror inventory audit establishes what was actually captured; the real `route-acceptance.json`, paired `provider-travel-frontier.json`, and profile lifecycle audit produced from that data are the source of truth for the next completion pass.
