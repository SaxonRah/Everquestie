from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .db import Database, normalize_name
from .entity_lifecycle_records import lifecycle_records_for_entity
from .world_profiles import profile_expansion_allowed, world_profile


LIFECYCLE_FIELD_KEYS = ("expansion", "expansion_name", "era")

# Direct lifecycle truth is field/source-specific. A top-level key named ``expansion``
# is not sufficient by itself: the parser/source semantics must have been reviewed.
#
# The Allakhazam mirror importer currently owns these exact structured fields:
# - NPC/zone: explicit page ``Expansion``
# - item: explicit metadata-table ``Expansion``
# - quest: explicit quest-table ``Era``
#
# New cross-source evidence should prefer ``entity_lifecycle_records`` so adding one
# lifecycle fact never has to replace a canonical entity's primary source or detail row.
_REVIEWED_ENTITY_DATA_LIFECYCLE_FIELDS: dict[tuple[str, str, str], frozenset[str]] = {
    ("allakhazam", "local_mirror", "npc"): frozenset({"expansion"}),
    ("allakhazam", "local_mirror", "zone"): frozenset({"expansion"}),
    ("allakhazam", "local_mirror", "item"): frozenset({"expansion"}),
    ("allakhazam", "local_mirror", "quest"): frozenset({"era"}),
}
_REVIEWED_SOURCE_GRANULAR_LIFECYCLE_FIELDS: dict[
    tuple[str, str, str], frozenset[str]
] = {
    ("allakhazam", "local_mirror", "spell"): frozenset({"expansion"}),
}


@dataclass(frozen=True, slots=True)
class LifecycleFieldPolicyDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class EntityExpansionEvidence:
    entity_id: int
    entity_kind: str
    entity_name: str
    expansion: str
    source_name: str
    source_kind: str
    source_key: str
    source_page_id: int | None
    origin: str
    field_name: str = ""

    @property
    def source_label(self) -> str:
        label = self.source_name or self.source_kind or self.origin
        if self.source_key:
            label += f" [{self.source_key}]"
        return label


@dataclass(frozen=True, slots=True)
class EntityLifecycleDecision:
    entity_id: int
    entity_kind: str
    entity_name: str
    profile_id: str
    compatibility: bool | None
    status: str
    reason: str
    evidence: tuple[EntityExpansionEvidence, ...] = ()

    @property
    def definitive(self) -> bool:
        return self.compatibility is not None


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def lifecycle_field(data: dict[str, Any]) -> tuple[str, str] | None:
    """Return the first explicit top-level lifecycle field and normalized text."""
    for key in LIFECYCLE_FIELD_KEYS:
        value = data.get(key)
        if value is not None and str(value).strip():
            return key, " ".join(str(value).split())
    return None


def expansion_text(data: dict[str, Any]) -> str:
    """Backward-compatible text-only view of :func:`lifecycle_field`."""
    found = lifecycle_field(data)
    return found[1] if found is not None else ""


def lifecycle_field_policy(
    *,
    entity_kind: str,
    origin: str,
    field_name: str,
    source_name: str,
    source_kind: str,
    source_page_id: int | None,
) -> LifecycleFieldPolicyDecision:
    """Decide whether one lifecycle-looking field is direct profile evidence.

    Field presence is not evidence by itself. Direct lifecycle classification requires
    reviewed parser/source semantics. This function deliberately fails closed for
    unknown sources and for canonical detail JSON.

    In particular, ``mcp_local_details`` is mechanics/reference data. The locked MCP
    1.2.1 spell source has no direct spell expansion field, while its
    ``getClassSpellsByExpansion`` helper explicitly derives approximate eras from class
    level ranges. MCP detail keys must therefore never become direct lifecycle truth
    unless a future source/field combination is separately reviewed and added here.
    """
    kind = str(entity_kind or "").strip().casefold()
    origin_key = str(origin or "").strip()
    field = str(field_name or "").strip().casefold()
    source_name_key = str(source_name or "").strip().casefold()
    source_kind_key = str(source_kind or "").strip().casefold()

    if field not in LIFECYCLE_FIELD_KEYS:
        return LifecycleFieldPolicyDecision(False, "field is not a recognized lifecycle field")

    if origin_key == "entity.data_json":
        reviewed = _REVIEWED_ENTITY_DATA_LIFECYCLE_FIELDS.get(
            (source_name_key, source_kind_key, kind),
            frozenset(),
        )
        if field in reviewed:
            return LifecycleFieldPolicyDecision(
                True,
                "reviewed explicit lifecycle field from the Allakhazam local mirror",
            )
        if source_kind_key == "mcp_local_snapshot":
            return LifecycleFieldPolicyDecision(
                False,
                "MCP inventory data is identity/reference input, not reviewed lifecycle evidence",
            )
        if source_page_id is None:
            return LifecycleFieldPolicyDecision(
                False,
                "unattributed normalized entity data is not source-backed lifecycle evidence",
            )
        return LifecycleFieldPolicyDecision(
            False,
            "entity lifecycle field source/field semantics have not been reviewed",
        )

    if origin_key == "entity_lifecycle_records":
        reviewed = _REVIEWED_SOURCE_GRANULAR_LIFECYCLE_FIELDS.get(
            (source_name_key, source_kind_key, kind),
            frozenset(),
        )
        if field in reviewed:
            return LifecycleFieldPolicyDecision(
                True,
                "reviewed source-granular lifecycle field from the Allakhazam local mirror",
            )
        return LifecycleFieldPolicyDecision(
            False,
            "source-granular lifecycle field source/field semantics have not been reviewed",
        )

    if origin_key == "entity_details.detail_json":
        if source_kind_key == "mcp_local_details":
            return LifecycleFieldPolicyDecision(
                False,
                "MCP rich-detail lifecycle-looking fields are not reviewed direct lifecycle evidence",
            )
        return LifecycleFieldPolicyDecision(
            False,
            "canonical detail JSON requires an explicit reviewed lifecycle source policy",
        )

    return LifecycleFieldPolicyDecision(
        False,
        "lifecycle evidence origin has not been reviewed",
    )


