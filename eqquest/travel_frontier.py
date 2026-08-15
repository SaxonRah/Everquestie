from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Any

from .zone_authority import prefer_eqclient_zone_resolution
from .zone_identity import ZoneIdentityIndex
from .zone_travel import ZoneTravelCatalog


# Explicit map-author syntax that is not currently compiled by ZoneTravelCatalog.
# Keep this list intentionally narrower than the compiler. When a frontier spelling
# graduates into the production parser it must be removed here so the audit never
# reports already-supported syntax as backlog.
_FRONTIER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "zone_line",
        re.compile(
            r"^(?:zone\s*connection|zone\s*boundary)\s*(?:(?:to|:|-|=)\s*)?(.+)$",
            re.I,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class TravelFrontierExample:
    source_name: str
    source_key: str
    map_stem: str
    source_zone: str
    label: str
    category: str
    connection_kind: str
    destination: str
    resolution_status: str
    target_zone: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_key": self.source_key,
            "map_stem": self.map_stem,
            "source_zone": self.source_zone,
            "label": self.label,
            "category": self.category,
            "connection_kind": self.connection_kind,
            "destination": self.destination,
            "resolution_status": self.resolution_status,
            "target_zone": self.target_zone,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class TravelFrontierSummary:
    map_labels_total: int
    labels_on_linked_zone_maps: int
    stored_map_travel_rows: int
    current_explicit_candidates: int
    current_explicit_linked: int
    current_explicit_ambiguous: int
    current_explicit_unresolved: int
    current_explicit_missing_stored_edge: int
    current_explicit_status_drift: int
    frontier_explicit: int
    frontier_explicit_linked: int
    frontier_explicit_ambiguous: int
    frontier_explicit_unresolved: int
    frontier_bare_zone_labels: int
    source_frontier_counts: tuple[tuple[str, int], ...]
    unresolved_destinations: tuple[tuple[str, int], ...]
    examples: tuple[TravelFrontierExample, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "map_labels_total": self.map_labels_total,
            "labels_on_linked_zone_maps": self.labels_on_linked_zone_maps,
            "stored_map_travel_rows": self.stored_map_travel_rows,
            "current_explicit_candidates": self.current_explicit_candidates,
            "current_explicit_linked": self.current_explicit_linked,
            "current_explicit_ambiguous": self.current_explicit_ambiguous,
            "current_explicit_unresolved": self.current_explicit_unresolved,
            "current_explicit_missing_stored_edge": self.current_explicit_missing_stored_edge,
            "current_explicit_status_drift": self.current_explicit_status_drift,
            "frontier_explicit": self.frontier_explicit,
            "frontier_explicit_linked": self.frontier_explicit_linked,
            "frontier_explicit_ambiguous": self.frontier_explicit_ambiguous,
            "frontier_explicit_unresolved": self.frontier_explicit_unresolved,
            "frontier_bare_zone_labels": self.frontier_bare_zone_labels,
            "source_frontier_counts": [
                {"source_name": source_name, "count": count}
                for source_name, count in self.source_frontier_counts
            ],
            "unresolved_destinations": [
                {"destination": destination, "count": count}
                for destination, count in self.unresolved_destinations
            ],
            "examples": [example.as_dict() for example in self.examples],
        }


class TravelFrontierAudit:
    """Read-only audit of travel evidence that is stored but not fully usable yet.

    The existing travel compiler remains the source of truth. This projection measures
    three useful boundaries without mutating knowledge:

    * current explicit syntax that the compiler already understands, including whether
      the stored ``zone_travel_edges`` row is missing/stale;
    * additional explicit travel spellings that are safe-looking candidates for a
      future parser expansion (currently ``Zone Connection`` / ``Zone Boundary``);
    * bare labels that exactly resolve to another canonical zone. Bare names are never
      auto-promoted here because they may be landmarks rather than exits.

    Frontier patterns are intentionally removed when the production compiler learns
    them. This keeps the audit a backlog measurement rather than a duplicate parser.
    """

    def __init__(self, db):
        self.db = db

    def _object_exists(self, name: str) -> bool:
        return self.db.conn.execute(
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

    @staticmethod
    def _frontier_candidate(label: str) -> tuple[str, str] | None:
        text = ZoneTravelCatalog._human_text(label)
        if not text:
            return None
        for kind, pattern in _FRONTIER_PATTERNS:
            match = pattern.match(text)
            if not match:
                continue
            destination = ZoneTravelCatalog._human_text(match.group(1))
            if destination:
                return kind, destination
        return None

    @staticmethod
    def _resolve(
        destination: str,
        source_zone_entity_id: int,
        identities: ZoneIdentityIndex,
    ) -> tuple[int | None, str, str, str]:
        resolved = identities.resolve(destination)
        resolved = prefer_eqclient_zone_resolution(resolved, destination)
        if resolved.status == "unresolved":
            return None, "unresolved", "", "no exact canonical zone identity"
        if resolved.status == "ambiguous":
            return (
                None,
                "ambiguous",
                "",
                f"matches {len(resolved.candidates)} canonical zones",
            )
        target_id = resolved.entity_id
        if target_id is None:
            return None, "unresolved", "", "no exact canonical zone identity"
        if int(target_id) == int(source_zone_entity_id):
            return None, "same_zone", resolved.zone_name, "resolves back to source zone"
        return int(target_id), "linked", resolved.zone_name, "exact canonical zone identity"

    def summary(self, *, example_limit: int = 60) -> TravelFrontierSummary:
        if not self._object_exists("map_labels") or not self._object_exists("map_sources"):
            return TravelFrontierSummary(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, (), (), ())

        map_labels_total = int(
            self.db.conn.execute("SELECT COUNT(*) AS n FROM map_labels").fetchone()["n"]
        )
        if not self._object_exists("zone_map_bindings"):
            return TravelFrontierSummary(
                map_labels_total, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, (), (), ()
            )

        rows = self.db.conn.execute(
            """
            SELECT ml.id AS label_id,ml.raw_text,ml.clean_text,
                   ms.source_name,ms.source_key,ms.map_stem,
                   zmb.zone_entity_id AS source_zone_entity_id,
                   zmb.zone_name AS source_zone_name
            FROM map_labels ml
            JOIN map_sources ms ON ms.id=ml.source_id
            JOIN zone_map_bindings zmb
              ON zmb.source_name=ms.source_name AND zmb.map_stem=ms.map_stem
            WHERE zmb.status='linked' AND zmb.zone_entity_id IS NOT NULL
            ORDER BY ms.source_name,ms.source_key,ml.source_line,ml.id
            """
        ).fetchall()

        stored_by_label: dict[int, tuple[str, int | None]] = {}
        stored_rows = 0
        if self._object_exists("zone_travel_edges"):
            edge_rows = self.db.conn.execute(
                """
                SELECT label_id,status,target_zone_entity_id
                FROM zone_travel_edges
                WHERE source_kind='map_label' AND label_id IS NOT NULL
                ORDER BY id
                """
            ).fetchall()
            stored_rows = len(edge_rows)
            for edge in edge_rows:
                stored_by_label[int(edge["label_id"])] = (
                    str(edge["status"] or ""),
                    int(edge["target_zone_entity_id"])
                    if edge["target_zone_entity_id"] is not None
                    else None,
                )

        identities = ZoneIdentityIndex(self.db, include_map_bindings=True)
        current = Counter()
        frontier = Counter()
        source_counts: Counter[str] = Counter()
        unresolved: Counter[str] = Counter()
        missing = 0
        drift = 0
        bare = 0
        examples: list[TravelFrontierExample] = []

        def add_example(
            row,
            *,
            category: str,
            kind: str,
            destination: str,
            status: str,
            target_zone: str,
            reason: str,
        ) -> None:
            if len(examples) >= max(0, int(example_limit)):
                return
            examples.append(
                TravelFrontierExample(
                    source_name=str(row["source_name"] or ""),
                    source_key=str(row["source_key"] or ""),
                    map_stem=str(row["map_stem"] or ""),
                    source_zone=str(row["source_zone_name"] or ""),
                    label=ZoneTravelCatalog._human_text(
                        str(row["raw_text"] or row["clean_text"] or "")
                    ),
                    category=category,
                    connection_kind=kind,
                    destination=destination,
                    resolution_status=status,
                    target_zone=target_zone,
                    reason=reason,
                )
            )

        for row in rows:
            label_id = int(row["label_id"])
            label = str(row["raw_text"] or row["clean_text"] or "")
            source_zone_id = int(row["source_zone_entity_id"])
            compiled_candidate = ZoneTravelCatalog._travel_candidate(label)
            if compiled_candidate is not None:
                kind, destination = compiled_candidate
                target_id, status, target_name, reason = self._resolve(
                    destination, source_zone_id, identities
                )
                current["total"] += 1
                current[status] += 1
                if status == "unresolved":
                    unresolved[destination] += 1
                stored = stored_by_label.get(label_id)
                if stored is None:
                    missing += 1
                elif stored != ("linked" if status == "linked" else status, target_id):
                    drift += 1
                continue

            frontier_candidate = self._frontier_candidate(label)
            if frontier_candidate is not None:
                kind, destination = frontier_candidate
                _target_id, status, target_name, reason = self._resolve(
                    destination, source_zone_id, identities
                )
                frontier["total"] += 1
                frontier[status] += 1
                source_counts[str(row["source_name"] or "")] += 1
                if status == "unresolved":
                    unresolved[destination] += 1
                add_example(
                    row,
                    category="unsupported_explicit",
                    kind=kind,
                    destination=destination,
                    status=status,
                    target_zone=target_name,
                    reason=reason,
                )
                continue

            text = ZoneTravelCatalog._human_text(label)
            if not text:
                continue
            _target_id, status, target_name, reason = self._resolve(
                text, source_zone_id, identities
            )
            if status != "linked":
                continue
            bare += 1
            source_counts[str(row["source_name"] or "")] += 1
            add_example(
                row,
                category="bare_zone_label",
                kind="unknown",
                destination=text,
                status=status,
                target_zone=target_name,
                reason=(
                    reason
                    + "; audit only because a bare zone name may be a landmark rather than an exit"
                ),
            )

        return TravelFrontierSummary(
            map_labels_total=map_labels_total,
            labels_on_linked_zone_maps=len(rows),
            stored_map_travel_rows=stored_rows,
            current_explicit_candidates=int(current["total"]),
            current_explicit_linked=int(current["linked"]),
            current_explicit_ambiguous=int(current["ambiguous"]),
            current_explicit_unresolved=int(current["unresolved"] + current["same_zone"]),
            current_explicit_missing_stored_edge=missing,
            current_explicit_status_drift=drift,
            frontier_explicit=int(frontier["total"]),
            frontier_explicit_linked=int(frontier["linked"]),
            frontier_explicit_ambiguous=int(frontier["ambiguous"]),
            frontier_explicit_unresolved=int(frontier["unresolved"] + frontier["same_zone"]),
            frontier_bare_zone_labels=bare,
            source_frontier_counts=tuple(
                sorted(source_counts.items(), key=lambda item: (-item[1], item[0].casefold()))
            ),
            unresolved_destinations=tuple(
                sorted(unresolved.items(), key=lambda item: (-item[1], item[0].casefold()))
            ),
            examples=tuple(examples),
        )


def travel_frontier_audit_text(db, *, example_limit: int = 30) -> str:
    summary = TravelFrontierAudit(db).summary(example_limit=example_limit)
    lines = [
        "EverQuestie travel frontier audit",
        "",
        "Read-only projection over stored map/catalog knowledge; no map folders are scanned.",
        "",
        f"Map labels stored: {summary.map_labels_total:,}",
        f"Labels on linked canonical zone maps: {summary.labels_on_linked_zone_maps:,}",
        f"Stored map-label travel rows: {summary.stored_map_travel_rows:,}",
        "",
        "Current compiler:",
        f"  explicit candidates: {summary.current_explicit_candidates:,}",
        f"  linked / ambiguous / unresolved: {summary.current_explicit_linked:,} / "
        f"{summary.current_explicit_ambiguous:,} / {summary.current_explicit_unresolved:,}",
        f"  explicit candidates missing stored edge: {summary.current_explicit_missing_stored_edge:,}",
        f"  stored edge status/target drift: {summary.current_explicit_status_drift:,}",
        "",
        "Frontier not currently auto-compiled:",
        f"  additional explicit travel spellings: {summary.frontier_explicit:,}",
        f"    currently resolvable / ambiguous / unresolved: {summary.frontier_explicit_linked:,} / "
        f"{summary.frontier_explicit_ambiguous:,} / {summary.frontier_explicit_unresolved:,}",
        f"  bare labels that exactly name another canonical zone: {summary.frontier_bare_zone_labels:,}",
    ]

    if summary.source_frontier_counts:
        lines += ["", "Frontier by map source:"]
        for source_name, count in summary.source_frontier_counts[:20]:
            lines.append(f"  {source_name or '(unnamed)'}: {count:,}")

    if summary.unresolved_destinations:
        lines += ["", "Top unresolved explicit destinations:"]
        for destination, count in summary.unresolved_destinations[:20]:
            lines.append(f"  {destination}: {count:,}")

    if summary.examples:
        lines += ["", f"Frontier examples (up to {example_limit}):"]
        for example in summary.examples:
            target = f" -> {example.target_zone}" if example.target_zone else ""
            lines.append(
                f"  [{example.category}] {example.source_name} | {example.map_stem} | "
                f"{example.label} | {example.resolution_status}{target}"
            )

    return "\n".join(lines)
