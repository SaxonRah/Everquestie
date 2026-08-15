from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from .travel_connectivity import TravelConnectivityDiagnostic, travel_connectivity_diagnostic
from .zone_authority import prefer_eqclient_zone_resolution
from .zone_identity import ZoneIdentityIndex, ZoneResolution
from .zone_travel import ZoneTravelCatalog


# Deliberately difficult cross-world queries that are useful when auditing a real
# finalized knowledge snapshot. They are acceptance questions, not hard-coded travel
# facts: unresolved endpoints or missing topology are reported rather than invented.
# Keep these as literal real EverQuest client zone display names. Synthetic zones used
# by route stress tests belong in tests only and must never leak into this real-data audit.
DEFAULT_ROUTE_ACCEPTANCE_CASES: tuple[tuple[str, str], ...] = (
    ("The Hole", "Labyrinth of Spite"),
    ("Paineel", "The Hole"),
    ("Stonebrunt Mountains", "Paineel"),
    ("Greater Faydark", "The Hole"),
    ("Stone Hive", "North Freeport"),
)

_ACCEPTED_STATUSES = {"reachable", "same_zone"}


@dataclass(frozen=True, slots=True)
class RouteEndpointResolution:
    query: str
    status: str
    match_kind: str
    reason: str
    entity_id: int | None
    canonical_name: str
    candidates: tuple[tuple[int, str], ...] = ()

    @property
    def linked(self) -> bool:
        return self.status == "linked" and self.entity_id is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "status": self.status,
            "match_kind": self.match_kind,
            "reason": self.reason,
            "entity_id": self.entity_id,
            "canonical_name": self.canonical_name,
            "candidates": [
                {"entity_id": entity_id, "name": name}
                for entity_id, name in self.candidates
            ],
        }


@dataclass(frozen=True, slots=True)
class RouteAcceptanceResult:
    source: RouteEndpointResolution
    target: RouteEndpointResolution
    status: str
    reason: str
    path_entity_ids: tuple[int, ...] = ()
    path_zone_names: tuple[str, ...] = ()
    diagnostic: TravelConnectivityDiagnostic | None = None

    @property
    def ok(self) -> bool:
        return self.status in _ACCEPTED_STATUSES

    @property
    def hop_count(self) -> int:
        return max(0, len(self.path_entity_ids) - 1)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source.as_dict(),
            "target": self.target.as_dict(),
            "status": self.status,
            "ok": self.ok,
            "reason": self.reason,
            "hop_count": self.hop_count,
            "path_entity_ids": list(self.path_entity_ids),
            "path_zone_names": list(self.path_zone_names),
        }
        if self.diagnostic is not None:
            payload["diagnostic"] = {
                "source_entity_id": self.diagnostic.source_entity_id,
                "target_entity_id": self.diagnostic.target_entity_id,
                "directed_reachable_count": self.diagnostic.directed_reachable_count,
                "weak_component_count": self.diagnostic.weak_component_count,
                "source_outgoing_count": self.diagnostic.source_outgoing_count,
                "target_incoming_count": self.diagnostic.target_incoming_count,
                "target_in_directed_reachable_set": (
                    self.diagnostic.target_in_directed_reachable_set
                ),
                "target_in_weak_component": self.diagnostic.target_in_weak_component,
            }
        return payload


@dataclass(frozen=True, slots=True)
class RouteAcceptanceSummary:
    results: tuple[RouteAcceptanceResult, ...]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def accepted(self) -> int:
        return sum(result.ok for result in self.results)

    @property
    def failed(self) -> int:
        return self.total - self.accepted

    @property
    def status_counts(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(result.status for result in self.results)
        return tuple(sorted(counts.items()))

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "accepted": self.accepted,
            "failed": self.failed,
            "status_counts": dict(self.status_counts),
            "results": [result.as_dict() for result in self.results],
        }


def _endpoint_resolution(
    index: ZoneIdentityIndex,
    query: str,
) -> RouteEndpointResolution:
    text = " ".join(str(query or "").split()).strip()
    resolution: ZoneResolution = index.resolve(text)
    resolution = prefer_eqclient_zone_resolution(resolution, text)
    identity = resolution.identity
    return RouteEndpointResolution(
        query=text,
        status=resolution.status,
        match_kind=resolution.match_kind,
        reason=resolution.reason,
        entity_id=(identity.entity_id if identity is not None else None),
        canonical_name=(identity.name if identity is not None else ""),
        candidates=tuple(
            (candidate.entity_id, candidate.name)
            for candidate in resolution.candidates
        ),
    )


def _zone_names(db) -> dict[int, str]:
    return {
        int(row["id"]): str(row["name"])
        for row in db.conn.execute(
            "SELECT id,name FROM entities WHERE kind='zone' ORDER BY id"
        ).fetchall()
    }


def _identity_failure(
    source: RouteEndpointResolution,
    target: RouteEndpointResolution,
) -> RouteAcceptanceResult | None:
    if not source.linked:
        status = "source_ambiguous" if source.status == "ambiguous" else "source_unresolved"
        return RouteAcceptanceResult(
            source=source,
            target=target,
            status=status,
            reason=(
                f"Start zone {source.query!r} does not resolve to one authoritative canonical zone: "
                f"{source.reason}."
            ),
        )
    if not target.linked:
        status = "target_ambiguous" if target.status == "ambiguous" else "target_unresolved"
        return RouteAcceptanceResult(
            source=source,
            target=target,
            status=status,
            reason=(
                f"Destination zone {target.query!r} does not resolve to one authoritative canonical zone: "
                f"{target.reason}."
            ),
        )
    return None