def _source_fields(
    row,
    *,
    fallback_name: str,
    fallback_kind: str,
) -> tuple[str, str, str, int | None]:
    source_page_id = (
        int(row["source_page_id"])
        if row["source_page_id"] is not None
        else None
    )
    return (
        str(row["source_name"] or fallback_name),
        str(row["source_kind"] or fallback_kind),
        str(row["source_key"] or ""),
        source_page_id,
    )


def entity_expansion_evidence(
    db: Database,
    entity_id: int,
) -> tuple[EntityExpansionEvidence, ...]:
    """Read reviewed, explicit, source-backed expansion statements for an entity.

    The normalized database can contain lifecycle-looking fields on multiple surfaces.
    Only source/field/origin combinations accepted by :func:`lifecycle_field_policy`
    become direct gameplay-profile evidence.

    Text descriptions, locations, names, dates, IDs, nested metadata, and unreviewed
    detail fields are never promoted into lifecycle truth.
    """
    entity = db.entity(int(entity_id))
    if entity is None:
        return ()

    base = db.conn.execute(
        """
        SELECT e.id,e.kind,e.name,e.data_json,e.source_page_id,
               sp.source_name,sp.source_kind,sp.source_key
        FROM entities e
        LEFT JOIN source_pages sp ON sp.id=e.source_page_id
        WHERE e.id=?
        """,
        (int(entity_id),),
    ).fetchone()
    if base is None:
        return ()

    result: list[EntityExpansionEvidence] = []
    seen: set[tuple[str, str, int | None, str]] = set()

    def add_values(
        *,
        field_name: str,
        expansion: str,
        source_name: str,
        source_kind: str,
        source_key: str,
        source_page_id: int | None,
        origin: str,
    ) -> None:
        text = " ".join(str(expansion or "").split()).strip()
        if not text:
            return
        policy = lifecycle_field_policy(
            entity_kind=str(base["kind"] or ""),
            origin=origin,
            field_name=field_name,
            source_name=source_name,
            source_kind=source_kind,
            source_page_id=source_page_id,
        )
        if not policy.allowed:
            return
        key = (normalize_name(text), origin, source_page_id, field_name.casefold())
        if key in seen:
            return
        seen.add(key)
        result.append(
            EntityExpansionEvidence(
                entity_id=int(base["id"]),
                entity_kind=str(base["kind"] or ""),
                entity_name=str(base["name"] or ""),
                expansion=text,
                source_name=source_name,
                source_kind=source_kind,
                source_key=source_key,
                source_page_id=source_page_id,
                origin=origin,
                field_name=field_name,
            )
        )

    def add(
        field_name: str,
        expansion: str,
        row,
        origin: str,
        fallback_name: str,
        fallback_kind: str,
    ) -> None:
        source_name, source_kind, source_key, source_page_id = _source_fields(
            row,
            fallback_name=fallback_name,
            fallback_kind=fallback_kind,
        )
        add_values(
            field_name=field_name,
            expansion=expansion,
            source_name=source_name,
            source_kind=source_kind,
            source_key=source_key,
            source_page_id=source_page_id,
            origin=origin,
        )

    base_field = lifecycle_field(_json_object(base["data_json"]))
    if base_field is not None:
        add(
            base_field[0],
            base_field[1],
            base,
            "entity.data_json",
            "EverQuestie normalized entity",
            "entity_data",
        )

    # Source-granular records are the preferred surface for facts that enrich a
    # canonical entity owned by another source. They preserve the exact source page
    # without replacing the entity's primary source or its canonical rich-detail row.
    for record in lifecycle_records_for_entity(db, int(entity_id)):
        add_values(
            field_name=record.field_name,
            expansion=record.field_value,
            source_name=record.source_name,
            source_kind=record.source_kind,
            source_key=record.source_key,
            source_page_id=record.source_page_id,
            origin="entity_lifecycle_records",
        )

    # entity_details is a one-row canonical projection. Rich detail is retained for
    # display/search/mechanics, but lifecycle semantics remain independently governed
    # by the source policy above.
    try:
        detail = db.conn.execute(
            """
            SELECT d.detail_json,d.source_page_id,
                   sp.source_name,sp.source_kind,sp.source_key
            FROM entity_details d
            LEFT JOIN source_pages sp ON sp.id=d.source_page_id
            WHERE d.entity_id=?
            """,
            (int(entity_id),),
        ).fetchone()
    except Exception:
        detail = None
    if detail is not None:
        detail_field = lifecycle_field(_json_object(detail["detail_json"]))
        if detail_field is not None:
            add(
                detail_field[0],
                detail_field[1],
                detail,
                "entity_details.detail_json",
                "EverQuestie structured detail",
                "entity_detail",
            )

    return tuple(
        sorted(
            result,
            key=lambda item: (
                normalize_name(item.expansion),
                item.source_name.casefold(),
                item.origin,
                item.field_name,
            ),
        )
    )


