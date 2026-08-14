from __future__ import annotations

from tkinter import ttk

from .local_map_readiness import local_map_readiness_text
from .route_guidance import (
    RouteGuidanceResult,
    build_route_guidance,
    next_hop_for_zone,
    route_guidance_text,
)
from .travel import TravelFrame
from .zone_actionability import build_zone_actionability, zone_actionability_text


class RouteGuidanceFrame(TravelFrame):
    """Packaged Travel frame with cached source-safe next-hop map guidance."""

    def __init__(self, *args, **kwargs):
        self._route_guidance: RouteGuidanceResult | None = None
        self.get_map_readiness = kwargs.pop("get_map_readiness", None)
        super().__init__(*args, **kwargs)

    def _build(self) -> None:
        super()._build()
        route_actions = ttk.Frame(self)
        route_actions.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(
            route_actions,
            text="Map next hop",
            command=self.map_next_hop,
        ).pack(side="left")
        ttk.Label(
            route_actions,
            text="Uses confirmed route evidence; player /loc is not required.",
        ).pack(side="left", padx=(8, 0))

    def _local_readiness(self, zone: str):
        if self.get_map_readiness is None:
            return None
        try:
            return self.get_map_readiness(zone)
        except Exception:
            # Local filesystem readiness is supplemental. Never turn a transient local
            # resource check into a failure of canonical knowledge/navigation views.
            return None

    def show_zone_context(self) -> None:
        """Render canonical zone knowledge plus source-safe route map actionability."""
        self._clear_nearby_points()
        zone = self._selected_or_current_zone()
        if not zone:
            self.status_var.set("Choose a zone or wait for the current zone from the log.")
            return

        view, status = build_zone_actionability(self.db, zone, location_limit=50)
        text = zone_actionability_text(self.db, zone, location_limit=50)
        readiness = self._local_readiness(zone)
        if readiness is not None:
            text += "\n\nLocal map readiness:\n  " + local_map_readiness_text(readiness)
        self._set_result(text)
        if view is not None:
            context = view.context
            local_status = ""
            if readiness is not None:
                local_status = (
                    " | local map ready"
                    if readiness.ready
                    else f" | local map {readiness.status.replace('_', ' ')}"
                )
            self.status_var.set(
                f"Canonical zone context loaded: {context.identity.name} | "
                f"{len(context.maps)} map binding(s) | "
                f"{view.usable_route_directions} usable route direction(s) | "
                f"{view.mappable_route_directions} mappable exit(s) | "
                f"{context.entity_count} located entity/entities{local_status}."
            )
        elif status == "ambiguous":
            self.status_var.set("Zone identity is ambiguous; EverQuestie will not guess.")
        else:
            self.status_var.set("No canonical zone identity is present in shipped knowledge yet.")

    def find_route(self) -> None:
        self._clear_nearby_points()
        source = self.from_var.get().strip()
        target = self.to_var.get().strip()
        if not source:
            self.use_current_zone()
            source = self.from_var.get().strip()
        if not source or not target:
            self._route_guidance = None
            self.status_var.set("Choose both a start zone and destination.")
            return

        guidance = build_route_guidance(self.db, source, target)
        self._route_guidance = guidance if guidance.ok else None
        self._set_result(route_guidance_text(self.db, guidance))
        self.status_var.set(
            "Confirmed canonical route found. Map next hop follows the live zone along this cached route."
            if guidance.ok
            else "No confirmed canonical route is currently available."
        )

    def map_next_hop(self) -> None:
        guidance = self._route_guidance
        if guidance is None or not guidance.ok:
            self.status_var.set("Find a confirmed route before mapping its next hop.")
            return

        live_zone = self._live_current_zone()
        if not live_zone:
            self.status_var.set("Current zone is unknown; next-hop map guidance needs the live zone.")
            return

        hop, status = next_hop_for_zone(self.db, guidance, live_zone)
        if status == "arrived":
            self.status_var.set("Route destination reached; there is no next hop to map.")
            return
        if status == "off_route":
            self.status_var.set(
                "The live zone is not on the cached route. Recompute the route from the current zone."
            )
            return
        if status == "zone_ambiguous":
            self.status_var.set("Current zone identity is ambiguous; EverQuestie will not guess a route hop.")
            return
        if status != "linked" or hop is None:
            self.status_var.set("The live current zone could not be resolved against the cached route.")
            return

        coordinate = hop.source_coordinate
        if coordinate is None:
            if hop.stored_x is not None and hop.stored_y is not None:
                self.status_var.set(
                    f"Next hop is {hop.source_name} → {hop.target_name}, but the stored coordinate belongs "
                    f"to {hop.coordinate_owner_name}. EverQuestie will not map that opposite-side coordinate."
                )
            else:
                self.status_var.set(
                    f"Next hop is {hop.source_name} → {hop.target_name}, but no confirmed source-zone "
                    "coordinate is present for map targeting."
                )
            return

        readiness = self._local_readiness(hop.source_name)
        if readiness is not None and not readiness.ready:
            self.status_var.set(
                f"Next hop coordinate is confirmed for {hop.source_name}, but "
                f"{local_map_readiness_text(readiness)}"
            )
            return

        if self.on_map_target is None:
            self.status_var.set("Map targeting is not connected in this application surface.")
            return

        x, y, z = coordinate
        self.on_map_target(hop.source_name, x, y, z, hop.map_label)
        local_suffix = (
            f" | local map: {readiness.path.name}"
            if readiness is not None and readiness.ready and readiness.path is not None
            else ""
        )
        self.status_var.set(
            f"Map next hop: {hop.map_label} | source: {hop.evidence_source}{local_suffix}. "
            "The Map tab owns local map selection, coordinate conversion and rendering."
        )
