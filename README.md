# EverQuestie v0.13

EverQuestie is a local-first, log-driven EverQuest companion. It reads normal
`eqlog_*.txt` output, combines it with a precompiled local knowledge database, and helps
with quest progress, maps, locations, travel, mechanics, and navigation.

The normal packaged application is designed to work offline. It does **not** read
EverQuest process memory, inject into the game, inspect packets, send keystrokes, or
automate gameplay.

## What EverQuestie does

### Live log companion

EverQuestie tails the selected EverQuest log and maintains session state from observed
log lines. The Live tab shows current zone/location information, recent parsed events,
tracked quests/objectives, and guidance derived from the local knowledge database.

Tracked objectives can hand navigation to the correct owner:

- a confirmed location in the current zone can be focused on the Map tab;
- an objective in another canonical zone can be handed to Travel for route guidance;
- unresolved or ambiguous evidence is reported instead of guessed.

### Native EQ maps

The Map tab renders normal EverQuest `.txt` map files and supports local map search,
player position, logged `/loc` trails, pan/zoom state, and navigation targets.

The global Good/Brewall map catalog is compiled into the shipped knowledge database.
Normal users do **not** rebuild that catalog. A player's selected Good, Brewall, or EQ
map directory is only the local rendering source for the actual map geometry.

When multiple legitimate local map variants exist for one canonical zone, EverQuestie
requires an explicit user choice and stores that binding in writable user state. It does
not break canonical zone ambiguity by filename guessing.

### Travel and zone navigation

Packaged EverQuestie has a dedicated Travel tab. Routes are computed from finalized
canonical zone identities and confirmed directed travel evidence.

Travel deliberately does not invent reciprocal edges. A route can run in reverse only
when the underlying evidence is explicitly bidirectional or a separate reverse edge is
present.

Travel can also:

- use the live current zone as the route start;
- cache a confirmed route and follow the player's live zone along it;
- map a source-owned coordinate for the next hop when one is known;
- show canonical zone context and route actionability;
- open the current-zone **What's here** dashboard and hand exact selected entities to
  Knowledge.

### Local Knowledge

Knowledge is backed by the shipped SQLite database and its finalized FTS5 index. It
covers the normalized entity kinds currently populated by the builders, including
quests, NPCs, items, zones, factions, spells, achievements, alternate advancement,
Overseer data, mercenaries, tributes, lore, combat abilities, client help topics, and
other client-derived identities.

Knowledge navigation preserves exact entity IDs when duplicate names exist. Related
entities, locations, quest steps, source evidence, and provider relationships remain
source-aware rather than being flattened into one unqualified answer.

In packaged runtime, Knowledge also exposes safe navigation actions:

- **Map location** for confirmed locations in the live current zone;
- **Route to location** for confirmed locations in another canonical zone.

### Rich EverQuest client mechanics

The full builder imports both the broad `everquest1-mcp` identity inventory and the
structured records exposed by its local-data parsers.

Rich records currently cover:

- spells;
- zones;
- factions;
- achievements;
- alternate advancement abilities;
- Overseer agents/minions;
- Overseer quests;
- mercenaries;
- tributes;
- lore;
- combat abilities / disciplines.

The complete source-granular MCP records are retained in `mcp_detail_records`. The
canonical one-row-per-entity UI/search projection lives in `entity_details`, so multiple
source IDs can safely map to one canonical entity without losing the original records.

Spell and combat-ability detail views expose useful local mechanics such as mana or
endurance cost, cast/recast/recovery timing, targeting, resist data, class/level data,
effects, descriptions, and available stacking information.

EverQuestie also compiles direct client support tables such as skill caps, base stats,
AC mitigation, and spell stacking data. The packaged Mechanics tab projects that data
through canonical class/skill/spell identities instead of requiring users to understand
raw client table IDs.

## Packaged runtime architecture

Normal users do not need `everquest1-mcp`, Node.js, HTTrack mirrors, a source checkout,
map-catalog compilation, or an FTS rebuild.

EverQuestie separates immutable global knowledge from writable player state:

```text
builder inputs
  EverQuest client
  Allakhazam mirror
  everquest1-mcp
  Good + Brewall map catalogs
  approved travel supplements
          |
          v
build/working.sqlite3
          |
          | finalize / audit
          v
everquestie-knowledge.sqlite3     read-only / immutable at runtime
          |
          +-------------------------+
                                    |
eqlog + quest progress + bindings  |
          |                         |
          v                         v
everquestie-user.sqlite3       packaged EverQuestie
```

The packaged runtime opens `everquestie-knowledge.sqlite3` with SQLite read-only,
immutable semantics and writes player/session state to:

```text
%USERPROFILE%\.eqquest\everquestie-user.sqlite3
```

Filesystem selections and UI preferences remain in the human-readable settings file:

```text
%USERPROFILE%\.eqquest\settings.ini
```

If an older combined `%USERPROFILE%\.eqquest\eqquest.sqlite3` exists, packaged runtime
can migrate its tracked quests, quest progress, observed events, and user metadata into
the split user-state database without changing the shipped knowledge snapshot.

Builder/source-checkout mode may still use the old writable combined database as a
workspace. That file is not the release artifact.

## Source and identity policy

EverQuestie owns its normalized schema. External datasets are evidence providers, not
runtime databases.

The current full build can combine:

- **Installed EverQuest client files** for client identities, mechanics, help data and
  other locally shipped data;
- **everquest1-mcp** for broad local inventory plus structured rich records;
- **a local Allakhazam HTTrack mirror** for recognized structured community/world
  evidence and relationships;
