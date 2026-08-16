from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .mechanics import MechanicsFrame
from .mechanics_catalog import (
    EQ_CLASS_VOCABULARY,
    MECHANICS_CATALOG_VERSION,
    MechanicsCatalog,
)
from .mechanics_context import ClassMechanicsContext, build_class_mechanics_context
from .mechanics_profile_availability import mechanics_profile_source_notice
from .spell_stacking_context import spell_stacking_text


def ensure_builder_mechanics_catalog(db) -> bool:
    """Backfill deterministic mechanics identities in an existing writable builder DB.

    Release finalization already reconciles this catalog on the snapshot copy.  Older
    source-checkout databases can therefore contain all raw client support rows while
    still lacking the canonical class/skill identities the modern Mechanics UI reads.
    This compatibility ensure is deliberately builder-only and source-independent: it
    does not scan the EQ install or any mirror and never runs against immutable runtime
    knowledge.
    """
    if not getattr(db, "knowledge_writable", True):
        return False
    version = db.get_meta("mechanics_catalog_version", "")
    warrior = db.entity_by_namespaced_external_id("eqclient:class", "1")
    if version == MECHANICS_CATALOG_VERSION and warrior is not None:
        return False
    with db.batch():
        MechanicsCatalog(db).reconcile()
    return True


def mechanics_context_summary(context: ClassMechanicsContext) -> str:
    lines = [
        f"{context.identity.name} | level {context.requested_level}",
        "Exact client-table facts only; missing base/AC levels are not interpolated.",
    ]
    if context.base_stats is None:
        lines += ["", "Base resources: no exact-level row in shipped knowledge."]
    else:
        base = context.base_stats
        lines += [
            "",
            "Base resources:",
            f"  HP: {base.hp}",
            f"  Mana: {base.mana}",
            f"  Endurance: {base.endurance}",
            f"  HP regen: {base.hp_regen}",
            f"  Mana regen: {base.mana_regen}",
            f"  Endurance regen: {base.endurance_regen}",
            f"  Source: {base.source.label}",
        ]
    if context.ac_mitigation is None:
        lines += ["", "AC mitigation: no exact-level row in shipped knowledge."]
    else:
        ac = context.ac_mitigation
        lines += [
            "",
            "AC mitigation:",
            f"  AC cap: {ac.ac_cap}",
            f"  Soft-cap multiplier: {ac.soft_cap_multiplier}",
            f"  Source: {ac.source.label}",
        ]
    return "\n".join(lines)


def mechanics_skill_rows(context: ClassMechanicsContext) -> list[tuple[str, int, str, str]]:
    rows: list[tuple[str, int, str, str]] = []
    for skill in context.skills:
        changes: list[str] = []
        if skill.new_this_level:
            changes.append("new")
        if skill.changed_this_level:
            changes.append("cap changed")
        if not changes and skill.row_level != context.requested_level:
            changes.append(f"from level {skill.row_level}")
        rows.append((skill.name, skill.cap, ", ".join(changes), skill.source.label))
    return rows


class MechanicsContextFrame(MechanicsFrame):
    """Canonical mechanics browser shared by builder and packaged runtimes."""

    def __init__(self, master, *, db):
        ensure_builder_mechanics_catalog(db)
        # Mirror the small state setup from MechanicsFrame so the Class/level tab can
        # start with canonical names rather than the legacy numeric display token.
        ttk.Frame.__init__(self, master, padding=8)
        self.db = db
        self.class_var = tk.StringVar(value=EQ_CLASS_VOCABULARY[1][0])
        self.level_var = tk.IntVar(value=1)
        self.spell_query = tk.StringVar()
        self.status_var = tk.StringVar()
        self._spell_entity_by_item: dict[str, int] = {}
        self._build()
        self.refresh_class_level()
        self.refresh_counts()

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
            values=[EQ_CLASS_VOCABULARY[i][0] for i in sorted(EQ_CLASS_VOCABULARY)],
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

        summary_frame = ttk.LabelFrame(tab, text="Canonical class mechanics", padding=6)
        summary_frame.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        summary_frame.columnconfigure(0, weight=1)
        self.class_summary = tk.Text(summary_frame, height=9, wrap="word", state="disabled")
        self.class_summary.grid(row=0, column=0, sticky="ew")
        summary_scroll = ttk.Scrollbar(summary_frame, orient="vertical", command=self.class_summary.yview)
        summary_scroll.grid(row=0, column=1, sticky="ns")
        self.class_summary.configure(yscrollcommand=summary_scroll.set)

        skills_frame = ttk.LabelFrame(tab, text="Skills available by selected level", padding=6)
        skills_frame.grid(row=2, column=0, sticky="nsew")
        skills_frame.rowconfigure(0, weight=1)
        skills_frame.columnconfigure(0, weight=1)
        self.skills_tree = ttk.Treeview(
            skills_frame,
            columns=("skill", "cap", "change", "source"),
            show="headings",
            selectmode="browse",
        )
        for col, label, width in (
            ("skill", "Skill", 240),
            ("cap", "Cap", 90),
            ("change", "Progression", 150),
            ("source", "Source", 360),
        ):
            self.skills_tree.heading(col, text=label)
            self.skills_tree.column(col, width=width, stretch=(col == "source"))
        self.skills_tree.grid(row=0, column=0, sticky="nsew")
        vscroll = ttk.Scrollbar(skills_frame, orient="vertical", command=self.skills_tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll = ttk.Scrollbar(skills_frame, orient="horizontal", command=self.skills_tree.xview)
        hscroll.grid(row=1, column=0, sticky="ew")
        self.skills_tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)

    def refresh_class_level(self) -> None:
        token = self.class_var.get().strip()
        try:
            level = max(1, int(self.level_var.get()))
        except Exception:
            level = 1
            self.level_var.set(level)

        context, status = build_class_mechanics_context(self.db, token, level)
        self.skills_tree.delete(*self.skills_tree.get_children())
        if context is None:
            detail = "ambiguous; EverQuestie will not guess" if status == "ambiguous" else "not present in shipped knowledge"
            self._set_text(self.class_summary, f"Class identity {token!r} is {detail}.")
            return

        summary = mechanics_context_summary(context)
        source_notice = mechanics_profile_source_notice(self.db)
        self._set_text(self.class_summary, summary + "\n\n" + source_notice)
        for row in mechanics_skill_rows(context):
            self.skills_tree.insert("", "end", values=row)

    def _spell_selected(self) -> None:
        """Render selected spell through the canonical stacking read projection."""
        selected = self.spell_tree.selection()
        if not selected:
            return
        entity_id = self._spell_entity_by_item.get(selected[0])
        if entity_id is None:
            return
        self._set_text(self.stacking_text, spell_stacking_text(self.db, entity_id))
