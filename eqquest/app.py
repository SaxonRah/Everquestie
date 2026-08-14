from __future__ import annotations

import os
import queue
import json
import sqlite3
import tkinter as tk
import webbrowser
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .allakhazam import AllakhazamImporter, open_allakhazam_search, open_url
from .commands import parse_control_command
from .db import Database
from .parser import EQLogParser
from .quest_engine import QuestEngine
from .knowledge import entity_detail_text, find_text, where_text
from .local_search import count_local_entities_by_kind, query_summary, search_local_entities, search_local_hits
from .db_audit import identity_audit_text
from .mapview import MapViewerFrame
from .mcp_client import (
    ONLINE_TOOLS,
    MCP_LOCAL_SEARCH_TOOL,
    MCPStdioClient,
    default_mcp_path,
    mcp_status,
)
from .sources import EQClientImporter, MCPLocalSnapshotCompiler
from .sources.allakhazam_wiki import AllakhazamWikiImporter
from .settings import SettingsFile
from .theme import DEFAULT_THEME, THEME_LABELS, ThemeManager
from .state import SessionState
from .tailer import LogTailer
from .widgets import VerticalScrolledFrame


APP_TITLE = "EverQuestie — local-first EverQuest companion"

VISIBLE_EVENT_KINDS = {
    "zone", "target_npc", "consider", "npc_say", "loot", "kill", "death",
    "level_gain", "level_loss", "faction_up", "faction_down",
    "task_assigned", "task_update", "merchant_sale",
}

KNOWLEDGE_KIND_LABELS = {
    "quest": "Quests",
    "npc": "NPCs / Bestiary",
    "item": "Items",
    "zone": "Zones",
    "faction": "Factions",
    "spell": "Spells",
    "recipe": "Recipes",
    "achievement": "Achievements",
    "aa": "Alternate Advancement (AA)",
    "overseer_agent": "Overseer Agents",
    "overseer_quest": "Overseer Quests",
    "mercenary": "Mercenaries",
    "tribute": "Tributes",
    "lore": "Lore",
    "combat_ability": "Combat Abilities",
    "creature_type": "Creature / Race Types",
    "alt_currency": "Alternate Currencies",
    "expansion": "Expansions",
    "game_event": "Game Events",
    "wiki": "Wiki",
    "help": "Official Help",
}
KNOWLEDGE_CHILD_LIMIT = 1000


class EverQuestieApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1220x760")
        self.minsize(940, 620)

        data_dir = Path.home() / ".eqquest"
        data_dir.mkdir(parents=True, exist_ok=True)

        self.db = Database(data_dir / "eqquest.sqlite3")

        # User-selected filesystem locations live in a human-readable INI rather
        # than being scattered across widgets/SQLite metadata.  On first v0.10
        # launch, migrate any paths older releases already stored in SQLite.
        self.settings = SettingsFile(data_dir / "settings.ini")
        migrated = self.settings.migrate_missing_paths({
            "everquest_install": self.db.get_meta("eq_game_path", ""),
            "allakhazam_db_mirror": self.db.get_meta("allakhazam_db_mirror", ""),
            "allakhazam_wiki_mirror": self.db.get_meta("allakhazam_wiki_mirror", ""),
            "map_root": self.db.get_meta("map_root", ""),
            "mcp_repository": str(default_mcp_path()),
        })
        if migrated or not self.settings.path.exists():
            self.settings.save()

        # MapViewerFrame still mirrors map_root into DB metadata for backwards
        # compatibility.  Make the INI authoritative when both exist.
        saved_map_root = self.settings.get_path("map_root")
        if saved_map_root:
            self.db.set_meta("map_root", saved_map_root)

        self.parser = EQLogParser()
        self.state_model = SessionState()
        self.quest_engine = QuestEngine(self.db)
        self.importer = AllakhazamImporter(self.db)
        self.eq_client_importer = EQClientImporter(self.db)
        self.mcp_local_compiler = MCPLocalSnapshotCompiler(self.db)
        self.wiki_importer = AllakhazamWikiImporter(self.db)
        # Upgrade previously imported raw Allakhazam pages into the new graph
        # automatically; no re-save/re-import is required after updating EverQuestie.
        try:
            self.importer.rebuild_imported_pages()
        except Exception:
            # A malformed archived page must not prevent the companion from starting.
            pass

        self.tailer: LogTailer | None = None
        self.event_queue: queue.Queue[str] = queue.Queue()

        self.log_path = tk.StringVar(value=self.settings.get_path("log_file"))
        self.status = tk.StringVar(value="Not monitoring")
        self.zone_var = tk.StringVar(value="Zone: unknown")
        self.loc_var = tk.StringVar(value="Location: unknown")
        self.search_var = tk.StringVar()
        self.kind_var = tk.StringVar(value="all")
        self.import_url_var = tk.StringVar()
        self.import_type_var = tk.StringVar(value="auto")
        self.import_name_var = tk.StringVar()
        self.eq_game_path_var = tk.StringVar(value=self.settings.get_path("everquest_install"))
        self.mcp_path_var = tk.StringVar(value=self.settings.get_path("mcp_repository", str(default_mcp_path())))
        self.mcp_status_var = tk.StringVar(value="MCP repository status: checking…")
        self.db_mirror_var = tk.StringVar(value=self.settings.get_path("allakhazam_db_mirror"))
        self.wiki_mirror_var = tk.StringVar(value=self.settings.get_path("allakhazam_wiki_mirror"))
        self.settings_path_var = tk.StringVar(value=str(self.settings.path))
        saved_theme = self.settings.get("ui", "theme", DEFAULT_THEME) or DEFAULT_THEME
        self.ui_theme_var = tk.StringVar(value=ThemeManager.label_for(saved_theme))
        self.theme_manager = ThemeManager(self)
        self.online_query_var = tk.StringVar()
        self.online_source_var = tk.StringVar(value="All online sources")
        self.online_status_var = tk.StringVar(value="Online access is idle. No network request has been made.")
        self.client_compile_status_var = tk.StringVar(
            value=self._initial_client_compile_status()
        )

        # If a previous run already observed the quest assignment/progress, rebuild
        # tracked quests immediately after an Allakhazam graph upgrade. If the
        # stored history lacks a reliable boundary, reconciliation preserves the
        # existing progress instead of guessing.
        for tracked in self.db.tracked_quests():
            self.quest_engine.reconcile_quest_from_history(int(tracked["id"]))

        self._knowledge_entity_by_item: dict[str, int] = {}
        self._knowledge_kind_nodes: dict[str, str] = {}
        self._knowledge_loaded_nodes: set[str] = set()
        self._knowledge_counts: dict[str, int] = {}
        self._tracked_quest_by_item: dict[str, int] = {}
        self._tracked_step_by_item: dict[str, tuple[int, int]] = {}

        self._settings_save_job: str | None = None
        self._build_ui()
        self.theme_manager.apply(ThemeManager.id_for_label(self.ui_theme_var.get()))
        self._bind_settings_autosave()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_lines)
        self.after(400, self._refresh_guidance)

    def _initial_client_compile_status(self) -> str:
        timestamp = self.db.get_meta("eq_mcp_last_compile", "")
        version = self.db.get_meta("eq_mcp_version", "")
        if not timestamp:
            return "Full MCP client-data compile has not been run yet."
        suffix = f" | everquest1-mcp {version}" if version else ""
        return f"Last full MCP compile: {timestamp}{suffix}"

    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="EQ log:").pack(side="left")
        ttk.Entry(top, textvariable=self.log_path).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(top, text="Browse…", command=self._browse_log).pack(side="left")
        ttk.Button(top, text="Start monitoring", command=self._start).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(top, text="Stop", command=self._stop).pack(side="left", padx=(6, 0))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.notebook = notebook

        self.live_tab = ttk.Frame(notebook, padding=8, style="Stone.TFrame")
        self.map_tab = ttk.Frame(notebook)
        self.knowledge_tab = ttk.Frame(notebook, padding=8, style="Stone.TFrame")
        self.search_tab = ttk.Frame(notebook, padding=8, style="Stone.TFrame")
        self.database_tab = ttk.Frame(notebook, padding=8, style="Stone.TFrame")
        self.import_tab = VerticalScrolledFrame(
            notebook, padding=8, style="Stone.TFrame", content_style="Stone.TFrame"
        )

        notebook.add(self.live_tab, text="Live")
        notebook.add(self.map_tab, text="Map")
        notebook.add(self.knowledge_tab, text="Knowledge")
        notebook.add(self.search_tab, text="Search")
        notebook.add(self.database_tab, text="Database")
        notebook.add(self.import_tab, text="Sources")

        self._build_live()
        self._build_map()
        self._build_knowledge()
        self._build_search()
        self._build_database()
        self._build_import()
        self._refresh_mcp_status()
        self._refresh_source_summary()

        status = ttk.Frame(self, padding=(8, 2, 8, 8))
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.status).pack(side="left")
        ttk.Label(status, text="   ").pack(side="left")
        ttk.Label(status, textvariable=self.zone_var).pack(side="left")
        ttk.Label(status, text="   ").pack(side="left")
        ttk.Label(status, textvariable=self.loc_var).pack(side="left")

    def _build_live(self):
        self.live_tab.columnconfigure(0, weight=2)
        self.live_tab.columnconfigure(1, weight=1)
        self.live_tab.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(self.live_tab, text="Observed EQ events", padding=6)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.event_text = tk.Text(left, wrap="word", state="disabled")
        self.event_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(left, command=self.event_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.event_text.configure(yscrollcommand=scroll.set)

        right = ttk.Frame(self.live_tab)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(4, weight=1)

        ttk.Label(right, text="Tracked quests / objectives").grid(row=0, column=0, sticky="w")
        self.tracked_tree = ttk.Treeview(right, show="tree", selectmode="browse", height=10)
        self.tracked_tree.grid(row=1, column=0, sticky="nsew")
        self.tracked_tree.column("#0", minwidth=220, width=390, stretch=True)
        tracked_scroll = ttk.Scrollbar(right, orient="vertical", command=self.tracked_tree.yview)
        tracked_scroll.grid(row=1, column=1, sticky="ns")
        tracked_hscroll = ttk.Scrollbar(right, orient="horizontal", command=self.tracked_tree.xview)
        tracked_hscroll.grid(row=2, column=0, sticky="ew")
        self.tracked_tree.configure(yscrollcommand=tracked_scroll.set, xscrollcommand=tracked_hscroll.set)
        self.tracked_tree.bind("<<TreeviewSelect>>", self._tracked_tree_selected)

        ttk.Label(right, text="Guidance").grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.guide_text = tk.Text(right, wrap="word", state="disabled", height=12)
        self.guide_text.grid(row=4, column=0, sticky="nsew")
        guide_scroll = ttk.Scrollbar(right, orient="vertical", command=self.guide_text.yview)
        guide_scroll.grid(row=4, column=1, sticky="ns")
        self.guide_text.configure(yscrollcommand=guide_scroll.set)

        row = ttk.Frame(right)
        row.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(row, text="Open source", command=self._open_tracked_source).pack(
            side="left"
        )
        ttk.Button(row, text="Refresh", command=self._refresh_guidance).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(row, text="Reconcile from log", command=self._reconcile_selected_tracked).pack(
            side="left", padx=(6, 0)
        )

    def _build_map(self):
        self.map_tab.rowconfigure(0, weight=1)
        self.map_tab.columnconfigure(0, weight=1)
        self.map_view = MapViewerFrame(
            self.map_tab,
            db=self.db,
            get_zone=lambda: self.state_model.current_zone,
            get_location=lambda: self.state_model.last_location,
            set_zone=lambda zone: self._set_current_zone(zone, source="manual", announce=True),
            on_entity=self._map_entity_selected,
        )
        self.map_view.grid(row=0, column=0, sticky="nsew")

    def _map_entity_selected(self, entity_id: int):
        row = self.db.entity(entity_id)
        if row is None:
            return
        self.search_var.set(row["name"])
        self.kind_var.set(row["kind"])
        self._search_knowledge()
        iid = f"entity:{entity_id}"
        if not hasattr(self, "entity_tree") or not self.entity_tree.exists(iid):
            return
        self.entity_tree.selection_set(iid)
        self.entity_tree.focus(iid)
        self.entity_tree.see(iid)
        self._show_entity()

    def _build_knowledge(self):
        controls = ttk.Frame(self.knowledge_tab)
        controls.pack(fill="x")
        ttk.Label(controls, text="Search:").pack(side="left")
        ent = ttk.Entry(controls, textvariable=self.search_var)
        ent.pack(side="left", fill="x", expand=True, padx=6)
        ent.bind("<Return>", lambda _e: self._search_knowledge())

        kinds = ttk.Combobox(
            controls,
            textvariable=self.kind_var,
            values=["all", *KNOWLEDGE_KIND_LABELS.keys()],
            state="readonly",
            width=18,
        )
        kinds.pack(side="left")
        ttk.Button(
            controls, text="Search local", command=self._search_knowledge
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            controls,
            text="Open Search tab",
            command=lambda: self.notebook.select(self.search_tab),
        ).pack(side="left", padx=(6, 0))

        ttk.Label(
            self.knowledge_tab,
            text=(
                "Knowledge is grouped by topic. Expand a [+] topic to browse it; "
                "large topics are loaded lazily. Search supports type:, zone:, source:, exact: and quoted names."
            ),
            justify="left",
        ).pack(fill="x", pady=(6, 0))

        body = ttk.Panedwindow(self.knowledge_tab, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(8, 0))

        lf = ttk.Frame(body)
        rf = ttk.Frame(body)
        body.add(lf, weight=1)
        body.add(rf, weight=2)

        lf.rowconfigure(0, weight=1)
        lf.columnconfigure(0, weight=1)
        self.entity_tree = ttk.Treeview(lf, show="tree", selectmode="browse")
        self.entity_tree.grid(row=0, column=0, sticky="nsew")
        self.entity_tree.column("#0", width=340, minwidth=180, stretch=True)
        entity_vscroll = ttk.Scrollbar(lf, orient="vertical", command=self.entity_tree.yview)
        entity_vscroll.grid(row=0, column=1, sticky="ns")
        entity_hscroll = ttk.Scrollbar(lf, orient="horizontal", command=self.entity_tree.xview)
        entity_hscroll.grid(row=1, column=0, sticky="ew")
        self.entity_tree.configure(
            yscrollcommand=entity_vscroll.set,
            xscrollcommand=entity_hscroll.set,
        )
        self.entity_tree.bind("<<TreeviewOpen>>", self._knowledge_tree_open)
        self.entity_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_entity())

        action = ttk.Frame(lf)
        action.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(action, text="Track quest", command=self._track_selected).pack(
            side="left"
        )
        ttk.Button(action, text="Untrack", command=self._untrack_selected).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(action, text="Open source", command=self._open_entity_source).pack(
            side="left", padx=(6, 0)
        )

        rf.rowconfigure(0, weight=1)
        rf.columnconfigure(0, weight=1)
        self.entity_text = tk.Text(rf, wrap="word", state="disabled")
        self.entity_text.grid(row=0, column=0, sticky="nsew")
        entity_text_scroll = ttk.Scrollbar(rf, orient="vertical", command=self.entity_text.yview)
        entity_text_scroll.grid(row=0, column=1, sticky="ns")
        self.entity_text.configure(yscrollcommand=entity_text_scroll.set)

        self._search_knowledge()

    @staticmethod
    def _knowledge_kind_label(kind: str) -> str:
        return KNOWLEDGE_KIND_LABELS.get(kind, kind.replace("_", " ").title())

    def _knowledge_tree_open(self, _event=None) -> None:
        node = self.entity_tree.focus()
        if not node.startswith("kind:") or node in self._knowledge_loaded_nodes:
            return
        kind = node.split(":", 1)[1]
        self._populate_knowledge_kind(kind, node)

    def _populate_knowledge_kind(self, kind: str, node: str) -> None:
        if node in self._knowledge_loaded_nodes:
            return
        for child in self.entity_tree.get_children(node):
            self.entity_tree.delete(child)

        term = getattr(self, "_knowledge_search_term", "")
        rows = search_local_entities(
            self.db,
            term,
            default_kind=kind,
            current_zone=self.state_model.current_zone,
            limit=KNOWLEDGE_CHILD_LIMIT,
        )
        for row in rows:
            entity_id = int(row["id"])
            iid = f"entity:{entity_id}"
            # A rebuild clears the tree, so entity IDs are safe stable iids here.
            self.entity_tree.insert(node, "end", iid=iid, text=row["name"])
            self._knowledge_entity_by_item[iid] = entity_id

        count = self._knowledge_counts.get(kind, len(rows))
        if count > len(rows):
            remaining = count - len(rows)
            self.entity_tree.insert(
                node,
                "end",
                iid=f"more:{kind}",
                text=f"… {remaining:,} more — use Search to narrow this topic",
            )
        self._knowledge_loaded_nodes.add(node)

    def _build_search(self):
        """Explicit search surface. Nothing here performs background network I/O."""
        controls = ttk.LabelFrame(self.search_tab, text="Explicit search", padding=10)
        controls.pack(fill="x")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Query").grid(row=0, column=0, sticky="w")
        query_entry = ttk.Entry(controls, textvariable=self.online_query_var)
        query_entry.grid(row=0, column=1, sticky="ew", padx=8)
        query_entry.bind("<Return>", lambda _e: self._search_local_from_search_tab())

        ttk.Label(controls, text="Online source").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(
            controls,
            textvariable=self.online_source_var,
            values=list(ONLINE_TOOLS.keys()),
            state="readonly",
            width=30,
        ).grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))

        buttons = ttk.Frame(controls)
        buttons.grid(row=2, column=1, sticky="w", padx=8, pady=(10, 0))
        ttk.Button(buttons, text="Search local DB", command=self._search_local_from_search_tab).pack(side="left")
        ttk.Button(
            buttons,
            text="Search EQ client via MCP (offline)",
            command=self._search_mcp_local,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Search online (explicit)", command=self._search_online_explicit).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Allakhazam browser search", command=self._search_allakhazam_from_search_tab).pack(side="left", padx=(6, 0))

        ttk.Label(
            controls,
            textvariable=self.online_status_var,
            wraplength=900,
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        info = (
            "Local DB is the default. 'Search EQ client via MCP (offline)' queries the installed game files "
            "through the local MCP repository without contacting community sites. EverQuestie never invokes an online source "
            "in the background; MCP-backed online sources are contacted only when you press 'Search online (explicit)'. "
            "Local DB search uses EverQuestie's FTS5 index when available. Online results are temporary and are not silently merged into the local knowledge DB."
        )
        ttk.Label(self.search_tab, text=info, wraplength=1000, justify="left").pack(fill="x", pady=(8, 6))

        result_frame = ttk.LabelFrame(self.search_tab, text="Search results", padding=6)
        result_frame.pack(fill="both", expand=True)
        result_frame.rowconfigure(0, weight=1)
        result_frame.columnconfigure(0, weight=1)
        self.online_result_text = tk.Text(result_frame, wrap="word", state="disabled")
        self.online_result_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(result_frame, command=self.online_result_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.online_result_text.configure(yscrollcommand=scroll.set)

    def _build_database(self):
        self.database_tab.rowconfigure(1, weight=1)
        self.database_tab.columnconfigure(0, weight=1)

        controls = ttk.Frame(self.database_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.database_rebuild_button = ttk.Button(
            controls, text="Rebuild local search index", command=self._rebuild_search_index
        )
        self.database_rebuild_button.pack(side="left")
        ttk.Button(controls, text="Refresh diagnostics", command=self._refresh_database_diagnostics).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(controls, text="Backup database…", command=self._backup_database).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(controls, text="Identity audit", command=self._run_identity_audit).pack(
            side="left", padx=(6, 0)
        )

        frame = ttk.LabelFrame(self.database_tab, text="EverQuestie SQLite diagnostics", padding=8)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.database_text = tk.Text(frame, wrap="word", state="disabled")
        self.database_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.database_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.database_text.configure(yscrollcommand=scroll.set)
        self._refresh_database_diagnostics()

    def _build_import(self):
        root = self.import_tab.content
        root.columnconfigure(0, weight=1)

        settings_frame = ttk.LabelFrame(root, text="Persistent settings", padding=10)
        settings_frame.pack(fill="x")
        settings_frame.columnconfigure(1, weight=1)
        ttk.Label(settings_frame, text="Settings file").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings_frame, textvariable=self.settings_path_var, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=8
        )
        ttk.Button(settings_frame, text="Open…", command=self._open_settings_file).grid(row=0, column=2)
        ttk.Button(settings_frame, text="Save now", command=self._save_settings_now).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(settings_frame, text="UI theme").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(
            settings_frame,
            textvariable=self.ui_theme_var,
            values=ThemeManager.labels(),
            state="readonly",
            width=28,
        ).grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))
        ttk.Label(
            settings_frame,
            text=(
                "Classic EQ Stone is an original EverQuestie theme inspired by the old blue/gray marble UI. "
                "Theme choice and selected paths are saved automatically."
            ),
            wraplength=950,
            justify="left",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        client = ttk.LabelFrame(root, text="EverQuest client data", padding=10)
        client.pack(fill="x", pady=(8, 0))
        client.columnconfigure(1, weight=1)
        ttk.Label(client, text="EverQuest folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(client, textvariable=self.eq_game_path_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(client, text="Browse…", command=self._browse_eq_game_path).grid(row=0, column=2)
        client_buttons = ttk.Frame(client)
        client_buttons.grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))
        ttk.Button(
            client_buttons,
            text="Import basic client files",
            command=self._import_eq_client,
        ).pack(side="left")
        self.client_compile_button = ttk.Button(
            client_buttons,
            text="Compile full local DB via MCP (offline)",
            command=self._compile_eq_client_via_mcp,
        )
        self.client_compile_button.pack(side="left", padx=(6, 0))
        ttk.Label(
            client,
            textvariable=self.client_compile_status_var,
            wraplength=950,
            justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(
            client,
            text=(
                "The full compile first captures everquest1-mcp's local inventory, then directly invokes its built localdata "
                "module to compile rich per-record details for spells, zones, factions, achievements, AAs, Overseer, mercenaries, "
                "tributes and lore. EverQuestie also imports local skill-cap/base-stat/AC/stacking tables. No community source is "
                "loaded by this operation. Any pre-existing .eq-mcp-snapshot.json is restored after the compile."
            ),
            wraplength=950,
            justify="left",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        mcp = ttk.LabelFrame(root, text="everquest1-mcp repository", padding=10)
        mcp.pack(fill="x", pady=(8, 0))
        mcp.columnconfigure(1, weight=1)
        ttk.Label(mcp, text="Repository path").grid(row=0, column=0, sticky="w")
        ttk.Entry(mcp, textvariable=self.mcp_path_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(mcp, text="Browse…", command=self._browse_mcp_path).grid(row=0, column=2)
        ttk.Button(mcp, text="Recheck", command=self._refresh_mcp_status).grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))
        ttk.Label(mcp, textvariable=self.mcp_status_var, wraplength=950, justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )
        ttk.Label(
            mcp,
            text="The MCP repository is not required while playing. It is used for explicit Search and for the manual offline client-data compile, then EverQuestie runs from its own SQLite DB. "
                 "tools/setup_mcp_submodule.ps1 now works from both a Git checkout (real submodule) and the downloadable ZIP (standalone nested clone).",
            wraplength=950,
            justify="left",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        mirrors = ttk.LabelFrame(root, text="Allakhazam local mirrors", padding=10)
        mirrors.pack(fill="x", pady=(8, 0))
        mirrors.columnconfigure(1, weight=1)
        ttk.Label(mirrors, text="DB mirror").grid(row=0, column=0, sticky="w")
        ttk.Entry(mirrors, textvariable=self.db_mirror_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(mirrors, text="Browse…", command=lambda: self._browse_source_folder(self.db_mirror_var)).grid(row=0, column=2)
        ttk.Button(mirrors, text="Import / refresh DB mirror", command=self._import_db_mirror).grid(row=0, column=3, padx=(6, 0))

        ttk.Label(mirrors, text="Wiki mirror").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(mirrors, textvariable=self.wiki_mirror_var).grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(mirrors, text="Browse…", command=lambda: self._browse_source_folder(self.wiki_mirror_var)).grid(row=1, column=2, pady=(8, 0))
        ttk.Button(mirrors, text="Index / refresh Wiki mirror", command=self._import_wiki_mirror).grid(row=1, column=3, padx=(6, 0), pady=(8, 0))

        ttk.Label(
            mirrors,
            text="Manual only: EverQuestie does not scan, watch, index, modify, or otherwise open these mirror paths until you press the corresponding Import/Index button. Canonical Allakhazam URLs remain provenance keys; EverQuestie never fetches the mirror itself from the network.",
            wraplength=950,
            justify="left",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        single = ttk.LabelFrame(root, text="Single saved Allakhazam page", padding=10)
        single.pack(fill="x", pady=(8, 0))
        single.columnconfigure(1, weight=1)
        ttk.Label(single, text="Canonical URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(single, textvariable=self.import_url_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Label(single, text="Entity type").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(
            single,
            textvariable=self.import_type_var,
            values=["auto", "quest", "npc", "item", "zone"],
            state="readonly",
        ).grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))
        ttk.Label(single, text="Name override").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(single, textvariable=self.import_name_var).grid(row=2, column=1, sticky="ew", padx=8, pady=(8, 0))
        buttons = ttk.Frame(single)
        buttons.grid(row=3, column=1, sticky="w", padx=8, pady=(10, 0))
        ttk.Button(buttons, text="Choose saved HTML and import…", command=self._import_saved_html).pack(side="left")
        ttk.Button(
            buttons,
            text="Open URL in browser",
            command=lambda: open_url(self.import_url_var.get().strip()) if self.import_url_var.get().strip() else None,
        ).pack(side="left", padx=(6, 0))

        summary = ttk.LabelFrame(root, text="Local knowledge sources", padding=8)
        summary.pack(fill="both", expand=True, pady=(8, 0))
        summary.rowconfigure(0, weight=1)
        summary.columnconfigure(0, weight=1)
        self.source_summary_text = tk.Text(summary, height=8, wrap="word", state="disabled")
        self.source_summary_text.grid(row=0, column=0, sticky="nsew")
        source_scroll = ttk.Scrollbar(summary, orient="vertical", command=self.source_summary_text.yview)
        source_scroll.grid(row=0, column=1, sticky="ns")
        self.source_summary_text.configure(yscrollcommand=source_scroll.set)
        ttk.Button(summary, text="Refresh summary", command=self._refresh_source_summary).grid(row=1, column=0, sticky="w", pady=(6, 0))

    def _set_online_result(self, text: str) -> None:
        self.online_result_text.configure(state="normal")
        self.online_result_text.delete("1.0", "end")
        self.online_result_text.insert("end", text)
        self.online_result_text.configure(state="disabled")

    def _search_local_from_search_tab(self) -> None:
        query = self.online_query_var.get().strip()
        if not query:
            return
        hits = search_local_hits(
            self.db,
            query,
            current_zone=self.state_model.current_zone,
            limit=250,
        )
        if not hits:
            map_lines = self.map_view.map_label_search_summary(query) if hasattr(self, "map_view") else []
            if map_lines:
                self._set_online_result(
                    f"LOCAL DB | no normalized entity match: {query}\n\n"
                    "CURRENT LOCAL MAP | unclassified label evidence\n" +
                    "\n".join(map_lines)
                )
                self.online_status_var.set(
                    "No normalized DB entity matched; current local map label evidence is shown. No network request was made."
                )
                return
            self._set_online_result(f"LOCAL DB / CURRENT MAP | no match: {query}")
            self.online_status_var.set("Local-only search complete. No network request was made.")
            return
        lines = [f"LOCAL DB | {query} | {len(hits)} ranked match(es)", f"Filters: {query_summary(query)}", ""]
        for hit in hits[:100]:
            row = hit.row
            zone = f" | {row['zone']}" if row["zone"] else ""
            lines.append(f"[{row['kind']}] {row['name']}{zone} | {hit.reason}")
        if len(hits) > 100:
            lines.append(f"\n...and {len(hits)-100} more")
        self._set_online_result("\n".join(lines))
        self.online_status_var.set("Local-only ranked search complete. No network request was made.")

    def _search_allakhazam_from_search_tab(self) -> None:
        query = self.online_query_var.get().strip()
        if not query:
            return
        self.online_status_var.set("Opening an explicit Allakhazam browser search.")
        open_allakhazam_search(query)

    def _search_mcp_local(self) -> None:
        query = self.online_query_var.get().strip()
        if not query:
            return
        eq_path = self.eq_game_path_var.get().strip()
        if not eq_path:
            messagebox.showerror(
                "EverQuestie local MCP search",
                "Choose your EverQuest installation in the Sources tab first.",
            )
            return
        status = mcp_status(self.mcp_path_var.get().strip() or None)
        if not status.ready:
            messagebox.showerror("EverQuestie local MCP search", status.summary())
            self.online_status_var.set("Local MCP search was not started. " + status.summary())
            return

        self.online_status_var.set("Searching installed EverQuest data through MCP (offline)…")
        self._set_online_result("Searching local game data…")

        def worker() -> None:
            try:
                with MCPStdioClient(status.path, eq_game_path=eq_path) as client:
                    text = client.search(MCP_LOCAL_SEARCH_TOOL, query)
            except Exception as exc:
                self.after(0, lambda exc=exc: self._finish_mcp_local_error(exc))
                return
            self.after(0, lambda: self._finish_mcp_local(text))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_mcp_local(self, text: str) -> None:
        self._set_online_result(text)
        self.online_status_var.set(
            "Local MCP search complete. Installed EQ files only; no community-site request was made."
        )

    def _finish_mcp_local_error(self, exc: Exception) -> None:
        self._set_online_result(f"Local MCP search failed:\n\n{exc}")
        self.online_status_var.set("Local MCP search failed; no online search was started.")

    def _search_online_explicit(self) -> None:
        query = self.online_query_var.get().strip()
        source = self.online_source_var.get().strip()
        tool_name = ONLINE_TOOLS.get(source)
        if not query or not tool_name:
            return
        status = mcp_status(self.mcp_path_var.get().strip() or None)
        if not status.ready:
            messagebox.showerror("EverQuestie online search", status.summary())
            self.online_status_var.set("Online search was not started. " + status.summary())
            return

        self.online_status_var.set(f"Explicit online search running: {source}…")
        self._set_online_result("Searching…")
        eq_path = self.eq_game_path_var.get().strip() or None

        def worker() -> None:
            try:
                with MCPStdioClient(status.path, eq_game_path=eq_path) as client:
                    text = client.search(tool_name, query)
            except Exception as exc:
                self.after(0, lambda source=source, exc=exc: self._finish_online_search_error(source, exc))
                return
            self.after(0, lambda: self._finish_online_search(source, text))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_online_search(self, source: str, text: str) -> None:
        self._set_online_result(text)
        self.online_status_var.set(
            f"Explicit online search complete: {source}. Result is temporary and was not imported."
        )

    def _finish_online_search_error(self, source: str, exc: Exception) -> None:
        self._set_online_result(f"Online search failed:\n\n{exc}")
        self.online_status_var.set(f"Explicit online search failed: {source}.")

    def _set_database_text(self, text: str) -> None:
        if not hasattr(self, "database_text"):
            return
        self.database_text.configure(state="normal")
        self.database_text.delete("1.0", "end")
        self.database_text.insert("end", text)
        self.database_text.configure(state="disabled")

    def _run_identity_audit(self) -> None:
        self._set_database_text(identity_audit_text(self.db))

    def _database_diagnostic_text(self) -> str:
        d = self.db.database_diagnostics()
        try:
            size = self.db.path.stat().st_size
        except OSError:
            size = 0
        lines = [
            "EverQuestie-owned SQLite database",
            "",
            f"Path: {d['path']}",
            f"File size: {size / (1024 * 1024):.1f} MiB",
            f"Integrity check: {d['integrity']}",
            f"FTS5 available: {'yes' if d['fts_available'] else 'no (LIKE fallback active)'}",
            f"FTS rows: {d['fts_rows']:,}",
            f"FTS state: {'needs rebuild (safe LIKE fallback active)' if d['fts_dirty'] else 'current'}",
            f"FTS last rebuild: {d['fts_last_rebuild'] or 'never'}",
            "",
            "Core rows:",
        ]
        for key, value in d["counts"].items():
            lines.append(f"  {key}: {value:,}")
        lines += ["", "Local client support tables:"]
        for key, value in d["support"].items():
            lines.append(f"  {key}: {value:,}")
        lines += [
            "",
            "Source policy:",
            "  EQ client: authoritative for local IDs/mechanics/zone identity",
            "  Allakhazam: quest/world/community evidence when explicitly imported from the local mirror",
            "  Good/Brewall/EQ maps: selected map geometry and POIs",
            "  Conflicting evidence is retained through source provenance instead of silently fetching a replacement.",
        ]
        return "\n".join(lines)

    def _refresh_database_diagnostics(self) -> None:
        try:
            self._set_database_text(self._database_diagnostic_text())
        except Exception as exc:
            self._set_database_text(f"Database diagnostics failed:\n\n{exc}")

    def _rebuild_search_index(self) -> None:
        if getattr(self, "_database_rebuild_running", False):
            return
        self._database_rebuild_running = True
        self.database_rebuild_button.configure(state="disabled")
        self.status.set("Rebuilding local full-text search index…")
        db_path = self.db.path

        def worker() -> None:
            worker_db = None
            try:
                worker_db = Database(db_path)
                count = worker_db.rebuild_search_index()
            except Exception as exc:
                if worker_db is not None:
                    try: worker_db.close()
                    except Exception: pass
                self.after(0, lambda exc=exc: self._finish_search_rebuild_error(exc))
                return
            worker_db.close()
            self.after(0, lambda: self._finish_search_rebuild(count))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_search_rebuild(self, count: int) -> None:
        self._database_rebuild_running = False
        self.database_rebuild_button.configure(state="normal")
        self.status.set(f"Local search index rebuilt: {count:,} entities")
        self._refresh_database_diagnostics()
        self._refresh_source_summary()

    def _finish_search_rebuild_error(self, exc: Exception) -> None:
        self._database_rebuild_running = False
        self.database_rebuild_button.configure(state="normal")
        self.status.set("Local search-index rebuild failed")
        messagebox.showerror("EverQuestie search index", str(exc))
        self._refresh_database_diagnostics()

    def _backup_database(self) -> None:
        target = filedialog.asksaveasfilename(
            title="Back up EverQuestie SQLite database",
            defaultextension=".sqlite3",
            initialfile="eqquest-backup.sqlite3",
            filetypes=[("SQLite database", "*.sqlite3 *.db"), ("All files", "*.*")],
        )
        if not target:
            return
        try:
            out = sqlite3.connect(target)
            try:
                self.db.conn.backup(out)
            finally:
                out.close()
        except Exception as exc:
            messagebox.showerror("EverQuestie database backup", str(exc))
            return
        messagebox.showinfo("EverQuestie database backup", f"Backup written to:\n{target}")

    def _bind_settings_autosave(self) -> None:
        variables = [
            self.log_path,
            self.eq_game_path_var,
            self.mcp_path_var,
            self.db_mirror_var,
            self.wiki_mirror_var,
        ]
        if hasattr(self, "map_view"):
            variables.append(self.map_view.map_root)
        for variable in variables:
            variable.trace_add("write", lambda *_args: self._schedule_settings_save())
        self.ui_theme_var.trace_add("write", self._on_ui_theme_changed)

    def _on_ui_theme_changed(self, *_args) -> None:
        theme_id = ThemeManager.id_for_label(self.ui_theme_var.get())
        self.theme_manager.apply(theme_id)
        self._schedule_settings_save()

    def _schedule_settings_save(self) -> None:
        if self._settings_save_job is not None:
            try:
                self.after_cancel(self._settings_save_job)
            except Exception:
                pass
        self._settings_save_job = self.after(350, self._save_settings_now)

    def _save_settings_now(self) -> None:
        pending = self._settings_save_job
        self._settings_save_job = None
        if pending is not None:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
        map_root = self.map_view.map_root.get().strip() if hasattr(self, "map_view") else ""
        self.settings.update_paths({
            "log_file": self.log_path.get().strip(),
            "everquest_install": self.eq_game_path_var.get().strip(),
            "mcp_repository": self.mcp_path_var.get().strip(),
            "allakhazam_db_mirror": self.db_mirror_var.get().strip(),
            "allakhazam_wiki_mirror": self.wiki_mirror_var.get().strip(),
            "map_root": map_root,
        })
        self.settings.set("ui", "theme", ThemeManager.id_for_label(self.ui_theme_var.get()))
        self.settings.save()

        # Keep legacy metadata synchronized so older builds can still consume the
        # important paths if somebody rolls back.
        self.db.set_meta("eq_game_path", self.eq_game_path_var.get().strip())
        self.db.set_meta("allakhazam_db_mirror", self.db_mirror_var.get().strip())
        self.db.set_meta("allakhazam_wiki_mirror", self.wiki_mirror_var.get().strip())
        self.db.set_meta("map_root", map_root)

    def _open_settings_file(self) -> None:
        self._save_settings_now()
        try:
            if os.name == "nt":
                os.startfile(str(self.settings.path))
            else:
                webbrowser.open(self.settings.path.resolve().as_uri())
        except Exception as exc:
            messagebox.showerror("EverQuestie settings", f"Could not open settings.ini:\n\n{exc}")

    @staticmethod
    def _existing_initial_dir(path_text: str, *, file_path: bool = False) -> str | None:
        if not path_text:
            return None
        p = Path(path_text).expanduser()
        if file_path:
            p = p.parent
        return str(p) if p.is_dir() else None

    def _browse_eq_game_path(self) -> None:
        folder = filedialog.askdirectory(
            title="Choose EverQuest installation folder",
            initialdir=self._existing_initial_dir(self.eq_game_path_var.get().strip()),
        )
        if folder:
            self.eq_game_path_var.set(folder)

    def _browse_mcp_path(self) -> None:
        folder = filedialog.askdirectory(
            title="Choose everquest1-mcp repository folder",
            initialdir=self._existing_initial_dir(self.mcp_path_var.get().strip()),
        )
        if folder:
            self.mcp_path_var.set(folder)
            self._refresh_mcp_status()

    def _browse_source_folder(self, variable: tk.StringVar) -> None:
        folder = filedialog.askdirectory(
            title="Choose local mirror folder",
            initialdir=self._existing_initial_dir(variable.get().strip()),
        )
        if folder:
            variable.set(folder)

    def _refresh_mcp_status(self) -> None:
        status = mcp_status(self.mcp_path_var.get().strip() or None)
        self.mcp_status_var.set("MCP repository status: " + status.summary())

    def _refresh_source_summary(self) -> None:
        if not hasattr(self, "source_summary_text"):
            return
        lines = ["EverQuestie-owned SQLite knowledge DB", ""]
        stats = self.db.source_stats()
        if not stats:
            lines.append("No imported source records yet.")
        else:
            for row in stats:
                lines.append(
                    f"{row['source_name']} [{row['source_kind']}]: {row['records']} source record(s)"
                )
        total_entities = self.db.conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
        total_rels = self.db.conn.execute("SELECT COUNT(*) AS n FROM entity_relationships").fetchone()["n"]
        lines += ["", f"Entities: {total_entities:,}", f"Relationships: {total_rels:,}", "", "Entities by type:"]
        for row in self.db.conn.execute(
            "SELECT kind, COUNT(*) AS n FROM entities GROUP BY kind ORDER BY n DESC, kind"
        ).fetchall():
            lines.append(f"  {row['kind']}: {int(row['n']):,}")
        support = self.db.support_table_counts()
        lines += ["", "Local client support tables:"]
        for key, value in support.items():
            lines.append(f"  {key}: {value:,}")
        lines += [
            "",
            f"FTS5 search: {'available' if self.db.fts_available else 'unavailable (LIKE fallback)'}",
            f"FTS state: {'needs rebuild' if self.db.get_meta('fts_dirty', '1') == '1' else 'current'}",
            f"FTS last rebuild: {self.db.get_meta('fts_last_rebuild', '') or 'never'}",
        ]
        last_compile = self.db.get_meta("eq_mcp_last_compile", "")
        if last_compile:
            lines += ["", f"Last MCP client compile: {last_compile}"]
        detail_compile = self.db.get_meta("eq_mcp_detail_last_compile", "")
        if detail_compile:
            lines.append(f"Last rich-detail compile: {detail_compile}")
        self.source_summary_text.configure(state="normal")
        self.source_summary_text.delete("1.0", "end")
        self.source_summary_text.insert("end", "\n".join(lines))
        self.source_summary_text.configure(state="disabled")

    def _import_eq_client(self) -> None:
        folder = self.eq_game_path_var.get().strip()
        if not folder:
            self._browse_eq_game_path()
            folder = self.eq_game_path_var.get().strip()
        if not folder:
            return
        try:
            result = self.eq_client_importer.import_installation(folder)
        except Exception as exc:
            messagebox.showerror("EverQuest client import failed", str(exc))
            return
        messagebox.showinfo(
            "EverQuest client imported",
            f"Zones: {result.zones:,}\nOfficial help topics: {result.help_topics:,}\n"
            f"Skill-cap rows: {result.skill_caps:,}\nBase-stat rows: {result.base_stats:,}\n"
            f"AC rows: {result.ac_mitigation:,}\nSpell-stacking rows: {result.spell_stacking:,}\n"
            f"Additional dbstr identities: {result.dbstring_entities:,}\n"
            f"Missing optional datasets: {result.skipped}\n\n"
            "No network access was used.",
        )
        self._search_knowledge()
        self._refresh_source_summary()

    def _compile_eq_client_via_mcp(self) -> None:
        eq_path = self.eq_game_path_var.get().strip()
        mcp_path = self.mcp_path_var.get().strip()
        if not eq_path:
            self._browse_eq_game_path()
            eq_path = self.eq_game_path_var.get().strip()
        if not eq_path:
            return
        if self.tailer is not None:
            messagebox.showerror(
                "EverQuest client compile",
                "Stop log monitoring before running the full client-data compile. "
                "The compile performs a large local SQLite transaction.",
            )
            return
        status = mcp_status(mcp_path or None)
        if not status.ready:
            messagebox.showerror("EverQuest client compile", status.summary())
            self.client_compile_status_var.set("Compile not started: " + status.summary())
            return

        self._save_settings_now()
        self.client_compile_button.configure(state="disabled")
        self.client_compile_status_var.set(
            "Compiling installed EQ data through everquest1-mcp (offline)… "
            "This can take a while on the first run."
        )
        self.status.set("Compiling local EverQuest data…")

        db_path = self.db.path

        def worker() -> None:
            worker_db = None
            try:
                worker_db = Database(db_path)
                # Keep the direct authoritative imports too: they preserve full Help
                # text and the ZoneNames source record, while MCP supplies the broad
                # identity inventory for the much larger local data systems.
                basic = EQClientImporter(worker_db).import_installation(eq_path)
                def progress(text: str) -> None:
                    self.after(0, lambda text=text: self.client_compile_status_var.set(text))

                compiled = MCPLocalSnapshotCompiler(worker_db).compile_installation(
                    eq_path, status.path, include_details=True, progress=progress
                )
                fts_count = worker_db.rebuild_search_index()
            except Exception as exc:
                if worker_db is not None:
                    try:
                        worker_db.close()
                    except Exception:
                        pass
                self.after(0, lambda exc=exc: self._finish_eq_client_compile_error(exc))
                return
            try:
                worker_db.close()
            except Exception:
                pass
            self.after(0, lambda: self._finish_eq_client_compile(basic, compiled, fts_count))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_eq_client_compile(self, basic, compiled, fts_count: int) -> None:
        self.client_compile_button.configure(state="normal")
        suffix = f" | everquest1-mcp {compiled.mcp_version}" if compiled.mcp_version else ""
        self.client_compile_status_var.set(
            f"Last full MCP compile: {compiled.snapshot_timestamp or 'completed'}{suffix} | "
            f"{compiled.total_entities:,} inventory entities"
        )
        self.status.set("Local EverQuest data compile complete")
        lines = [
            f"Zones: {basic.zones:,}",
            f"Official help topics: {basic.help_topics:,}",
            f"Skill-cap rows: {basic.skill_caps:,}",
            f"Base-stat rows: {basic.base_stats:,}",
            f"AC-mitigation rows: {basic.ac_mitigation:,}",
            f"Spell-stacking rows: {basic.spell_stacking:,}",
            f"Additional dbstr identities: {basic.dbstring_entities:,}",
            "",
            *compiled.summary_lines(),
            "",
            f"Local FTS search rows: {fts_count:,}",
            "No community website was contacted.",
        ]
        messagebox.showinfo("EverQuest client data compiled", "\n".join(lines))
        self._search_knowledge()
        self._refresh_source_summary()
        self._refresh_database_diagnostics()
        self._refresh_mcp_status()

    def _finish_eq_client_compile_error(self, exc: Exception) -> None:
        self.client_compile_button.configure(state="normal")
        self.client_compile_status_var.set(f"Full MCP compile failed: {exc}")
        self.status.set("Local EverQuest data compile failed")
        messagebox.showerror("EverQuest client compile failed", str(exc))

    def _import_db_mirror(self) -> None:
        folder = self.db_mirror_var.get().strip()
        if not folder:
            self._browse_source_folder(self.db_mirror_var)
            folder = self.db_mirror_var.get().strip()
        if not folder:
            return
        try:
            summary = self.importer.import_mirror(folder)
        except Exception as exc:
            messagebox.showerror("Allakhazam DB mirror import failed", str(exc))
            return

        self.db.set_meta("allakhazam_db_mirror", folder)

        relationships = sum(r.relationships for r in summary.imported)
        discovered = sum(r.discovered_entities for r in summary.imported)
        steps = sum(r.quest_steps for r in summary.imported)
        locations = sum(r.locations for r in summary.imported)
        for imported in summary.imported:
            if imported.kind == "quest" and self.db.is_quest_tracked(imported.entity_id):
                self._reconcile_tracked_quest(imported.entity_id)

        messagebox.showinfo(
            "Allakhazam DB mirror refreshed",
            f"Imported/changed entity pages: {summary.changed}\n"
            f"Unchanged entity pages: {summary.unchanged}\n"
            f"Ignored/non-entity pages: {summary.ignored}\n"
            f"Read errors: {summary.read_errors}\n\n"
            f"Relationships: {relationships}\n"
            f"Discovered linked entities: {discovered}\n"
            f"Quest steps: {steps}\n"
            f"Locations: {locations}",
        )
        self._search_knowledge()
        self._refresh_guidance()
        self._refresh_source_summary()

    def _import_wiki_mirror(self) -> None:
        folder = self.wiki_mirror_var.get().strip()
        if not folder:
            self._browse_source_folder(self.wiki_mirror_var)
            folder = self.wiki_mirror_var.get().strip()
        if not folder:
            return
        try:
            result = self.wiki_importer.import_folder(folder)
        except Exception as exc:
            messagebox.showerror("Wiki mirror import failed", str(exc))
            return
        self.db.set_meta("allakhazam_wiki_mirror", folder)
        messagebox.showinfo(
            "Allakhazam Wiki indexed",
            f"Imported/changed: {result.imported}\nUnchanged: {result.unchanged}\nIgnored: {result.ignored}",
        )
        self._search_knowledge()
        self._refresh_source_summary()

    def _browse_log(self):
        path = filedialog.askopenfilename(
            title="Choose EverQuest log",
            initialdir=self._existing_initial_dir(self.log_path.get().strip(), file_path=True),
            filetypes=[("EverQuest logs", "eqlog_*.txt"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.log_path.set(path)
            if hasattr(self, "map_view"):
                self.map_view.suggest_root_from_log(path)

    def _start(self):
        path = self.log_path.get().strip()
        if not path:
            self._browse_log()
            path = self.log_path.get().strip()
        if not path:
            return
        if not Path(path).exists():
            messagebox.showerror("EverQuestie", "That log file does not exist.")
            return

        if hasattr(self, "map_view"):
            self.map_view.suggest_root_from_log(path)
        self._stop()
        self._bootstrap_state_from_log(path)
        self.tailer = LogTailer(path, self.event_queue.put, start_at_end=True)
        self.tailer.start()
        self.status.set(f"Monitoring {Path(path).name}")

    def _stop(self):
        if self.tailer:
            self.tailer.stop()
            self.tailer = None
        self.status.set("Not monitoring")

    def _drain_lines(self):
        processed = 0
        while processed < 250:
            try:
                line = self.event_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            event = self.parser.parse_line(line)
            if not event:
                continue

            self.db.add_event(event)
            self.state_model.apply(event)
            self._handle_task_assigned(event)
            self.quest_engine.observe(event)
            if event.kind in VISIBLE_EVENT_KINDS:
                self._append_event(event.summary())
            self._handle_control_command(event)

            if self.state_model.current_zone:
                self._update_zone_display()
            if self.state_model.last_location:
                x, y, z = self.state_model.last_location
                self.loc_var.set(f"Location: {x:.1f}, {y:.1f}, {z:.1f}")

        if processed:
            self._refresh_guidance()

        self.after(100, self._drain_lines)

    def _update_zone_display(self) -> None:
        zone = self.state_model.current_zone or "unknown"
        source = self.state_model.zone_source
        suffix = "" if source in {"unknown", "log"} else f" [{source}]"
        self.zone_var.set(f"Zone: {zone}{suffix}")

    def _set_current_zone(self, zone: str, *, source: str, announce: bool = False, force: bool = False) -> bool:
        # Prefer the canonical local zone name/alias when the graph knows it, but
        # still allow a raw manual name so map packs work before zone HTML is imported.
        canonical = zone.strip()
        row, status = self.db.resolve_entity(canonical, "zone")
        if row is not None:
            canonical = row["name"]
        elif status == "ambiguous" and source == "manual":
            self._append_event(f"ZONE | multiple local zone matches: {zone}")
            return False

        changed = self.state_model.set_zone(canonical, source=source, force=force)
        if changed:
            self._update_zone_display()
            if announce:
                self._append_event(f"ZONE | set to {canonical} ({source})")
            if hasattr(self, "map_view"):
                self.map_view.manual_zone.set(canonical)
                self.map_view.load_current_zone()
        return changed

    def _quest_zone_name(self, quest_id: int) -> str | None:
        row = self.db.entity(quest_id)
        if row is not None and row["zone"]:
            return str(row["zone"])
        targets = self.db.relationship_targets(quest_id, "occurs_in")
        if targets:
            return str(targets[0]["name"])
        for step in self.db.quest_steps(quest_id):
            if step["zone"]:
                return str(step["zone"])
        return None

    def _suggest_zone_from_quest(self, quest_id: int) -> None:
        zone = self._quest_zone_name(quest_id)
        if not zone:
            return
        changed = self._set_current_zone(zone, source="quest", announce=False)
        if changed:
            row = self.db.entity(quest_id)
            name = row["name"] if row else str(quest_id)
            self._append_event(f"ZONE | inferred {zone} from tracked quest: {name}")

    def _bootstrap_state_from_log(self, log_path: str | Path) -> None:
        """Recover the latest zone and /loc before live tailing begins.

        We scan only candidate zone/location lines, so even a large log avoids the
        cost of fully parsing and storing historical combat text at startup.
        """
        latest_zone: str | None = None
        latest_loc: tuple[float, float, float] | None = None
        try:
            with Path(log_path).open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "You have entered " not in line and "Your Location is " not in line:
                        continue
                    event = self.parser.parse_line(line)
                    if event is None:
                        continue
                    if event.kind == "zone" and event.zone:
                        latest_zone = event.zone
                        latest_loc = None
                    elif event.kind == "loc":
                        latest_loc = (
                            float(event.fields["x"]),
                            float(event.fields["y"]),
                            float(event.fields["z"]),
                        )
        except (OSError, PermissionError):
            return

        if latest_zone:
            self.state_model.set_zone(latest_zone, source="log-history", force=True)
        if latest_loc is not None:
            self.state_model.last_location = latest_loc
        self._update_zone_display()
        if latest_loc is not None:
            x, y, z = latest_loc
            self.loc_var.set(f"Location: {x:.1f}, {y:.1f}, {z:.1f}")
        if latest_zone and hasattr(self, "map_view"):
            self.map_view.manual_zone.set(latest_zone)
            self.map_view.load_current_zone()

    def _reconcile_tracked_quest(self, quest_id: int):
        """Rebuild a tracked quest from the selected log, falling back to stored events."""
        log_value = self.log_path.get().strip()
        try:
            if log_value and Path(log_value).exists():
                return self.quest_engine.reconcile_quest_from_log(
                    quest_id, log_value, parser=self.parser
                )
            return self.quest_engine.reconcile_quest_from_history(quest_id)
        except Exception as exc:
            self._append_event(f"RECONCILE | failed: {exc}")
            return None

    def _track_and_reconcile(self, quest_id: int, *, announce: str | None = None):
        self.db.track_quest(quest_id)
        self._suggest_zone_from_quest(quest_id)
        result = self._reconcile_tracked_quest(quest_id)
        row = self.db.entity(quest_id)
        name = row["name"] if row else str(quest_id)
        if announce:
            self._append_event(f"{announce}: {name}")
        if result is not None:
            self._append_event(
                f"RECONCILE | {name} | {result.confidence} confidence | {result.summary()}"
            )
        return result

    def _handle_task_assigned(self, event):
        if event.kind != "task_assigned" or not event.text:
            return
        row, _status = self.db.resolve_entity(event.text, "quest")
        if row is None:
            return
        self._track_and_reconcile(
            int(row["id"]), announce="QUEST | auto-tracked assigned task"
        )

    def _handle_control_command(self, event):
        command = parse_control_command(event)
        if command is None:
            return

        if command.verb == "quest":
            row, status = self.db.resolve_entity(command.argument, "quest")
            if row is not None:
                self._track_and_reconcile(
                    int(row["id"]), announce="COMMAND | tracking quest"
                )
                self.search_var.set(row["name"])
                self.kind_var.set("quest")
                self._search_knowledge()
            elif status == "ambiguous":
                self.search_var.set(command.argument)
                self.kind_var.set("quest")
                self._search_knowledge()
                self._append_event(
                    f"COMMAND | multiple local quests match: {command.argument}"
                )
            else:
                self.search_var.set(command.argument)
                self.kind_var.set("quest")
                self._search_knowledge()
                self._append_event(
                    f"COMMAND | quest not in local knowledge: {command.argument}"
                )

        elif command.verb == "unquest":
            row, status = self.db.resolve_entity(command.argument, "quest")
            if row is not None:
                self.db.untrack_quest(int(row["id"]))
                self._append_event(f"COMMAND | untracked quest: {row['name']}")
            else:
                self._append_event(
                    f"COMMAND | could not uniquely resolve quest: {command.argument}"
                )

        elif command.verb == "find":
            self.search_var.set(command.argument)
            self.kind_var.set("all")
            self._search_knowledge()
            self._append_event(find_text(self.db, command.argument))

        elif command.verb == "where":
            self.search_var.set(command.argument)
            self.kind_var.set("all")
            self._search_knowledge()
            row, status = self.db.resolve_entity(command.argument)
            if row is not None:
                self._append_event(
                    where_text(self.db, int(row["id"]), self.state_model.current_zone)
                )
            elif status == "ambiguous":
                self._append_event(f"WHERE | multiple local matches: {command.argument}")
            else:
                self._append_event(f"WHERE | no local match: {command.argument}")

        elif command.verb == "zone":
            self._set_current_zone(command.argument, source="manual", announce=True, force=True)

        elif command.verb == "status":
            tracked = self.db.tracked_quests()
            names = ", ".join(q["name"] for q in tracked) or "none"
            zone = self.state_model.current_zone or "unknown"
            self._append_event(
                f"COMMAND | zone={zone}; tracked quests={names}"
            )

        self._refresh_guidance()

    def _append_event(self, text: str):
        self.event_text.configure(state="normal")
        self.event_text.insert("end", text + "\n")
        if int(self.event_text.index("end-1c").split(".")[0]) > 1200:
            self.event_text.delete("1.0", "200.0")
        self.event_text.see("end")
        self.event_text.configure(state="disabled")

    @staticmethod
    def _step_tree_text(step) -> str:
        try:
            rule = json.loads(step["match_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            rule = {}
        need = max(1, int(rule.get("count", 1) or 1))
        progress = min(int(step["progress_count"] or 0), need)
        done = bool(int(step["complete"] or 0))
        mark = "[✓]" if done else "[ ]"
        count = f"  {progress}/{need}" if need > 1 else ""
        return f"{mark} {step['description']}{count}"

    def _refresh_guidance(self):
        quests = self.db.tracked_quests()
        selected_quest = self._tracked_selected_quest_id() if hasattr(self, "tracked_tree") else None
        selected_step = self._tracked_selected_step() if hasattr(self, "tracked_tree") else None

        self._tracked_quest_by_item.clear()
        self._tracked_step_by_item.clear()
        self.tracked_tree.delete(*self.tracked_tree.get_children(""))
        for q in quests:
            quest_id = int(q["id"])
            steps = list(self.db.quest_steps(quest_id))
            completed = sum(1 for step in steps if int(step["complete"] or 0))
            mark = "[✓]" if steps and completed == len(steps) else "[-]"
            suffix = f"  {completed}/{len(steps)}" if steps else ""
            qitem = f"tracked:q:{quest_id}"
            self.tracked_tree.insert("", "end", iid=qitem, text=f"{mark} {q['name']}{suffix}", open=True)
            self._tracked_quest_by_item[qitem] = quest_id
            for step in steps:
                order = int(step["step_order"])
                sitem = f"tracked:s:{quest_id}:{order}"
                self.tracked_tree.insert(qitem, "end", iid=sitem, text=self._step_tree_text(step))
                self._tracked_quest_by_item[sitem] = quest_id
                self._tracked_step_by_item[sitem] = (quest_id, order)

        # Preserve selection across progress refreshes when possible.
        restore = None
        if selected_step:
            candidate = f"tracked:s:{selected_step[0]}:{selected_step[1]}"
            if self.tracked_tree.exists(candidate):
                restore = candidate
        if restore is None and selected_quest is not None:
            candidate = f"tracked:q:{selected_quest}"
            if self.tracked_tree.exists(candidate):
                restore = candidate
        if restore:
            self.tracked_tree.selection_set(restore)
            self.tracked_tree.focus(restore)
            self.tracked_tree.see(restore)

        guides = self.quest_engine.guidance(self.state_model.current_zone)
        self.guide_text.configure(state="normal")
        self.guide_text.delete("1.0", "end")
        if not guides:
            self.guide_text.insert(
                "end",
                "No quest is tracked.\n\n"
                "Search the Knowledge tab, select a quest, and press Track quest.",
            )
        else:
            for g in guides:
                self.guide_text.insert("end", f"{g.title}\n{g.text}\n\n")
        self.guide_text.configure(state="disabled")

    def _tracked_selected_quest_id(self) -> int | None:
        if not hasattr(self, "tracked_tree"):
            return None
        selected = self.tracked_tree.selection()
        if not selected:
            return None
        return self._tracked_quest_by_item.get(selected[0])

    def _tracked_selected_step(self) -> tuple[int, int] | None:
        if not hasattr(self, "tracked_tree"):
            return None
        selected = self.tracked_tree.selection()
        if not selected:
            return None
        return self._tracked_step_by_item.get(selected[0])

    def _tracked_tree_selected(self, _event=None) -> None:
        selected_step = self._tracked_selected_step()
        if not selected_step:
            return
        quest_id, order = selected_step
        step = next((s for s in self.db.quest_steps(quest_id) if int(s["step_order"]) == order), None)
        if step is None:
            return
        try:
            rule = json.loads(step["match_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            rule = {}
        target = None
        target_kind = None
        if rule.get("item"):
            target, target_kind = str(rule["item"]), "item"
        elif rule.get("npc"):
            target, target_kind = str(rule["npc"]), "npc"
        elif rule.get("target") and str(rule.get("event", "")).casefold() in {"kill", "consider", "target_npc"}:
            target, target_kind = str(rule["target"]), "npc"
        if not target:
            return
        row, _status = self.db.resolve_entity(target, target_kind)
        if row is None:
            row, _status = self.db.resolve_entity(target)
        if row is not None and hasattr(self, "map_view"):
            self.map_view.focus_entity(int(row["id"]))

    def _search_knowledge(self):
        term = self.search_var.get().strip()
        kind = None if self.kind_var.get() == "all" else self.kind_var.get()
        counts = count_local_entities_by_kind(
            self.db,
            term,
            default_kind=kind,
            current_zone=self.state_model.current_zone,
        )

        self._knowledge_search_term = term
        self._knowledge_entity_by_item.clear()
        self._knowledge_kind_nodes.clear()
        self._knowledge_loaded_nodes.clear()
        self._knowledge_counts = {str(r["kind"]): int(r["count"]) for r in counts}

        self.entity_tree.delete(*self.entity_tree.get_children(""))
        if not counts:
            map_lines = self.map_view.map_label_search_summary(term) if term and hasattr(self, "map_view") else []
            if map_lines:
                self.entity_tree.insert(
                    "", "end", iid="info:maplabels",
                    text=f"Map labels ({len(map_lines)}) — no normalized DB entity yet",
                )
                self.entity_text.configure(state="normal")
                self.entity_text.delete("1.0", "end")
                self.entity_text.insert(
                    "end",
                    "No normalized EverQuestie knowledge entity matched. Current local map evidence:\n\n" +
                    "\n".join(map_lines) +
                    "\n\nMap labels remain unclassified until another local source supplies an entity identity/type."
                )
                self.entity_text.configure(state="disabled")
                return
            self.entity_tree.insert("", "end", iid="info:none", text="No local knowledge or current-map label matches.")
            self.entity_text.configure(state="normal")
            self.entity_text.delete("1.0", "end")
            self.entity_text.configure(state="disabled")
            return

        known_order = {name: i for i, name in enumerate(KNOWLEDGE_KIND_LABELS)}
        ordered = sorted(
            counts,
            key=lambda r: (known_order.get(str(r["kind"]), 10_000), str(r["kind"])),
        )
        total_matches = sum(int(r["count"]) for r in ordered)
        auto_expand = bool(kind) or (bool(term) and total_matches <= 500)

        for row in ordered:
            topic = str(row["kind"])
            count = int(row["count"])
            node = f"kind:{topic}"
            label = self._knowledge_kind_label(topic)
            self.entity_tree.insert(
                "",
                "end",
                iid=node,
                text=f"{label} ({count:,})",
                open=False,
            )
            self._knowledge_kind_nodes[topic] = node
            # A placeholder child gives the topic its native [+] expansion control
            # without materializing huge MCP inventories up front.
            self.entity_tree.insert(node, "end", iid=f"placeholder:{topic}", text="Loading…")
            if auto_expand:
                self._populate_knowledge_kind(topic, node)
                self.entity_tree.item(node, open=True)

    def _selected_entity_id(self) -> int | None:
        if not hasattr(self, "entity_tree"):
            return None
        selected = self.entity_tree.selection()
        if not selected:
            return None
        return self._knowledge_entity_by_item.get(selected[0])

    def _show_entity(self):
        entity_id = self._selected_entity_id()
        if entity_id is None:
            return
        r = self.db.entity(entity_id)
        if not r:
            return

        detail = entity_detail_text(self.db, entity_id, include_source_text=True)

        self.entity_text.configure(state="normal")
        self.entity_text.delete("1.0", "end")
        self.entity_text.insert("end", detail)
        self.entity_text.configure(state="disabled")

    def _search_allakhazam(self):
        term = self.search_var.get().strip()
        if term:
            open_allakhazam_search(term)

    def _track_selected(self):
        entity_id = self._selected_entity_id()
        if entity_id is None:
            return
        r = self.db.entity(entity_id)
        if r["kind"] != "quest":
            messagebox.showinfo("EverQuestie", "Only quest entities can be tracked.")
            return
        self._track_and_reconcile(entity_id, announce="QUEST | tracking")
        self._refresh_guidance()

    def _untrack_selected(self):
        entity_id = self._selected_entity_id()
        if entity_id is None:
            return
        self.db.untrack_quest(entity_id)
        self._refresh_guidance()

    def _open_entity_source(self):
        entity_id = self._selected_entity_id()
        if entity_id is None:
            return
        r = self.db.entity(entity_id)
        if r["source_url"]:
            open_url(r["source_url"])

    def _reconcile_selected_tracked(self):
        quest_id = self._tracked_selected_quest_id()
        if quest_id is None:
            return
        result = self._reconcile_tracked_quest(quest_id)
        row = self.db.entity(quest_id)
        if result is not None and row is not None:
            self._append_event(
                f"RECONCILE | {row['name']} | {result.confidence} confidence | {result.summary()}"
            )
        self._refresh_guidance()

    def _open_tracked_source(self):
        quest_id = self._tracked_selected_quest_id()
        if quest_id is None:
            return
        r = self.db.entity(quest_id)
        if r and r["source_url"]:
            open_url(r["source_url"])

    def _import_saved_html(self):
        source_url = self.import_url_var.get().strip() or None

        html_path = filedialog.askopenfilename(
            title="Choose the saved Allakhazam HTML page",
            initialdir=self._existing_initial_dir(self.settings.get_path("last_saved_html_dir")),
            filetypes=[
                ("HTML files", "*.html *.htm"),
                ("All files", "*.*"),
            ],
        )
        if not html_path:
            return
        self.settings.set_path("last_saved_html_dir", str(Path(html_path).parent))
        self.settings.save()

        kind = self.import_type_var.get()
        kind_hint = None if kind == "auto" else kind
        name_hint = self.import_name_var.get().strip() or None

        try:
            result = self.importer.import_saved_html(
                html_path,
                source_url,
                kind_hint=kind_hint,
                name_hint=name_hint,
            )
        except Exception as exc:
            messagebox.showerror("Import failed", str(exc))
            return

        if result.kind == "quest" and self.db.is_quest_tracked(result.entity_id):
            self._reconcile_tracked_quest(result.entity_id)

        messagebox.showinfo(
            "Imported",
            f"Imported {result.kind}: {result.name}\n\n"
            f"Relationships: {result.relationships}\n"
            f"Discovered linked entities: {result.discovered_entities}\n"
            f"Quest steps: {result.quest_steps}\n"
            f"Locations: {result.locations}\n\n"
            f"SHA-256: {result.sha256}",
        )
        self.search_var.set(result.name)
        self.kind_var.set(result.kind)
        self._search_knowledge()
        self._refresh_source_summary()

    def _import_html_folder(self, folder_override: str | None = None):
        folder = folder_override or filedialog.askdirectory(
            title="Choose local Allakhazam DB mirror or saved HTML folder",
            initialdir=self._existing_initial_dir(
                self.settings.get_path("last_allakhazam_import_dir") or self.db_mirror_var.get().strip()
            ),
        )
        if not folder:
            return
        self.settings.set_path("last_allakhazam_import_dir", folder)
        self.settings.save()
        try:
            results = self.importer.import_folder(folder)
        except Exception as exc:
            messagebox.showerror("Folder import failed", str(exc))
            return
        if not results:
            messagebox.showinfo("Import", "No recognizable Allakhazam entity pages were found.")
            return
        relationships = sum(r.relationships for r in results)
        discovered = sum(r.discovered_entities for r in results)
        steps = sum(r.quest_steps for r in results)
        locations = sum(r.locations for r in results)
        for imported in results:
            if imported.kind == "quest" and self.db.is_quest_tracked(imported.entity_id):
                self._reconcile_tracked_quest(imported.entity_id)
        messagebox.showinfo(
            "Imported folder",
            f"Pages imported: {len(results)}\n"
            f"Relationships: {relationships}\n"
            f"Discovered linked entities: {discovered}\n"
            f"Quest steps: {steps}\n"
            f"Locations: {locations}",
        )
        self._search_knowledge()
        self._refresh_guidance()
        self._refresh_source_summary()

    def _on_close(self):
        self._stop()
        self._save_settings_now()
        self.db.close()
        self.destroy()


def main():
    app = EverQuestieApp()
    app.mainloop()
