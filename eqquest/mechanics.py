from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .db import Database


EQ_CLASSES = {
    1: "Warrior",
    2: "Cleric",
    3: "Paladin",
    4: "Ranger",
    5: "Shadowknight",
    6: "Druid",
    7: "Monk",
    8: "Bard",
    9: "Rogue",
    10: "Shaman",
    11: "Necromancer",
    12: "Wizard",
    13: "Magician",
    14: "Enchanter",
    15: "Beastlord",
    16: "Berserker",
}


def _class_label(class_id: int) -> str:
    return f"{class_id} — {EQ_CLASSES.get(class_id, 'Class ' + str(class_id))}"


def _source_label(row) -> str:
    if row is None:
        return ""
    return str(row["source_name"] or row["local_path"] or row["url"] or "")


class MechanicsFrame(ttk.Frame):
    """Read-only browser for deterministic EverQuest client support tables."""

    def __init__(self, master, *, db: Database):
        super().__init__(master, padding=8)
        self.db = db
        self.class_var = tk.StringVar(value=_class_label(1))
        self.level_var = tk.IntVar(value=1)
        self.spell_query = tk.StringVar()
        self.status_var = tk.StringVar()
        self._spell_entity_by_item: dict[str, int] = {}
        self._build()
        self.refresh_class_level()
        self.refresh_counts()

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(top, textvariable=self.status_var).pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_all).pack(side="right")

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew")

        self.progression_tab = ttk.Frame(notebook, padding=8)
        self.stacking_tab = ttk.Frame(notebook, padding=8)
        notebook.add(self.progression_tab, text="Class / level")
        notebook.add(self.stacking_tab, text="Spell stacking")
        self._build_progression()
        self._build_stacking()

    def _build_progression(self) -> None:
        tab = self.progression_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        controls = ttk.Frame(tab)
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Label(controls, text="Class:").pack(side="left")
        class_box = ttk.Combobox(
            controls,
            textvariable=self.class_var,
            values=[_class_label(i) for i in sorted(EQ_CLASSES)],
            state="readonly",
            width=24,
        )
        class_box.pack(side="left", padx=(5, 10))
        class_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_class_level())
        ttk.Label(controls, text="Level:").pack(side="left")
        level = ttk.Spinbox(
            controls,
            from_=1,
            to=125,
            textvariable=self.level_var,
            width=6,
            command=self.refresh_class_level,
        )
        level.pack(side="left", padx=(5, 6))
        level.bind("<Return>", lambda _e: self.refresh_class_level())
        level.bind("<FocusOut>", lambda _e: self.refresh_class_level())
        ttk.Button(controls, text="Show", command=self.refresh_class_level).pack(side="left")

        summary_frame = ttk.LabelFrame(tab, text="Base statistics and AC mitigation", padding=6)
        summary_frame.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        summary_frame.columnconfigure(0, weight=1)
        self.class_summary = tk.Text(summary_frame, height=8, wrap="word", state="disabled")
        self.class_summary.grid(row=0, column=0, sticky="ew")
        summary_scroll = ttk.Scrollbar(summary_frame, orient="vertical", command=self.class_summary.yview)
        summary_scroll.grid(row=0, column=1, sticky="ns")
        self.class_summary.configure(yscrollcommand=summary_scroll.set)

        skills_frame = ttk.LabelFrame(tab, text="Skill caps at selected level", padding=6)
        skills_frame.grid(row=2, column=0, sticky="nsew")
        skills_frame.rowconfigure(0, weight=1)
        skills_frame.columnconfigure(0, weight=1)
        self.skills_tree = ttk.Treeview(
            skills_frame,
            columns=("skill", "cap", "source"),
            show="headings",
            selectmode="browse",
        )
        for col, label, width in (
            ("skill", "Skill ID", 90),
            ("cap", "Cap", 90),
            ("source", "Source", 420),
        ):
            self.skills_tree.heading(col, text=label)
            self.skills_tree.column(col, width=width, stretch=(col == "source"))
        self.skills_tree.grid(row=0, column=0, sticky="nsew")
        vscroll = ttk.Scrollbar(skills_frame, orient="vertical", command=self.skills_tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll = ttk.Scrollbar(skills_frame, orient="horizontal", command=self.skills_tree.xview)
        hscroll.grid(row=1, column=0, sticky="ew")
        self.skills_tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)

    def _build_stacking(self) -> None:
        tab = self.stacking_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        tab.rowconfigure(4, weight=1)

        controls = ttk.Frame(tab)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Spell:").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(controls, textvariable=self.spell_query)
        entry.grid(row=0, column=1, sticky="ew", padx=6)
        entry.bind("<Return>", lambda _e: self.search_spells())
        ttk.Button(controls, text="Search local", command=self.search_spells).grid(row=0, column=2)

        ttk.Label(
            tab,
            text=(
                "Searches normalized spell entities in EverQuestie's local DB, then reads SpellStackingGroups.txt-derived "
                "rows. Stacking group/type/rank are shown exactly as stored by the installed client data."
            ),
            wraplength=1000,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(6, 4))

        results = ttk.LabelFrame(tab, text="Spell matches", padding=6)
        results.grid(row=2, column=0, sticky="nsew")
        results.rowconfigure(0, weight=1)
        results.columnconfigure(0, weight=1)
        self.spell_tree = ttk.Treeview(results, columns=("id", "zone"), show="tree headings", height=8)
        self.spell_tree.heading("#0", text="Spell")
        self.spell_tree.heading("id", text="Spell ID")
        self.spell_tree.heading("zone", text="Match")
        self.spell_tree.column("#0", width=330, stretch=True)
        self.spell_tree.column("id", width=90, stretch=False)
        self.spell_tree.column("zone", width=180, stretch=True)
        self.spell_tree.grid(row=0, column=0, sticky="nsew")
        sv = ttk.Scrollbar(results, orient="vertical", command=self.spell_tree.yview)
        sv.grid(row=0, column=1, sticky="ns")
        self.spell_tree.configure(yscrollcommand=sv.set)
        self.spell_tree.bind("<<TreeviewSelect>>", lambda _e: self._spell_selected())

        ttk.Label(tab, text="Stacking group / peers").grid(row=3, column=0, sticky="w", pady=(8, 2))
        detail_frame = ttk.Frame(tab)
        detail_frame.grid(row=4, column=0, sticky="nsew")
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        self.stacking_text = tk.Text(detail_frame, wrap="word", state="disabled")
        self.stacking_text.grid(row=0, column=0, sticky="nsew")
        dv = ttk.Scrollbar(detail_frame, orient="vertical", command=self.stacking_text.yview)
        dv.grid(row=0, column=1, sticky="ns")
        self.stacking_text.configure(yscrollcommand=dv.set)

    def refresh_counts(self) -> None:
        counts = self.db.support_table_counts()
        self.status_var.set(
            "Local mechanics tables | "
            f"skill caps {counts.get('skill_caps', 0):,} | "
            f"base stats {counts.get('base_stats', 0):,} | "
            f"AC {counts.get('ac_mitigation', 0):,} | "
            f"spell stacking {counts.get('spell_stacking', 0):,}"
        )

    def refresh_all(self) -> None:
        self.refresh_counts()
        self.refresh_class_level()
        if self.spell_query.get().strip():
            self.search_spells()

    def _selected_class_id(self) -> int:
        try:
            return int(self.class_var.get().split("—", 1)[0].strip())
        except Exception:
            return 1

    def _nearest_row(self, table: str, class_id: int, level: int):
        return self.db.conn.execute(
            f"""
            SELECT t.*, sp.source_name, sp.local_path, sp.url
            FROM {table} t LEFT JOIN source_pages sp ON sp.id=t.source_page_id
            WHERE t.class_id=?
            ORDER BY ABS(t.level-?), CASE WHEN t.level<=? THEN 0 ELSE 1 END, t.level DESC
            LIMIT 1
            """,
            (class_id, level, level),
        ).fetchone()

    def refresh_class_level(self) -> None:
        class_id = self._selected_class_id()
        try:
            level = max(1, int(self.level_var.get()))
        except Exception:
            level = 1
            self.level_var.set(level)
        base = self._nearest_row("base_stats", class_id, level)
        ac = self._nearest_row("ac_mitigation", class_id, level)

        lines = [f"{EQ_CLASSES.get(class_id, 'Class')} (class ID {class_id}) | requested level {level}"]
        if base is None:
            lines += ["", "Base stats: no imported row for this class."]
        else:
            lines += [
                "",
                f"Base stats (row level {base['level']}):",
                f"  HP: {base['hp']}",
                f"  Mana: {base['mana']}",
                f"  Endurance: {base['endurance']}",
                f"  HP regen: {base['hp_regen']}",
                f"  Mana regen: {base['mana_regen']}",
                f"  Endurance regen: {base['endurance_regen']}",
            ]
            src = _source_label(base)
            if src:
                lines.append(f"  Source: {src}")
        if ac is None:
            lines += ["", "AC mitigation: no imported row for this class."]
        else:
            lines += [
                "",
                f"AC mitigation (row level {ac['level']}):",
                f"  AC cap: {ac['ac_cap']}",
                f"  Soft-cap multiplier: {ac['soft_cap_multiplier']}",
            ]
            src = _source_label(ac)
            if src:
                lines.append(f"  Source: {src}")
        self._set_text(self.class_summary, "\n".join(lines))

        self.skills_tree.delete(*self.skills_tree.get_children())
        rows = self.db.conn.execute(
            """
            SELECT sc.skill_id,sc.cap,sc.level,sp.source_name,sp.local_path,sp.url
            FROM skill_caps sc LEFT JOIN source_pages sp ON sp.id=sc.source_page_id
            WHERE sc.class_id=? AND sc.level=?
            ORDER BY sc.skill_id
            """,
            (class_id, level),
        ).fetchall()
        if not rows:
            nearest = self.db.conn.execute(
                "SELECT level FROM skill_caps WHERE class_id=? ORDER BY ABS(level-?),level LIMIT 1",
                (class_id, level),
            ).fetchone()
            if nearest is not None:
                rows = self.db.conn.execute(
                    """
                    SELECT sc.skill_id,sc.cap,sc.level,sp.source_name,sp.local_path,sp.url
                    FROM skill_caps sc LEFT JOIN source_pages sp ON sp.id=sc.source_page_id
                    WHERE sc.class_id=? AND sc.level=? ORDER BY sc.skill_id
                    """,
                    (class_id, int(nearest["level"])),
                ).fetchall()
        for row in rows:
            source = str(row["source_name"] or row["local_path"] or row["url"] or "")
            self.skills_tree.insert("", "end", values=(row["skill_id"], row["cap"], source))

    def _spell_id_for_entity(self, entity_id: int) -> int | None:
        row = self.db.entity(entity_id)
        if row is None:
            return None
        for ext in self.db.external_ids_for_entity(entity_id):
            if str(ext["namespace"]).casefold() in {"eqclient:spell", "everquest:spell", "spell"}:
                try:
                    return int(ext["external_id"])
                except Exception:
                    pass
        try:
            return int(str(row["external_id"] or ""))
        except Exception:
            return None

    def search_spells(self) -> None:
        term = self.spell_query.get().strip()
        if not term:
            return
        rows = self.db.search_entities_fts(term, "spell", limit=100)
        self.spell_tree.delete(*self.spell_tree.get_children())
        self._spell_entity_by_item.clear()
        for row in rows:
            entity_id = int(row["id"])
            spell_id = self._spell_id_for_entity(entity_id)
            match = "local spell entity"
            iid = self.spell_tree.insert("", "end", text=row["name"], values=(spell_id if spell_id is not None else "?", match))
            self._spell_entity_by_item[iid] = entity_id
        if rows:
            first = self.spell_tree.get_children()[0]
            self.spell_tree.selection_set(first)
            self.spell_tree.focus(first)
            self._spell_selected()
        else:
            self._set_text(self.stacking_text, f"No local spell entity matches: {term}")

    def _spell_selected(self) -> None:
        selected = self.spell_tree.selection()
        if not selected:
            return
        entity_id = self._spell_entity_by_item.get(selected[0])
        if entity_id is None:
            return
        entity = self.db.entity(entity_id)
        spell_id = self._spell_id_for_entity(entity_id)
        if spell_id is None:
            self._set_text(
                self.stacking_text,
                f"{entity['name']}\n\nNo numeric installed-client spell ID is linked to this entity yet.",
            )
            return
        row = self.db.conn.execute(
            """
            SELECT ss.*,sp.source_name,sp.local_path,sp.url
            FROM spell_stacking ss LEFT JOIN source_pages sp ON sp.id=ss.source_page_id
            WHERE ss.spell_id=?
            """,
            (spell_id,),
        ).fetchone()
        if row is None:
            self._set_text(
                self.stacking_text,
                f"{entity['name']} (spell ID {spell_id})\n\nNo SpellStackingGroups-derived row is imported for this spell.",
            )
            return
        lines = [
            f"{entity['name']} (spell ID {spell_id})",
            f"Stacking group: {row['stacking_group']}",
            f"Rank: {row['rank']}",
            f"Stacking type: {row['stacking_type']}",
        ]
        src = _source_label(row)
        if src:
            lines.append(f"Source: {src}")
        group = row["stacking_group"]
        if group is not None:
            peers = self.db.conn.execute(
                "SELECT spell_id,rank,stacking_type FROM spell_stacking WHERE stacking_group=? ORDER BY rank,spell_id",
                (group,),
            ).fetchall()
            lines += ["", f"Other spells in stacking group {group}:"]
            for peer in peers[:500]:
                peer_id = int(peer["spell_id"])
                name_row = self.db.conn.execute(
                    "SELECT name FROM entities WHERE kind='spell' AND external_id=? ORDER BY id LIMIT 1",
                    (str(peer_id),),
                ).fetchone()
                name = str(name_row["name"]) if name_row else f"spell ID {peer_id}"
                marker = " ← selected" if peer_id == spell_id else ""
                lines.append(
                    f"  • {name} | ID {peer_id} | rank {peer['rank']} | type {peer['stacking_type']}{marker}"
                )
            if len(peers) > 500:
                lines.append(f"  … {len(peers)-500} more")
        self._set_text(self.stacking_text, "\n".join(lines))

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")