def _post_cap_status(cap: str) -> str:
    token = str(cap or "cap").strip().casefold().replace("-", "_").replace(" ", "_")
    return f"post_{token}"


def entity_lifecycle_decision(
    db: Database,
    entity_id: int,
    profile_id: str,
) -> EntityLifecycleDecision:
    """Classify reviewed direct entity lifecycle evidence for one gameplay profile.

    Live does not currently use origin expansion alone as a retirement statement.
    Unrestricted accepts all compiled knowledge. Any profile configured with an
    ``expansion_cap`` can classify reviewed direct lifecycle evidence against that cap;
    the current P99 profile is simply the first such profile (Velious).
    """
    entity = db.entity(int(entity_id))
    kind = str(entity["kind"] or "") if entity is not None else ""
    name = str(entity["name"] or "") if entity is not None else f"entity {entity_id}"
    profile = world_profile(profile_id)
    evidence = entity_expansion_evidence(db, int(entity_id))

    if profile.availability_mode == "unrestricted":
        return EntityLifecycleDecision(
            int(entity_id),
            kind,
            name,
            profile.profile_id,
            True,
            "available",
            "unrestricted/custom profile retains all compiled knowledge",
            evidence,
        )

    if profile.availability_mode != "expansion_cap" or not profile.expansion_cap or not evidence:
        return EntityLifecycleDecision(
            int(entity_id),
            kind,
            name,
            profile.profile_id,
            None,
            "unknown",
            (
                "expansion evidence alone is not a Live retirement statement"
                if profile.availability_mode == "live" and evidence
                else "no reviewed direct entity expansion evidence is currently compiled"
            ),
            evidence,
        )

    cap_label = profile.expansion_cap_label or profile.expansion_cap
    classified = [
        profile_expansion_allowed(profile.profile_id, item.expansion)
        for item in evidence
    ]
    known = [value for value in classified if value is not None]
    if not known:
        return EntityLifecycleDecision(
            int(entity_id),
            kind,
            name,
            profile.profile_id,
            None,
            "unknown",
            "reviewed entity expansion evidence is present but not classifiable",
            evidence,
        )
    if any(value is True for value in known) and any(value is False for value in known):
        return EntityLifecycleDecision(
            int(entity_id),
            kind,
            name,
            profile.profile_id,
            None,
            "conflict",
            f"reviewed direct source expansion statements disagree across the {cap_label} boundary",
            evidence,
        )
    if all(value is True for value in known):
        return EntityLifecycleDecision(
            int(entity_id),
            kind,
            name,
            profile.profile_id,
            True,
            "available",
            f"reviewed direct entity expansion evidence places this content at or before {cap_label}",
            evidence,
        )
    return EntityLifecycleDecision(
        int(entity_id),
        kind,
        name,
        profile.profile_id,
        False,
        _post_cap_status(profile.expansion_cap),
        f"reviewed direct entity expansion evidence places this content after {cap_label}",
        evidence,
    )
