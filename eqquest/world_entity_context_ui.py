from __future__ import annotations

from dataclasses import dataclass

from .world_entity_context import WorldEntityContext, _OUT_LABELS
from .world_entity_detail import build_world_entity_context_for_id


_WORLD_ENTITY_UI_MARKER = "_everquestie_world_entity_context_ui"
_WORLD_KINDS = {"npc", "quest", "item"}


@dataclass(frozen=True, slots=True)
class WorldEntityMapTarget:
    """One already-safe EQ game-space handoff from Knowledge to the Map owner."""

    location_id: int
    entity_id: int
    entity_name: str
    relation: str
    zone_entity_id: int
    zone_name: str
    x: float
    y: float
    z: float | None
    label: str
    source_label: str
    related: bool

    @property
    def loc_text(self) -> str:
        parts = [f"Y={self.y:g}", f"X={self.x:g}"]
        if self.z is not None:
            parts.append(f"Z={self.z:g}")
        return " ".join(parts)


def world_entity_map_targets(
    context: WorldEntityContext | None,
) -> tuple[WorldEntityMapTarget, ...]:
    """Return only locations the canonical world projection already marks navigable.

    Provider candidate/ambiguous/unresolved locations stay in Knowledge detail as
    evidence, but cannot cross this boundary into a Map action.
    """
    if context is None:
        return ()

    result: list[WorldEntityMapTarget] = []
    seen: set[tuple[int, bool]] = set()
    for related, rows in (
        (False, context.navigable_locations),
        (True, context.navigable_related_locations),
    ):
        for row in rows:
            if (
                row.gameplay_zone_entity_id is None
                or not row.gameplay_zone_name
                or row.x is None
                or row.y is None
            ):
                continue
            key = (int(row.location_id), related)
            if key in seen:
                continue
            seen.add(key)

            relation = (
                "Location"
                if row.relation == "self"
                else _OUT_LABELS.get(row.relation, row.relation.replace("_", " ").title())
            )
            label = row.label.strip() or relation
            if related:
                label = f"{relation}: {row.entity_name}" + (
                    f" — {row.label}" if row.label else ""
                )
            result.append(
                WorldEntityMapTarget(
                    location_id=int(row.location_id),
                    entity_id=int(row.entity_id),
                    entity_name=str(row.entity_name),
                    relation=str(row.relation),
                    zone_entity_id=int(row.gameplay_zone_entity_id),
                    zone_name=str(row.gameplay_zone_name),
                    x=float(row.x),
                    y=float(row.y),
                    z=(float(row.z) if row.z is not None else None),
                    label=label,
                    source_label=row.source_label,
                    related=related,
                )
            )
    return tuple(result)


def _populate_world_location_tree(app, targets: tuple[WorldEntityMapTarget, ...]) -> None:
    app._world_entity_target_by_item = {}
    tree = getattr(app, "world_entity_location_tree", None)
    if tree is None:
        return
    try:
        children = tree.get_children("")
        if children:
            tree.delete(*children)
    except Exception:
        return

    for index, target in enumerate(targets):
        iid = f"worldloc:{target.location_id}:{int(target.related)}:{index}"
        try:
            tree.insert(
                "",
                "end",
                iid=iid,
                text=target.label,
                values=(
                    target.zone_name,
                    target.loc_text,
                    "Actor" if target.related else "Entity",
                    target.source_label,
                ),
            )
            app._world_entity_target_by_item[iid] = target
        except Exception:
            continue

    status = getattr(app, "world_entity_location_status", None)
    if status is None:
        return
    try:
        if targets:
            status.set(
                f"{len(targets)} map-ready location(s). Only canonical/linked zones "
                "with explicit X/Y are actionable."
            )
        else:
            status.set(
                "No map-ready location. Candidate/unresolved provider locations remain "
                "visible as evidence in the Knowledge detail."
            )
    except Exception:
        pass


def selected_world_entity_map_target(app) -> WorldEntityMapTarget | None:
    tree = getattr(app, "world_entity_location_tree", None)
    if tree is None:
        return None
    try:
        selected = tree.selection()
    except Exception:
        return None
    if not selected:
        return None
    return getattr(app, "_world_entity_target_by_item", {}).get(selected[0])


