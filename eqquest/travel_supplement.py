from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .zone_authority import prefer_eqclient_zone_resolution
from .zone_identity import ZoneIdentityIndex
from .zone_travel import ZoneTravelCatalog


TRAVEL_SUPPLEMENT_SOURCE_KIND = "curated_travel_manifest"
TRAVEL_SUPPLEMENT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class TravelSupplementBuildStats:
    source_name: str
    source_version: str
    edges: int
    bidirectional_edges: int
    requirements: int


@dataclass(frozen=True, slots=True)
class _ResolvedEdge:
    source_zone_entity_id: int
    target_zone_entity_id: int
    connection_kind: str
    bidirectional: bool
    source_key: str
    evidence: str
    source_url: str
    requirements: tuple[Any, ...]


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


class TravelSupplementImporter:
    """Compile explicit, source-backed travel evidence into canonical travel edges.

    This is builder-only infrastructure for transitions that are not represented by
    an ordinary structured provider surface. Runtime never reads the manifest; it
    consumes only finalized ``zone_travel_edges`` rows.

    The importer deliberately reuses EverQuestie's authoritative zone identity policy.
    It never creates zones or aliases, performs fuzzy matching, infers reverse travel,
    or adds topology merely to satisfy a route-acceptance case.
    """

    def __init__(self, db):
        if not getattr(db, "knowledge_writable", True):
            raise RuntimeError("travel supplement import is builder-only")
        self.db = db

    @staticmethod
    def _load(path: str | Path) -> dict[str, Any]:
        manifest_path = Path(path).expanduser().resolve()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("travel supplement manifest root must be a JSON object")
        return payload

    @staticmethod
    def _resolve_zone(index: ZoneIdentityIndex, query: str, *, field: str) -> int:
        resolution = prefer_eqclient_zone_resolution(index.resolve(query), query)
        if resolution.status == "ambiguous":
            raise ValueError(
                f"{field} {query!r} matches {len(resolution.candidates)} canonical zones"
            )
        if resolution.status != "linked" or resolution.entity_id is None:
            raise ValueError(
                f"{field} {query!r} has no authoritative canonical zone identity"
            )
        return int(resolution.entity_id)

    def _validated_edges(
        self,
        payload: dict[str, Any],
    ) -> tuple[str, str, str, tuple[_ResolvedEdge, ...]]:
        schema_version = payload.get("schema_version", TRAVEL_SUPPLEMENT_SCHEMA_VERSION)
        if schema_version != TRAVEL_SUPPLEMENT_SCHEMA_VERSION:
            raise ValueError(
                "unsupported travel supplement schema_version "
                f"{schema_version!r}; expected {TRAVEL_SUPPLEMENT_SCHEMA_VERSION}"
            )

        source_name = _clean(payload.get("source_name"))
        source_version = _clean(payload.get("source_version"))
        default_source_url = _clean(payload.get("source_url"))
        if not source_name:
            raise ValueError("travel supplement requires non-empty source_name")
        if not source_version:
            raise ValueError("travel supplement requires non-empty source_version")

        raw_edges = payload.get("edges")
        if not isinstance(raw_edges, list):
            raise ValueError("travel supplement requires an edges array")
        if not raw_edges:
            raise ValueError("travel supplement requires at least one edge")

        index = ZoneIdentityIndex(self.db, include_map_bindings=True)
        seen_keys: set[str] = set()
        resolved: list[_ResolvedEdge] = []
        for position, raw in enumerate(raw_edges, start=1):
            if not isinstance(raw, dict):
                raise ValueError(
                    f"travel supplement edge {position} must be a JSON object"
                )

            source_query = _clean(raw.get("source"))
            target_query = _clean(raw.get("target"))
            source_key = _clean(raw.get("source_key"))
            evidence = _clean(raw.get("evidence"))
            if not source_query or not target_query:
                raise ValueError(
                    f"travel supplement edge {position} requires source and target"
                )
            if not source_key:
                raise ValueError(
                    f"travel supplement edge {position} requires source_key"
                )
            if not evidence:
                raise ValueError(
                    f"travel supplement edge {position} requires explicit evidence"
                )
            if source_key in seen_keys:
                raise ValueError(
                    f"duplicate travel supplement source_key: {source_key}"
                )
            seen_keys.add(source_key)

            source_id = self._resolve_zone(
                index,
                source_query,
                field=f"edge {position} source",
            )
            target_id = self._resolve_zone(
                index,
                target_query,
                field=f"edge {position} target",
            )
            if source_id == target_id:
                raise ValueError(
                    f"travel supplement edge {position} resolves source and target "
                    "to the same canonical zone"
                )

            raw_bidirectional = raw.get("bidirectional", False)
            if not isinstance(raw_bidirectional, bool):
                raise ValueError(
                    f"travel supplement edge {position} bidirectional must be boolean"
                )

            requirements = raw.get(
                "travel_requirements",
                raw.get("requirements", []),
            )
            if requirements is None:
                requirements = []
            if not isinstance(requirements, list):
                raise ValueError(
                    f"travel supplement edge {position} travel_requirements "
                    "must be an array"
                )
            if any(not isinstance(value, (str, dict)) for value in requirements):
                raise ValueError(
                    f"travel supplement edge {position} travel_requirements "
                    "must contain only strings or objects"
                )

            resolved.append(
                _ResolvedEdge(
                    source_zone_entity_id=source_id,
                    target_zone_entity_id=target_id,
                    connection_kind=_clean(raw.get("connection_kind")) or "travel",
                    bidirectional=raw_bidirectional,
                    source_key=source_key,
                    evidence=evidence,
                    source_url=_clean(raw.get("source_url")) or default_source_url,
                    requirements=tuple(requirements),
                )
            )

        return source_name, source_version, default_source_url, tuple(resolved)

    def import_manifest(
        self,
        path: str | Path,
    ) -> TravelSupplementBuildStats:
        payload = self._load(path)
        source_name, source_version, _default_source_url, edges = (
            self._validated_edges(payload)
        )
        catalog = ZoneTravelCatalog(self.db)

        # Validate the complete manifest before replacing any prior rows. A bad edit
        # therefore cannot destroy the last known-good compiled supplement.
        with self.db.batch():
            self.db.conn.execute(
                """
                DELETE FROM zone_travel_edges
                WHERE source_kind=? AND source_name=?
                """,
                (TRAVEL_SUPPLEMENT_SOURCE_KIND, source_name),
            )
            for edge in edges:
                data: dict[str, Any] = {
                    "manifest_schema_version": TRAVEL_SUPPLEMENT_SCHEMA_VERSION,
                    "manifest_source_key": edge.source_key,
                    "travel_requirements": list(edge.requirements),
                }
                if edge.source_url:
                    data["source_url"] = edge.source_url

                catalog.add_provider_connection(
                    edge.source_zone_entity_id,
                    edge.target_zone_entity_id,
                    connection_kind=edge.connection_kind,
                    bidirectional=edge.bidirectional,
                    source_name=source_name,
                    source_kind=TRAVEL_SUPPLEMENT_SOURCE_KIND,
                    source_key=edge.source_key,
                    source_version=source_version,
                    evidence=edge.evidence,
                    data=data,
                )

        return TravelSupplementBuildStats(
            source_name=source_name,
            source_version=source_version,
            edges=len(edges),
            bidirectional_edges=sum(edge.bidirectional for edge in edges),
            requirements=sum(len(edge.requirements) for edge in edges),
        )