- **Good's and Brewall's map packs** for map identity, labels, POIs and travel evidence;
- **repository-approved travel supplements** for reviewed source-backed edges that are
  not safely recoverable from the automated providers.

Stable namespaced IDs and source provenance are retained throughout the build. Provider
zone identities are reconciled conservatively into canonical gameplay zones; ambiguous
or unsupported identities remain visible as evidence but are not promoted merely to
increase route or location coverage.

The packaged runtime does not perform hidden source refreshes or background website
requests. Source-checkout/developer mode retains explicit Search and Sources surfaces,
including optional online MCP-backed search, but those builder/developer tabs are hidden
from normal packaged users.

See [docs/SOURCE_POLICY.md](docs/SOURCE_POLICY.md) for the field-level source policy.

## Running a source checkout

EverQuestie requires Python 3.11 or newer. The core application uses Python's standard
library, Tkinter, and SQLite.

```powershell
git clone https://github.com/SaxonRah/Everquestie.git
cd Everquestie
py EverQuestie.py
```

You can also launch the package entry point:

```powershell
py -m eqquest
```

A source checkout with no finalized knowledge snapshot falls back to the writable
builder database under `%USERPROFILE%\.eqquest\eqquest.sqlite3` and retains the
builder/developer UI.

To exercise the packaged split-database behavior from a source checkout, point runtime
at a finalized snapshot explicitly:

```powershell
$env:EVERQUESTIE_KNOWLEDGE_DB = (Resolve-Path .\dist\everquestie-knowledge.sqlite3).Path
py .\EverQuestie.py
Remove-Item Env:EVERQUESTIE_KNOWLEDGE_DB
```

`EVERQUESTIE_USER_DB` can optionally override the writable user-state path for isolated
runtime testing.

## Building the full knowledge database

This section is for builders/developers, not normal users.

Initialize and build the MCP submodule first:

```powershell
git submodule update --init --recursive
cd .\third_party\everquest1-mcp
npm install
npm run build
cd ..\..
```

`tools\build_full_knowledge.ps1` is the current full local build driver. Its source-path
variables are intentionally explicit, so set the EverQuest installation, Allakhazam
mirror, MCP checkout, Good's map folder, and Brewall map folder near the top of the
script for the builder machine.

Then run:

```powershell
.\tools\build_full_knowledge.ps1
```

The full build:

1. compiles the installed EQ client data;
2. imports the local Allakhazam mirror;
3. imports MCP inventory and rich structured details;
4. indexes Good's and Brewall's map catalogs;
5. compiles approved travel supplements;
6. finalizes `dist\everquestie-knowledge.sqlite3`;
7. audits MCP inventory and rich-detail persistence in both working and finalized DBs;
8. runs canonical route acceptance and provider-frontier auditing;
9. runs the complete regression suite;
10. prints artifact sizes, source versions, reports, and the final snapshot SHA-256.

A requested rich MCP build is intentionally strict: missing required detail systems,
zero-record populated systems, incomplete source-record accounting, failed route
acceptance, or failed tests stop the build instead of silently producing a "full" but
incomplete artifact.

## Building a Windows release

`tools\build_release.ps1` is the release/distribution boundary for an existing builder
database. PyInstaller must already be installed for the selected Python interpreter.

Example:

```powershell
.\tools\build_release.ps1 -Version 0.13.0
```

The default release is a one-folder Windows build with
`everquestie-knowledge.sqlite3` beside `EverQuestie.exe`. The script stages the builder
DB through SQLite backup, compiles the approved travel manifests into the staged copy,
finalizes and audits the knowledge snapshot, runs route acceptance and tests, builds the
Windows application, writes a release manifest with hashes, and creates a versioned ZIP.

An optional one-file build embeds the immutable snapshot:

```powershell
.\tools\build_release.ps1 -Version 0.13.0 -OneFile
```

The release never packages the mutable builder DB or a player's user-state DB.

## Tests

Run the regression suite with:

```powershell
py -m unittest discover -s tests -v
```

The repository's runtime smoke workflow also compiles the Python source, imports the
application headlessly, and runs the regression suite for code/tool pull requests.

## Design rules worth knowing

- Normal gameplay is local-first and does not require builder infrastructure.
- The shipped knowledge database is immutable; player state is separate and writable.
- Knowledge identity prefers exact/namespaced evidence over fuzzy guesses.
- Ambiguous identities remain ambiguous.
- Travel is directional unless bidirectionality is explicitly supported.
- Coordinates are only used for navigation when their source-zone ownership is safe.
- Map catalog construction, provider reconciliation, FTS rebuilding, and MCP compilation
  are builder responsibilities, not player startup work.
- Provenance is retained so facts can be audited, refreshed, and reconciled without
  pretending that every source agrees.

## More architecture documentation

- [Database distribution](docs/DATABASE_DISTRIBUTION.md)
- [Source policy](docs/SOURCE_POLICY.md)
- [Allakhazam knowledge build](docs/ALLAKHAZAM_KNOWLEDGE_BUILD.md)
- [Provider zone reconciliation](docs/PROVIDER_ZONE_RECONCILIATION.md)
- [Provider zone travel](docs/PROVIDER_ZONE_TRAVEL.md)
- [Current-zone dashboard](docs/CURRENT_ZONE_DASHBOARD.md)
- [Knowledge relationship navigation](docs/KNOWLEDGE_RELATIONSHIP_NAVIGATION.md)
- [Release portability](docs/RELEASE_PORTABILITY.md)
