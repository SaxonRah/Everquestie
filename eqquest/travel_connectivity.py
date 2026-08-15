from __future__ import annotations

from dataclasses import dataclass
from collections import deque

from .db import Database


@dataclass(frozen=True, slots=True)
class TravelConnectivityDiagnostic:
    source_entity_id: int
    target_entity_id: int
    directed_reachable_count: int
    weak_component_count: int
    source_outgoing_count: int
    target_incoming_count: int
    target_in_directed_reachable_set: bool
    target_in_weak_component: bool


def _table_exists(db: Database, name: str) -> bool:
    return db.conn.execute(
        """
        SELECT 1 FROM sqlite_temp_master
        WHERE type IN ('table','view') AND name=?
        UNION ALL
        SELECT 1 FROM sqlite_master
        WHERE type IN ('table','view') AND name=?
        LIMIT 1
        """,
        (name, name),
    ).fetchone() is not None


def _linked_adjacency(db: Database):
    directed: dict[int, set[int]] = {}
    undirected: dict[int, set[int]] = {}
    incoming: dict[int, set[int]] = {}
    if not _table_exists(db, "zone_travel_edges"):
        return directed, undirected, incoming

    rows = db.conn.execute(
        """
        SELECT source_zone_entity_id,target_zone_entity_id,bidirectional
        FROM zone_travel_edges
        WHERE status='linked' AND target_zone_entity_id IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        source = int(row["source_zone_entity_id"])
        target = int(row["target_zone_entity_id"])
        directed.setdefault(source, set()).add(target)
        incoming.setdefault(target, set()).add(source)
        undirected.setdefault(source, set()).add(target)
        undirected.setdefault(target, set()).add(source)
        if bool(row["bidirectional"]):
            directed.setdefault(target, set()).add(source)
            incoming.setdefault(source, set()).add(target)
    return directed, undirected, incoming


def _reachable(adjacency: dict[int, set[int]], source: int) -> set[int]:
    seen = {int(source)}
    queue = deque([int(source)])
    while queue:
        current = queue.popleft()
        for nxt in adjacency.get(current, set()):
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append(nxt)
    return seen


def travel_connectivity_diagnostic(
    db: Database,
    source_entity_id: int,
    target_entity_id: int,
) -> TravelConnectivityDiagnostic:
    source = int(source_entity_id)
    target = int(target_entity_id)
    directed, undirected, incoming = _linked_adjacency(db)
    reachable = _reachable(directed, source)
    weak = _reachable(undirected, source)
    return TravelConnectivityDiagnostic(
        source_entity_id=source,
        target_entity_id=target,
        directed_reachable_count=max(0, len(reachable) - 1),
        weak_component_count=max(0, len(weak) - 1),
        source_outgoing_count=len(directed.get(source, set())),
        target_incoming_count=len(incoming.get(target, set())),
        target_in_directed_reachable_set=target in reachable,
        target_in_weak_component=target in weak,
    )


def travel_connectivity_text(
    db: Database,
    source_entity_id: int,
    target_entity_id: int,
) -> str:
    """Explain why a confirmed long route is unavailable without inventing edges."""
    diagnostic = travel_connectivity_diagnostic(db, source_entity_id, target_entity_id)
    source = db.entity(diagnostic.source_entity_id)
    target = db.entity(diagnostic.target_entity_id)
    source_name = (
        str(source["name"])
        if source is not None
        else f"zone {diagnostic.source_entity_id}"
    )
    target_name = (
        str(target["name"])
        if target is not None
        else f"zone {diagnostic.target_entity_id}"
    )

    if diagnostic.target_in_directed_reachable_set:
        return (
            f"{target_name} is reachable in the confirmed directed travel graph from {source_name}, "
            "but the normal shortest-path query did not return it. Because normal routing has no default hop "
            "ceiling, this indicates that the catalog changed between reads or that an internal route/catalog "
            "consistency problem needs investigation."
        )

    if diagnostic.target_in_weak_component:
        return (
            f"{source_name} and {target_name} are in the same connected evidence component, but confirmed edge "
            "directionality currently blocks travel in this direction. EverQuestie will not assume a reverse zone "
            "connection without explicit two-way or reciprocal evidence."
        )

    return (
        f"{target_name} is outside {source_name}'s confirmed travel-graph component. "
        f"From {source_name}, {diagnostic.directed_reachable_count} other zone(s) are currently reachable; "
        f"its undirected evidence component contains {diagnostic.weak_component_count} other zone(s). "
        f"The source has {diagnostic.source_outgoing_count} confirmed outgoing edge(s), and the destination has "
        f"{diagnostic.target_incoming_count} confirmed incoming edge(s). A missing canonical zone binding or an "
        "uncompiled map/provider connection somewhere between the components must be filled before a far route can exist."
    )