def evaluate_route_acceptance(
    db,
    cases: Iterable[tuple[str, str]] | None = None,
) -> RouteAcceptanceSummary:
    """Evaluate exact source→destination route questions against stored knowledge.

    This is a read-only acceptance projection. It deliberately reuses EverQuestie's
    canonical zone identity policy, confirmed travel graph, and directionality rules.
    A failed case records the coverage class that must be fixed; it never promotes an
    ambiguous provider candidate, invents a reciprocal edge, or applies a hop limit.
    """
    requested = tuple(cases if cases is not None else DEFAULT_ROUTE_ACCEPTANCE_CASES)
    index = ZoneIdentityIndex(db, include_map_bindings=True)
    catalog = ZoneTravelCatalog(db)
    names = _zone_names(db)
    results: list[RouteAcceptanceResult] = []

    for raw_source, raw_target in requested:
        source = _endpoint_resolution(index, raw_source)
        target = _endpoint_resolution(index, raw_target)
        failure = _identity_failure(source, target)
        if failure is not None:
            results.append(failure)
            continue

        source_id = int(source.entity_id)
        target_id = int(target.entity_id)
        if source_id == target_id:
            name = source.canonical_name or names.get(source_id, source.query)
            results.append(
                RouteAcceptanceResult(
                    source=source,
                    target=target,
                    status="same_zone",
                    reason=f"Both queries resolve to the same canonical zone, {name}.",
                    path_entity_ids=(source_id,),
                    path_zone_names=(name,),
                )
            )
            continue

        path = tuple(catalog.shortest_path(source_id, target_id))
        if path:
            path_names = tuple(names.get(entity_id, f"zone {entity_id}") for entity_id in path)
            results.append(
                RouteAcceptanceResult(
                    source=source,
                    target=target,
                    status="reachable",
                    reason=(
                        f"Confirmed directed route found in {len(path) - 1} hop(s); "
                        "normal routing has no default hop ceiling."
                    ),
                    path_entity_ids=path,
                    path_zone_names=path_names,
                )
            )
            continue

        diagnostic = travel_connectivity_diagnostic(db, source_id, target_id)
        if diagnostic.target_in_directed_reachable_set:
            status = "route_inconsistency"
            reason = (
                "The connectivity traversal can reach the destination but the normal shortest-path query "
                "returned no route. This is a route/catalog consistency defect, not a coverage gap."
            )
        elif diagnostic.target_in_weak_component:
            status = "directionality_blocked"
            reason = (
                "Source and destination are in the same weak evidence component, but confirmed directed "
                "edges do not permit travel in this direction. Reciprocal/two-way evidence is required."
            )
        else:
            status = "disconnected"
            reason = (
                "Destination is outside the source's confirmed travel component. A canonical binding or "
                "source-backed transition between components is still missing from compiled topology."
            )
        results.append(
            RouteAcceptanceResult(
                source=source,
                target=target,
                status=status,
                reason=reason,
                diagnostic=diagnostic,
            )
        )

    return RouteAcceptanceSummary(tuple(results))


def _path_text(names: tuple[str, ...], *, full_paths: bool, preview_nodes: int) -> str:
    if full_paths or len(names) <= max(2, preview_nodes):
        return " → ".join(names)
    keep = max(2, int(preview_nodes))
    front = max(1, keep * 2 // 3)
    back = max(1, keep - front)
    omitted = len(names) - front - back
    return " → ".join((*names[:front], f"… {omitted} zone(s) …", *names[-back:]))


def route_acceptance_text(
    summary: RouteAcceptanceSummary,
    *,
    full_paths: bool = False,
    preview_nodes: int = 14,
) -> str:
    lines = [
        "EverQuestie route acceptance audit",
        "",
        "Exact canonical identities + confirmed directed travel only; no provider guessing or reverse-edge inference.",
        f"Cases: {summary.total}",
        f"Accepted: {summary.accepted}",
        f"Failed: {summary.failed}",
    ]
    if summary.status_counts:
        lines.append(
            "Status: " + ", ".join(f"{status}={count}" for status, count in summary.status_counts)
        )

    for index, result in enumerate(summary.results, start=1):
        marker = "PASS" if result.ok else "FAIL"
        source_name = result.source.canonical_name or result.source.query or "(empty)"
        target_name = result.target.canonical_name or result.target.query or "(empty)"
        lines += [
            "",
            f"{index}. [{marker} {result.status}] {source_name} → {target_name}",
            f"   {result.reason}",
        ]
        if result.path_zone_names:
            lines.append(
                f"   path ({result.hop_count} hop(s)): "
                + _path_text(
                    result.path_zone_names,
                    full_paths=full_paths,
                    preview_nodes=preview_nodes,
                )
            )
        for label, endpoint in (("source", result.source), ("target", result.target)):
            if endpoint.linked:
                continue
            if endpoint.candidates:
                choices = ", ".join(
                    f"{name} [id {entity_id}]" for entity_id, name in endpoint.candidates
                )
                lines.append(f"   {label} candidates: {choices}")
        if result.diagnostic is not None:
            diagnostic = result.diagnostic
            lines.append(
                "   topology: "
                f"reachable={diagnostic.directed_reachable_count}, "
                f"weak_component={diagnostic.weak_component_count}, "
                f"source_outgoing={diagnostic.source_outgoing_count}, "
                f"target_incoming={diagnostic.target_incoming_count}"
            )

    return "\n".join(lines)
