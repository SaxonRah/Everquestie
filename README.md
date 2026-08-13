# EverQuestie v0.13

EverQuestie is a local-first, read-only EverQuest companion. It tails `eqlog_*.txt`,
tracks quest/objective progress, compiles local EverQuest knowledge into its own SQLite
database, renders native EQ map files, and can optionally perform **explicit** online
searches through the `everquest1-mcp` project.

Normal gameplay is offline. EverQuestie never reads process memory, injects into EQ,
reads packets, sends keystrokes, or automates gameplay.


## v0.13: deep local knowledge + FTS + Questie/navigation improvements

v0.13 deliberately does **not** inspect the configured Allakhazam DB or Wiki mirror
directories automatically. Those mirrors can remain under HTTrack for days without
EverQuestie touching their in-progress captures. Mirror imports remain manual actions.

The local-client compiler now goes beyond ID/name inventory. **Compile full local DB via
MCP (offline)** uses a small JSONL bridge to the built `everquest1-mcp` `localdata` module
and stores rich per-record details in EverQuestie's own SQLite database for spells, zones,
factions, achievements, AAs, Overseer agents/quests, mercenaries, tributes and lore. The
complete source object is preserved in `entity_details`; compact useful scalar fields are
also merged into the normalized entity record. An unchanged detail fingerprint skips the
rich pass on later compiles.

EverQuestie also directly compiles compact authoritative client tables when present:

- `Resources/skillcaps.txt`
- `Resources/basedata.txt`
- `Resources/ACMitigation.txt`
- `Resources/SpellStackingGroups.txt`
- selected named/description records from `dbstr_us.txt` (creature types, alternate
  currencies, expansions and game events)

### Local full-text search

The DB now owns an SQLite FTS5 index over entity names, aliases, notes, rich local detail,
JSON data and quest-step text. **Search local DB** uses FTS when the Python SQLite build
provides it and falls back to the previous local LIKE search otherwise. Full local compiles
rebuild the index automatically; the new Database tab can rebuild it manually.

### Knowledge and quest UI

Knowledge detail pages render rich installed-client records. Spells receive a structured
mechanics view (mana/endurance, cast/recast/recovery, targeting, class levels, effects,
description and available stacking/message data); other rich local records retain their
full text/JSON representation with provenance.

Tracked quests are now a collapsible objective tree rather than a flat quest list. Objective
rows show completion/count progress, and selecting a resolvable NPC/item objective asks the
map to focus the known entity location when one exists.

### Map quality-of-life

The map can show a trail made only from actual logged `/loc` samples, clear that trail, and
optionally follow the newest logged position. Manual map pan/zoom is remembered per zone in
EverQuestie's own metadata and restored when that zone is opened again.

### Database maintenance

A new **Database** tab reports SQLite integrity, database size, core/source/support-table
counts, FTS availability/index size, and the current source policy. It also provides:

- **Rebuild local search index**
- **Refresh diagnostics**
- **Backup database…** using SQLite's backup API

The source/provenance rules are documented in `docs/SOURCE_POLICY.md`.

### Optional Windows packaging

`tools\build_windows_exe.cmd` creates a PyInstaller Windows build when PyInstaller is
already installed. It intentionally does not install packages by itself. The MCP repository
is not bundled into the executable; it remains an optional separately configured source
compiler/search component.

## v0.12: collapsible Knowledge + Classic EQ Stone

The Knowledge tab is now organized as a lazy hierarchical tree instead of a flat list.
Each populated knowledge kind is a native expandable `[+]` topic, for example:

```text
[+] Quests (8,214)
[+] NPCs / Bestiary (44,472)
[+] Items (...)
[+] Zones (...)
[+] Factions (...)
[+] Spells (...)
[+] Alternate Advancement (AA) (...)
[+] Achievements (...)
...
```

Expanding a topic loads its children on demand. Very large topics load up to 1,000
rows for browsing and display how many remain; use the Knowledge Search box to narrow
them. Searches stay grouped by topic rather than returning `[kind] name` rows in one
undifferentiated list.

EverQuestie also has a persistent UI theme setting under **Sources → Persistent
settings**. **Classic EQ Stone** is the default for new settings files and uses an
original EverQuestie blue/gray marble texture plus beveled stone panels, parchment-like
inputs, cream/gold text, and dark content panes. **System** restores the platform ttk
theme. Theme changes apply live and are saved to:

```ini
[ui]
theme = classic_eq_stone
```

The bundled stone texture is original EverQuestie artwork inspired by the visual
character of the classic EverQuest interface; no EQInterface/game UI assets are copied
into the project.

## v0.11: local EverQuest knowledge compiler

EverQuestie owns the knowledge database. The installed EverQuest client,
`everquest1-mcp`, Allakhazam mirrors, and map packs are source/evidence layers rather
than runtime databases.

