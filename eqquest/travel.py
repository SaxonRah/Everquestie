from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk

from .db import Database
from .nearby import nearby_points, nearby_text
from .zone_context import build_zone_context, zone_context_text
from .zone_identity import resolve_zone
from .zone_travel import ZoneTravelCatalog


@dataclass(frozen=True, slots=True)
class TravelRouteResult:
    ok: bool
    source_entity_id: int | None
    target_entity_id: int | None
    path: tuple[int, ...]
    text: str


def _resolve_zone(db: Database, value: str):
    text = " ".join((value or "").split()).strip()
    if not text:
        return None, "empty"
    resolution = resolve_zone(db, text)
    if resolution.identity is None:
        return None, resolution.status
    row = db.entity(resolution.identity.entity_id)
    return row, resolution.match_kind


def _best_edge_for_hop(db: Database, source_id: int, target_id: int):
    """Return one deterministic evidence row for a route hop.

    Direct evidence is preferred. A reverse row is eligible only when that source
    explicitly marked the connection bidirectional.
    """
    return db.conn.execute(
        """
        SELECT *,
               CASE WHEN source_zone_entity_id=? AND target_zone_entity_id=?
                    THEN 0 ELSE 1 END AS reverse_rank
        FROM zone_travel_edges
        WHERE status='linked' AND target_zone_entity_id IS NOT NULL
          AND (
              (source_zone_entity_id=? AND target_zone_entity_id=?)
              OR
              (bidirectional=1 AND source_zone_entity_id=? AND target_zone_entity_id=?)
          )
        ORDER BY reverse_rank,source_kind,source_name,source_key,id
        LIMIT 1
        """,
        (source_id, target_id, source_id, target_id, target_id, source_id),
    ).fetchone()


def build_route_result(db: Database, source_text: str, target_text: str) -> TravelRouteResult:
    """Resolve canonical zones and format a read-only route from shipped topology."""
    source, source_status = _resolve_zone(db, source_text)
    if source is None:
        detail = "is ambiguous" if source_status == "ambiguous" else "was not found"
        return TravelRouteResult(
            False,
            None,
            None,
            (),
            f"Start zone {source_text!r} {detail} in the local EverQuestie knowledge DB.",
        )

    target, target_status = _resolve_zone(db, target_text)
    if target is None:
        detail = "is ambiguous" if target_status == "ambiguous" else "was not found"
        return TravelRouteResult(
            False,
            int(source["id"]),
            None,
            (),
            f"Destination zone {target_text!r} {detail} in the local EverQuestie knowledge DB.",
        )

    source_id = int(source["id"])
    target_id = int(target["id"])
    path = tuple(ZoneTravelCatalog(db).shortest_path(source_id, target_id))
    if not path:
        return TravelRouteResult(
            False,
            source_id,
            target_id,
            (),
            (
                f"No confirmed route is currently present from {source['name']} to {target['name']}.\n\n"
                "EverQuestie only routes across linked canonical travel evidence; ambiguous or unresolved "
                "map/provider candidates are not guessed."
            ),
        )

    if len(path) == 1:
        return TravelRouteResult(
            True,
            source_id,
            target_id,
            path,
            f"Already in {source['name']}.",
        )

    entities = {entity_id: db.entity(entity_id) for entity_id in path}
    lines = [
        f"Route: {entities[path[0]]['name']} → {entities[path[-1]]['name']}",
        f"Confirmed hops: {len(path) - 1}",
        "",
    ]
    for index, (a, b) in enumerate(zip(path, path[1:]), start=1):
        a_row = entities[a]
        b_row = entities[b]
        edge = _best_edge_for_hop(db, a, b)
        lines.append(f"{index}. {a_row['name']} → {b_row['name']}")
        if edge is None:
            continue
        kind = str(edge["connection_kind"] or "travel").replace("_", " ")
        source_name = str(edge["source_name"] or edge["source_kind"] or "EverQuestie knowledge")
        direction = "two-way" if bool(edge["bidirectional"]) else "directed"
        lines.append(f"   {kind} | {direction} | source: {source_name}")
        evidence = str(edge["evidence"] or "").strip()
        if evidence:
            lines.append(f"   evidence: {evidence}")
        if edge["x"] is not None and edge["y"] is not None:
            z = float(edge["z"] or 0.0)
            lines.append(
                f"   source-zone /loc: {float(edge['y']):.1f}, {float(edge['x']):.1f}, {z:.1f}"
            )
        if int(edge["reverse_rank"]):
            lines.append("   using the reverse direction of explicitly two-way evidence")
        lines.append("")

    return TravelRouteResult(True, source_id, target_id, path, "\n".join(lines).rstrip())


