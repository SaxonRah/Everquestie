from __future__ import annotations

from datetime import datetime
from typing import Callable

from .db import normalize_name
from .map_catalog import MapCatalog


ProgressCallback = Callable[[str, int, int, str], None]


def _candidate_index(catalog: MapCatalog) -> dict[str, dict[int, object]]:
    """Load exact entity/alias candidates for all map-label terms in two set queries.

    The historic reconciler issued one SELECT with a LEFT JOIN + OR predicate for
    every map label. Full Good/Brewall catalogs contain tens of thousands of labels,
    so that turned a deterministic builder step into tens of thousands of tiny SQL
    queries. Build the same exact candidate relation once and keep only the entity
    fields the conservative zone disambiguator actually needs.
    """
    result: dict[str, dict[int, object]] = {}

    for row in catalog.db.conn.execute(
        """
        WITH label_terms AS (
            SELECT DISTINCT normalized_text
            FROM map_labels
            WHERE normalized_text<>''
        )
        SELECT lt.normalized_text AS lookup_text,
               e.id,e.kind,e.name,e.zone
        FROM label_terms lt
        JOIN entities e ON e.normalized_name=lt.normalized_text
        ORDER BY lt.normalized_text,e.kind,e.name,e.id
        """
    ).fetchall():
        key = str(row["lookup_text"] or "")
        result.setdefault(key, {})[int(row["id"])] = row

    for row in catalog.db.conn.execute(
        """
        WITH label_terms AS (
            SELECT DISTINCT normalized_text
            FROM map_labels
            WHERE normalized_text<>''
        )
        SELECT lt.normalized_text AS lookup_text,
               e.id,e.kind,e.name,e.zone
        FROM label_terms lt
        JOIN entity_aliases a ON a.normalized_alias=lt.normalized_text
        JOIN entities e ON e.id=a.entity_id
        ORDER BY lt.normalized_text,e.kind,e.name,e.id
        """
    ).fetchall():
        key = str(row["lookup_text"] or "")
        result.setdefault(key, {})[int(row["id"])] = row

    return result


def fast_reconcile_all(
    self: MapCatalog,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
    chunk_size: int = 1000,
) -> dict[str, int]:
    """Reconcile map labels with set-based candidate loading and grouped updates.

    Identity policy is intentionally identical to MapCatalog's original reconciler:
    only exact cleaned entity names/aliases are candidates, with current-zone evidence
    used solely to disambiguate multiple exact candidates. The optimization is purely
    computational: candidate rows are loaded once, repeated (text, zone) labels are
    resolved once, and SQLite updates are batched by group instead of by label.
    """
    if not force and self.db.get_meta("map_links_dirty", "1") != "1":
        row = self.db.conn.execute(
            """
            SELECT SUM(link_status='linked'),
                   SUM(link_status='ambiguous'),
                   SUM(link_status='unresolved')
            FROM map_labels
            """
        ).fetchone()
        return {
            "linked": int(row[0] or 0),
            "ambiguous": int(row[1] or 0),
            "unresolved": int(row[2] or 0),
        }

    groups = self.db.conn.execute(
        """
        SELECT normalized_text,zone_name,COUNT(*) AS label_count
        FROM map_labels
        GROUP BY normalized_text,zone_name
        ORDER BY normalized_text,zone_name
        """
    ).fetchall()
    total = sum(int(row["label_count"] or 0) for row in groups)
    if progress:
        progress(
            "reconcile",
            0,
            max(1, total),
            f"Reconciling {total:,} map labels in {len(groups):,} unique label/zone groups",
        )

    candidates_by_text = _candidate_index(self)
    location_by_zone: dict[str, set[int]] = {}
    linked = ambiguous = unresolved = 0
    pending: list[tuple[int | None, str, str, str, str]] = []
    pending_labels = 0
    processed = 0
    chunk_size = max(50, int(chunk_size))

    def flush() -> None:
        nonlocal pending_labels
        if not pending:
            return
        with self.db.batch():
            self.db.conn.executemany(
                """
                UPDATE map_labels
                SET linked_entity_id=?,link_status=?,link_reason=?
                WHERE normalized_text=? AND zone_name=?
                """,
                pending,
            )
        pending.clear()
        pending_labels = 0

    for group_index, group in enumerate(groups, start=1):
        normalized = str(group["normalized_text"] or "")
        zone_name = str(group["zone_name"] or "")
        label_count = int(group["label_count"] or 0)
        candidate_map = candidates_by_text.get(normalized, {}) if normalized else {}
        candidates = list(candidate_map.values())
        chosen = None
        reason = ""
        status = "unresolved"

        if len(candidates) == 1:
            chosen = candidates[0]
            status = "linked"
            reason = "exact cleaned name/alias; unique local entity"
        elif len(candidates) > 1:
            if zone_name:
                key = normalize_name(zone_name)
                if key not in location_by_zone:
                    location_by_zone[key] = {
                        int(row["entity_id"])
                        for row in self.db.locations_in_zone(zone_name)
                    }
                zone_ids = location_by_zone[key]
                narrowed = [
                    row
                    for row in candidates
                    if self._entity_zone_matches(row, zone_name, zone_ids)
                ]
                if len(narrowed) == 1:
                    chosen = narrowed[0]
                    status = "linked"
                    reason = "exact cleaned name/alias; unique current-zone entity"
                else:
                    status = "ambiguous"
                    reason = f"{len(narrowed) or len(candidates)} exact entity candidates"
            else:
                status = "ambiguous"
                reason = f"{len(candidates)} exact entity candidates"

        entity_id = int(chosen["id"]) if chosen is not None else None
        pending.append((entity_id, status, reason, normalized, zone_name))
        pending_labels += label_count
        processed += label_count

        if status == "linked":
            linked += label_count
        elif status == "ambiguous":
            ambiguous += label_count
        else:
            unresolved += label_count

        if len(pending) >= chunk_size:
            flush()
            if progress:
                progress(
                    "reconcile",
                    processed,
                    max(1, total),
                    f"Reconciled {processed:,}/{total:,} labels "
                    f"({group_index:,}/{len(groups):,} unique groups)",
                )

    flush()
    with self.db.batch():
        self.db.set_meta("map_links_dirty", "0")
        self.db.set_meta(
            "map_links_last_reconcile",
            datetime.now().isoformat(timespec="seconds"),
        )
    if progress:
        progress(
            "reconcile",
            max(1, total),
            max(1, total),
            f"Reconciled {total:,} labels in {len(groups):,} unique groups",
        )
    return {"linked": linked, "ambiguous": ambiguous, "unresolved": unresolved}


def install_map_reconcile_acceleration() -> None:
    """Install the builder/runtime-compatible fast reconciler exactly once."""
    current = MapCatalog.reconcile_all
    if getattr(current, "_everquestie_fast_map_reconcile", False):
        return
    fast_reconcile_all._everquestie_fast_map_reconcile = True  # type: ignore[attr-defined]
    MapCatalog.reconcile_all = fast_reconcile_all  # type: ignore[method-assign]