```text
EverQuest installation
        |
        | local files only
        v
everquest1-mcp local-data parser
        |
        | save_data_snapshot inventory
        v
EverQuestie normalizer ----------------+
                                        |
Allakhazam DB HTTrack mirror -----------+--> ~/.eqquest/eqquest.sqlite3
Allakhazam Wiki HTTrack mirror ---------+          |
Good / Brewall map files ---------------+          +--> quests / maps / Find / Where
                                                   |
eqlog_*.txt -------------------------------------> quest state / observations

OPTIONAL, EXPLICIT ONLY
Search tab -> choose online source -> press Search online
```

### Compile installed EQ data

First configure/build `everquest1-mcp`, select the EverQuest installation in
**Sources → EverQuest client data**, then press:

```text
Compile full local DB via MCP (offline)
```

v0.11 asks the local MCP process to create its local-data snapshot and compiles the
snapshot's ID/name inventories into EverQuestie's own schema with provenance. The
currently normalized identity classes are:

- spells
- zones
- factions
- achievements
- alternate advancement abilities
- Overseer agents/minions
- Overseer quests
- mercenaries
- tributes
- lore entries
- combat abilities

Systems that the upstream snapshot reports only as aggregate counts are retained in
source metadata rather than being turned into invented entities.

v0.11 established the first compiler layer: stable local IDs, names, source metadata and
cross-source identities. v0.13 layers rich per-record details plus local support tables onto
those identities while preserving the original inventory/provenance model.

The existing **Import basic client files** action still directly imports
`Resources/ZoneNames.txt` and `Help/*.html` for the details that importer already
understands. A full MCP compile runs that basic import first and then merges the broader
MCP inventory.

The compiler runs in a worker thread with a separate SQLite connection so the UI stays
responsive. It refuses to start while live log monitoring is active, avoiding a long
bulk write competing with observation writes.

`everquest1-mcp` normally writes `.eq-mcp-snapshot.json` in the selected EQ directory.
EverQuestie uses that generated snapshot only long enough to ingest it. If a snapshot
already existed, EverQuestie restores its original bytes and timestamps; if none
existed, the temporary snapshot is removed afterward.

A stable content fingerprint ignores the snapshot's creation timestamp. Recompiling an
unchanged client therefore updates source metadata without rewriting tens of thousands
of identical entity rows.

After compilation, EverQuestie's normal gameplay/search/map runtime uses its own SQLite
DB. Node and the MCP process are not required merely to monitor EQ or query the compiled
local knowledge.

## Scrollable UI

v0.11 adds visible scrolling to the UI surfaces that can grow beyond the current window:

- the entire **Sources** page is vertically scrollable;
- Sources knowledge-summary text has its own scrollbar;
- Live event history, tracked quests, and Guidance have scrollbars;
- Knowledge result list and entity detail have scrollbars;
- Search result text has a scrollbar;
- Map imported-location results have a scrollbar.

The map canvas itself keeps its existing pan/zoom controls rather than adding redundant
canvas scrollbars.

## Persistent settings

EverQuestie stores user-selected filesystem locations in:

```text
%USERPROFILE%\.eqquest\settings.ini
```

The INI is saved automatically and remembers the selected EQ log, EverQuest
installation, MCP repository, Allakhazam DB and Wiki mirrors, map-pack root, and recent
manual import folders. **Sources → Persistent settings** shows the exact file and can
open or save it directly.

The application database remains:

```text
%USERPROFILE%\.eqquest\eqquest.sqlite3
```

Keeping settings and accumulated knowledge separate makes both files easy to inspect or
back up.

## Local Allakhazam mirrors

### DB mirror

Point the DB mirror field at the local HTTrack tree. The structured importer recursively
recognizes quest, NPC, item, and zone pages, keeps canonical URLs, raw source text/HTML,
aliases, relationships, locations, and quest objectives.

Mirror refresh is local and incremental: finalized HTML is SHA-256 checked, unchanged
recognized pages are skipped, and HTTrack `*.tmp` files are ignored.

### Wiki mirror

Point the Wiki mirror field at the local Wiki HTTrack tree. EverQuestie indexes canonical
Wiki articles as local `wiki` entities with provenance and source snapshots. Unchanged
pages are skipped on later scans.

## `everquest1-mcp` repository setup

Upstream project:

```text
https://github.com/ArtSabintsev/everquest1-mcp.git
```

For a Git checkout, initialize the submodule with:

```powershell
git submodule update --init --recursive
```

Then build it:

```powershell
cd third_party\everquest1-mcp
npm install
npm run build
```

The helper script can do this for you:

```powershell
.\tools\setup_mcp_submodule.cmd
```

## Running EverQuestie

```powershell
py EverQuestie.py
```

or:

```powershell
py -m eqquest
```

The core runtime remains Python standard library + Tkinter + SQLite. Node/npm are needed
only for the optional MCP-backed local compiler/search and explicit online searches.

## Testing

```powershell
py -m unittest discover -s tests -v
```

v0.13 was validated with the unit suite plus compile/import, Node-bridge syntax, headless
Tk/theme, and large-FTS smoke tests.