def map_selected_world_entity_location(app) -> bool:
    """Delegate one safe game-space target to the existing runtime Map owner."""
    target = selected_world_entity_map_target(app)
    status = getattr(app, "world_entity_location_status", None)
    if target is None:
        if status is not None:
            try:
                status.set("Select a map-ready location first.")
            except Exception:
                pass
        return False

    handoff = getattr(app, "_focus_navigation_map_target", None)
    if not callable(handoff):
        if status is not None:
            try:
                status.set("Map target handoff is unavailable in this application mode.")
            except Exception:
                pass
        return False

    handoff(target.zone_name, target.x, target.y, target.z, target.label)
    return True


def install_world_entity_context_ui() -> None:
    """Add map-ready world locations below the final canonical Knowledge detail."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _WORLD_ENTITY_UI_MARKER, False):
        return

    class WorldEntityContextUIApp(current_app):
        def _build_knowledge(self) -> None:
            super()._build_knowledge()
            import tkinter as tk
            from tkinter import ttk

            parent = self.entity_text.master
            parent.rowconfigure(1, weight=0)
            frame = ttk.LabelFrame(parent, text="Map-ready world locations", padding=6)
            frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            frame.columnconfigure(0, weight=1)

            self.world_entity_location_tree = ttk.Treeview(
                frame,
                columns=("zone", "loc", "kind", "source"),
                show="tree headings",
                height=5,
                selectmode="browse",
            )
            self.world_entity_location_tree.heading("#0", text="Location")
            self.world_entity_location_tree.heading("zone", text="Zone")
            self.world_entity_location_tree.heading("loc", text="EQ /loc")
            self.world_entity_location_tree.heading("kind", text="Kind")
            self.world_entity_location_tree.heading("source", text="Source")
            self.world_entity_location_tree.column("#0", width=250, minwidth=140, stretch=True)
            self.world_entity_location_tree.column("zone", width=160, minwidth=100, stretch=True)
            self.world_entity_location_tree.column("loc", width=170, minwidth=120, stretch=False)
            self.world_entity_location_tree.column("kind", width=70, minwidth=60, stretch=False)
            self.world_entity_location_tree.column("source", width=170, minwidth=100, stretch=True)
            self.world_entity_location_tree.grid(row=0, column=0, sticky="ew")
            scroll = ttk.Scrollbar(
                frame, orient="vertical", command=self.world_entity_location_tree.yview
            )
            scroll.grid(row=0, column=1, sticky="ns")
            self.world_entity_location_tree.configure(yscrollcommand=scroll.set)
            self.world_entity_location_tree.bind(
                "<Double-1>", lambda _event: self._map_selected_world_entity_location()
            )

            controls = ttk.Frame(frame)
            controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
            ttk.Button(
                controls,
                text="Map selected location",
                command=self._map_selected_world_entity_location,
            ).pack(side="left")
            self.world_entity_location_status = tk.StringVar(
                value="Select an NPC, quest, or item to inspect map-ready world locations."
            )
            ttk.Label(
                controls,
                textvariable=self.world_entity_location_status,
                justify="left",
                wraplength=650,
            ).pack(side="left", padx=(8, 0), fill="x", expand=True)
            self._world_entity_target_by_item: dict[str, WorldEntityMapTarget] = {}

        def _show_entity(self) -> None:
            # #43 owns the canonical ID-based world detail renderer. This layer only
            # derives the safe actionable subset for the location picker.
            super()._show_entity()
            entity_id = self._selected_entity_id()
            if entity_id is None:
                _populate_world_location_tree(self, ())
                return
            context = build_world_entity_context_for_id(self.db, entity_id)
            if context is None or context.kind not in _WORLD_KINDS:
                _populate_world_location_tree(self, ())
                return
            _populate_world_location_tree(self, world_entity_map_targets(context))

        def _map_selected_world_entity_location(self) -> bool:
            return map_selected_world_entity_location(self)

    setattr(WorldEntityContextUIApp, _WORLD_ENTITY_UI_MARKER, True)
    app_module.EverQuestieApp = WorldEntityContextUIApp