class TravelFrame(ttk.Frame):
    """Read-only navigation UI over finalized canonical zone knowledge."""

    def __init__(
        self,
        master,
        *,
        db: Database,
        get_zone,
        get_location=None,
        on_map_target=None,
    ):
        super().__init__(master, padding=8)
        self.db = db
        self.get_zone = get_zone
        self.get_location = get_location or (lambda: None)
        self.on_map_target = on_map_target
        self.from_var = tk.StringVar()
        self.to_var = tk.StringVar()
        self.status_var = tk.StringVar(
            value=(
                "Routes, zone overviews and nearby points use shipped canonical knowledge; "
                "no map parsing or network access occurs here."
            )
        )
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        controls = ttk.LabelFrame(self, text="Zone navigation", padding=10)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="From").grid(row=0, column=0, sticky="w")
        from_entry = ttk.Entry(controls, textvariable=self.from_var)
        from_entry.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(controls, text="Use current zone", command=self.use_current_zone).grid(
            row=0, column=2
        )
        ttk.Button(controls, text="Show zone", command=self.show_zone_context).grid(
            row=0, column=3, padx=(6, 0)
        )
        ttk.Button(controls, text="Nearby", command=self.show_nearby).grid(
            row=0, column=4, padx=(6, 0)
        )
        ttk.Button(controls, text="Map nearest", command=self.map_nearest).grid(
            row=0, column=5, padx=(6, 0)
        )

        ttk.Label(controls, text="To").grid(row=1, column=0, sticky="w", pady=(8, 0))
        to_entry = ttk.Entry(controls, textvariable=self.to_var)
        to_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(controls, text="Find route", command=self.find_route).grid(
            row=1, column=2, columnspan=4, sticky="ew", pady=(8, 0)
        )
        from_entry.bind("<Return>", lambda _e: self.show_zone_context())
        to_entry.bind("<Return>", lambda _e: self.find_route())

        ttk.Label(self, textvariable=self.status_var, wraplength=1000, justify="left").grid(
            row=1, column=0, sticky="ew", pady=(8, 6)
        )

        frame = ttk.LabelFrame(self, text="Canonical navigation knowledge", padding=6)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.result_text = tk.Text(frame, wrap="word", state="disabled")
        self.result_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.result_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.result_text.configure(yscrollcommand=scroll.set)

    def _set_result(self, text: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("end", text)
        self.result_text.configure(state="disabled")

    def use_current_zone(self) -> None:
        zone = " ".join(str(self.get_zone() or "").split()).strip()
        if zone:
            self.from_var.set(zone)
            self.status_var.set(f"Start zone set to current zone: {zone}")
        else:
            self.status_var.set("Current zone is not known yet.")

    def _selected_or_current_zone(self) -> str:
        zone = self.from_var.get().strip()
        if not zone:
            self.use_current_zone()
            zone = self.from_var.get().strip()
        return zone

    def _live_current_zone(self) -> str:
        """Zone paired with the ephemeral SessionState.last_location callback."""
        return " ".join(str(self.get_zone() or "").split()).strip()

    @staticmethod
    def _nearby_map_label(point) -> str:
        if point.point_type == "travel":
            return f"Travel to {point.name}"
        return f"{point.name} [{point.kind}]"

    def show_zone_context(self) -> None:
        zone = self._selected_or_current_zone()
        if not zone:
            self.status_var.set("Choose a zone or wait for the current zone from the log.")
            return

        context, status = build_zone_context(self.db, zone, location_limit=50)
        self._set_result(zone_context_text(self.db, zone, location_limit=50))
        if context is not None:
            self.status_var.set(
                f"Canonical zone context loaded: {context.identity.name} | "
                f"{len(context.maps)} map binding(s) | "
                f"{len(context.usable_connections)} usable connection(s) | "
                f"{context.entity_count} located entity/entities."
            )
        elif status == "ambiguous":
            self.status_var.set("Zone identity is ambiguous; EverQuestie will not guess.")
        else:
            self.status_var.set("No canonical zone identity is present in shipped knowledge yet.")

    def show_nearby(self) -> None:
        # Nearby geometry is meaningful only in the zone that owns the observed /loc.
        # Route/overview fields may intentionally contain some other zone, so never use
        # the editable From token to pair coordinates with knowledge.
        zone = self._live_current_zone()
        if not zone:
            self.status_var.set("Current zone is unknown; nearby ranking requires the live current zone.")
            return
        location = self.get_location()
        self._set_result(nearby_text(self.db, zone, location, limit=50))
        points, status = nearby_points(self.db, zone, location, limit=50)
        if status == "location_unknown":
            self.status_var.set(
                "Current /loc is unknown. Use /loc in EverQuest; the observed coordinate is never written into shipped knowledge."
            )
        elif status == "ambiguous":
            self.status_var.set("Current zone identity is ambiguous; EverQuestie will not rank nearby points by guessing.")
        elif status != "linked":
            self.status_var.set("No canonical identity for the live current zone is present in shipped knowledge yet.")
        else:
            travel_count = sum(point.point_type == "travel" for point in points)
            entity_count = len(points) - travel_count
            self.status_var.set(
                f"Nearby in {zone}: {len(points)} confirmed point(s) | "
                f"{entity_count} entity location(s) | {travel_count} usable travel point(s). "
                "Straight-line X/Y only; ΔZ is shown separately."
            )

    def map_nearest(self) -> None:
        """Send the nearest confirmed live-zone point to the Map owner in game space."""
        zone = self._live_current_zone()
        if not zone:
            self.status_var.set("Current zone is unknown; map targeting requires the live current zone.")
            return
        location = self.get_location()
        points, status = nearby_points(self.db, zone, location, limit=1)
        if status == "location_unknown":
            self.status_var.set("Current /loc is unknown; there is no safe nearest point to map yet.")
            return
        if status != "linked" or not points:
            self.status_var.set("No confirmed coordinate-bearing nearby point is available to map.")
            return
        if self.on_map_target is None:
            self.status_var.set("Map targeting is not connected in this application surface.")
            return

        point = points[0]
        label = self._nearby_map_label(point)
        self.on_map_target(zone, point.x, point.y, point.z, label)
        self.status_var.set(
            f"Map target: {label} | {point.distance_text}. "
            "The Map tab owns local map selection, coordinate conversion and rendering."
        )

    def find_route(self) -> None:
        source = self.from_var.get().strip()
        target = self.to_var.get().strip()
        if not source:
            self.use_current_zone()
            source = self.from_var.get().strip()
        if not source or not target:
            self.status_var.set("Choose both a start zone and destination.")
            return
        result = build_route_result(self.db, source, target)
        self._set_result(result.text)
        self.status_var.set(
            "Confirmed canonical route found."
            if result.ok
            else "No confirmed canonical route is currently available."
        )
