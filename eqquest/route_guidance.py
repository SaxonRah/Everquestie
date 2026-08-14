from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .travel import TravelRouteResult, build_route_result
from .zone_identity import resolve_zone


@dataclass(frozen=True, slots=True)
class RouteHopGuidance:
    source_entity_id: int
    target_entity_id: int
    source_name: str
    target_name: str
    connection_kind: str
    bidirectional: bool
    uses_reverse_evidence: bool
    evidence_source: str
    evidence: str
    coordinate_owner_entity_id: int | None
    coordinate_owner_name: str
    stored_x: float | None
    stored_y: float | None
    stored_z: float | None

    @property
    def source_coordinate(self) -> tuple[float, float, float | None] | None:
        if self.coordinate_owner_entity_id != self.source_entity_id:
            return None
        if self.stored_x is None or self.stored_y is None:
            return None
        return self.stored_x, self.stored_y, self.stored_z

    @property
    def map_label(self) -> str:
        kind = self.connection_kind.replace("_", " ").strip() or "travel"
        return f"{kind} to {self.target_name}"


@dataclass(frozen=True, slots=True)
class RouteGuidanceResult:
    route: TravelRouteResult
    hops: tuple[RouteHopGuidance, ...]

    @property
    def ok(self) -> bool:
        return self.route.ok


def _best_guidance_edge_for_hop(db: Database, source_id: int, target_id: int):
    """Choose deterministic hop evidence without hiding an actionable direct coordinate.

    Direction ownership is the primary invariant: any direct source→target evidence
    outranks reverse use of a bidirectional target→source row. Within the same
    direction rank, prefer a row with X/Y so route guidance agrees with release
    coverage's definition of a mappable source-side direction.
    """
    return db.conn.execute(
        """
        SELECT *,
               CASE WHEN source_zone_entity_id=? AND target_zone_entity_id=?
                    THEN 0 ELSE 1 END AS reverse_rank,
               CASE WHEN x IS NOT NULL AND y IS NOT NULL THEN 0 ELSE 1 END AS coordinate_rank
        FROM zone_travel_edges
        WHERE status='linked' AND target_zone_entity_id IS NOT NULL
          AND (
              (source_zone_entity_id=? AND target_zone_entity_id=?)
              OR
              (bidirectional=1 AND source_zone_entity_id=? AND target_zone_entity_id=?)
          )
        ORDER BY reverse_rank,coordinate_rank,source_kind,source_name,source_key,id
        LIMIT 1
        """,
        (source_id, target_id, source_id, target_id, target_id, source_id),
    ).fetchone()


def _hop_from_edge(db: Database, source_id: int, target_id: int) -> RouteHopGuidance:
    source = db.entity(source_id)
    target = db.entity(target_id)
    edge = _best_guidance_edge_for_hop(db, source_id, target_id)
    source_name = str(source["name"]) if source is not None else f"zone {source_id}"
    target_name = str(target["name"]) if target is not None else f"zone {target_id}"
    if edge is None:
        return RouteHopGuidance(
            source_entity_id=source_id,
            target_entity_id=target_id,
            source_name=source_name,
            target_name=target_name,
            connection_kind="travel",
            bidirectional=False,
            uses_reverse_evidence=False,
            evidence_source="EverQuestie knowledge",
            evidence="",
            coordinate_owner_entity_id=None,
            coordinate_owner_name="",
            stored_x=None,
            stored_y=None,
            stored_z=None,
        )

    owner_id = int(edge["source_zone_entity_id"])
    owner = db.entity(owner_id)
    return RouteHopGuidance(
        source_entity_id=source_id,
        target_entity_id=target_id,
        source_name=source_name,
        target_name=target_name,
        connection_kind=str(edge["connection_kind"] or "travel"),
        bidirectional=bool(edge["bidirectional"]),
        uses_reverse_evidence=bool(int(edge["reverse_rank"])),
        evidence_source=str(
            edge["source_name"] or edge["source_kind"] or "EverQuestie knowledge"
        ),
        evidence=str(edge["evidence"] or "").strip(),
        coordinate_owner_entity_id=owner_id,
        coordinate_owner_name=(str(owner["name"]) if owner is not None else f"zone {owner_id}"),
        stored_x=(float(edge["x"]) if edge["x"] is not None else None),
        stored_y=(float(edge["y"]) if edge["y"] is not None else None),
        stored_z=(float(edge["z"]) if edge["z"] is not None else None),
    )


def build_route_guidance(
    db: Database,
    source_text: str,
    target_text: str,
) -> RouteGuidanceResult:
    route = build_route_result(db, source_text, target_text)
    if not route.ok or len(route.path) < 2:
        return RouteGuidanceResult(route=route, hops=())
    hops = tuple(
        _hop_from_edge(db, source_id, target_id)
        for source_id, target_id in zip(route.path, route.path[1:])
    )
    return RouteGuidanceResult(route=route, hops=hops)


def next_hop_for_zone(
    db: Database,
    guidance: RouteGuidanceResult,
    zone_token: str,
) -> tuple[RouteHopGuidance | None, str]:
    if not guidance.route.ok:
        return None, "no_route"
    text = " ".join(str(zone_token or "").split()).strip()
    if not text:
        return None, "zone_unknown"
    resolution = resolve_zone(db, text)
    if resolution.identity is None:
        return None, "zone_ambiguous" if resolution.status == "ambiguous" else "zone_unknown"
    zone_id = resolution.identity.entity_id
    if guidance.route.target_entity_id == zone_id:
        return None, "arrived"
    for hop in guidance.hops:
        if hop.source_entity_id == zone_id:
            return hop, "linked"
    return None, "off_route"


def route_guidance_text(db: Database, guidance: RouteGuidanceResult) -> str:
    if not guidance.route.ok or not guidance.hops:
        return guidance.route.text

    first = guidance.hops[0]
    last = guidance.hops[-1]
    lines = [
        f"Route: {first.source_name} → {last.target_name}",
        f"Confirmed hops: {len(guidance.hops)}",
        "",
    ]
    for index, hop in enumerate(guidance.hops, start=1):
        direction = "two-way evidence" if hop.bidirectional else "directed evidence"
        lines.append(f"{index}. {hop.source_name} → {hop.target_name}")
        lines.append(
            f"   {hop.connection_kind.replace('_', ' ')} | {direction} | source: {hop.evidence_source}"
        )
        if hop.evidence:
            lines.append(f"   evidence: {hop.evidence}")
        if hop.stored_x is not None and hop.stored_y is not None:
            z = float(hop.stored_z or 0.0)
            if hop.coordinate_owner_entity_id == hop.source_entity_id:
                lines.append(
                    f"   source-zone /loc: {hop.stored_y:.1f}, {hop.stored_x:.1f}, {z:.1f}"
                )
            else:
                lines.append(
                    f"   stored /loc belongs to {hop.coordinate_owner_name}; "
                    "no source-zone coordinate is known for this route direction"
                )
        else:
            lines.append("   no source-zone coordinate is present for map targeting")
        if hop.uses_reverse_evidence:
            lines.append("   using the reverse direction of explicitly two-way evidence")
        lines.append("")
    return "\n".join(lines).rstrip()
