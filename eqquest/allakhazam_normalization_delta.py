from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol
import sqlite3

from .knowledge_coverage import provider_normalization_coverage


class DatabaseLike(Protocol):
    conn: sqlite3.Connection


STRUCTURED_KINDS = ("quest", "npc", "item", "zone", "spell")


@dataclass(frozen=True, slots=True)
class AllakhazamKindNormalizationDelta:
    kind: str
    captured_pages: int
    persisted_pages: int
    normalized_pages: int

    @property
    def captured_not_persisted(self) -> int:
        return max(0, self.captured_pages - self.persisted_pages)

    @property
    def persisted_not_in_capture(self) -> int:
        return max(0, self.persisted_pages - self.captured_pages)

    @property
    def persisted_not_normalized(self) -> int:
        return max(0, self.persisted_pages - self.normalized_pages)

    @property
    def persisted_fraction_of_capture(self) -> float | None:
        if not self.captured_pages:
            return None
        return self.persisted_pages / self.captured_pages

    @property
    def normalized_fraction_of_persisted(self) -> float | None:
        if not self.persisted_pages:
            return None
        return self.normalized_pages / self.persisted_pages

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "captured_pages": self.captured_pages,
            "persisted_pages": self.persisted_pages,
            "normalized_pages": self.normalized_pages,
            "captured_not_persisted": self.captured_not_persisted,
            "persisted_not_in_capture": self.persisted_not_in_capture,
            "persisted_not_normalized": self.persisted_not_normalized,
            "persisted_fraction_of_capture": self.persisted_fraction_of_capture,
            "normalized_fraction_of_persisted": self.normalized_fraction_of_persisted,
        }


@dataclass(frozen=True, slots=True)
class AllakhazamNormalizationDelta:
    mirror_importable_pages: int
    mirror_temporary_files: int
    mirror_read_errors: int
    mirror_spell_pages_with_expansion: int
    source_pages: int
    classified_pages: int
    normalized_pages: int
    entity_links: int
    primary_entity_links: int
    relationships: int
    locations: int
    quest_steps: int
    details: int
    lifecycle_records: int
    other_persisted_pages: int
    other_normalized_pages: int
    kinds: tuple[AllakhazamKindNormalizationDelta, ...]

    @property
    def captured_not_persisted(self) -> int:
        return sum(kind.captured_not_persisted for kind in self.kinds)

    @property
    def persisted_not_normalized(self) -> int:
        return sum(kind.persisted_not_normalized for kind in self.kinds)

    def as_dict(self) -> dict[str, object]:
        return {
            "source_name": "Allakhazam",
            "source_kind": "local_mirror",
            "mirror_importable_pages": self.mirror_importable_pages,
            "mirror_temporary_files": self.mirror_temporary_files,
            "mirror_read_errors": self.mirror_read_errors,
            "mirror_spell_pages_with_expansion": self.mirror_spell_pages_with_expansion,
            "source_pages": self.source_pages,
            "classified_pages": self.classified_pages,
            "normalized_pages": self.normalized_pages,
            "captured_not_persisted": self.captured_not_persisted,
            "persisted_not_normalized": self.persisted_not_normalized,
            "entity_links": self.entity_links,
            "primary_entity_links": self.primary_entity_links,
            "relationships": self.relationships,
            "locations": self.locations,
            "quest_steps": self.quest_steps,
            "details": self.details,
            "lifecycle_records": self.lifecycle_records,
            "other_persisted_pages": self.other_persisted_pages,
            "other_normalized_pages": self.other_normalized_pages,
            "kinds": [kind.as_dict() for kind in self.kinds],
        }


def _int_field(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"mirror audit field {key!r} must be a non-negative integer")
    return int(value)


def _mirror_kind_counts(payload: Mapping[str, object]) -> dict[str, int]:
    raw = payload.get("pages_by_kind")
    if not isinstance(raw, Mapping):
        raise ValueError("mirror audit field 'pages_by_kind' must be an object")
    counts: dict[str, int] = {}
    for kind in STRUCTURED_KINDS:
        value = raw.get(kind, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                f"mirror audit pages_by_kind[{kind!r}] must be a non-negative integer"
            )
        counts[kind] = int(value)
    return counts


def validate_mirror_audit_payload(payload: Mapping[str, object]) -> None:
    counts = _mirror_kind_counts(payload)
    importable = _int_field(payload, "importable_pages")
    temporary = _int_field(payload, "temporary_files")
    read_errors = _int_field(payload, "read_errors")
    spell_with_expansion = _int_field(payload, "spell_pages_with_expansion")
    if sum(counts.values()) != importable:
        raise ValueError(
            "mirror audit is internally inconsistent: importable_pages does not equal "
            "the structured pages_by_kind total"
        )
    if spell_with_expansion > counts["spell"]:
        raise ValueError(
            "mirror audit is internally inconsistent: spell_pages_with_expansion "
            "exceeds captured spell pages"
        )
    # Read these fields as part of validation even though their values are diagnostic.
    _ = temporary, read_errors


def allakhazam_normalization_delta(
    db: DatabaseLike,
    mirror_audit: Mapping[str, object],
) -> AllakhazamNormalizationDelta:
    """Compare one completed-mirror inventory with its persisted SQLite projection.

    The filesystem is never consulted here. ``mirror_audit`` is the JSON payload from
    the earlier read-only capture audit; ``db`` is a builder or finalized knowledge DB.
    This avoids rescanning a mirror after a potentially long build and makes the two
    sides of the comparison explicit artifacts.
    """
    validate_mirror_audit_payload(mirror_audit)
    captured = _mirror_kind_counts(mirror_audit)
    provider = provider_normalization_coverage(db, "Allakhazam", "local_mirror")
    persisted = dict(provider.page_types)
    normalized = dict(provider.normalized_page_types)

    kinds = tuple(
        AllakhazamKindNormalizationDelta(
            kind=kind,
            captured_pages=captured[kind],
            persisted_pages=int(persisted.get(kind, 0)),
            normalized_pages=int(normalized.get(kind, 0)),
        )
        for kind in STRUCTURED_KINDS
    )
    structured_persisted = sum(kind.persisted_pages for kind in kinds)
    structured_normalized = sum(kind.normalized_pages for kind in kinds)

    return AllakhazamNormalizationDelta(
        mirror_importable_pages=_int_field(mirror_audit, "importable_pages"),
        mirror_temporary_files=_int_field(mirror_audit, "temporary_files"),
        mirror_read_errors=_int_field(mirror_audit, "read_errors"),
        mirror_spell_pages_with_expansion=_int_field(
            mirror_audit, "spell_pages_with_expansion"
        ),
        source_pages=provider.source_pages,
        classified_pages=provider.classified_pages,
        normalized_pages=provider.normalized_pages,
        entity_links=provider.entity_links,
        primary_entity_links=provider.primary_entity_links,
        relationships=provider.relationships,
        locations=provider.locations,
        quest_steps=provider.quest_steps,
        details=provider.details,
        lifecycle_records=provider.lifecycle_records,
        other_persisted_pages=max(0, provider.source_pages - structured_persisted),
        other_normalized_pages=max(0, provider.normalized_pages - structured_normalized),
        kinds=kinds,
    )


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100.0 * value:.1f}%"


def allakhazam_normalization_delta_text(
    report: AllakhazamNormalizationDelta,
) -> str:
    lines = [
        "EverQuestie Allakhazam capture → normalization delta",
        "",
        "Read-only artifact comparison. The mirror filesystem is not scanned or modified.",
        "",
        f"Mirror structured pages ready for import: {report.mirror_importable_pages:,}",
        f"Mirror temporary files at inventory time: {report.mirror_temporary_files:,}",
        f"Mirror read errors: {report.mirror_read_errors:,}",
        f"Persisted Allakhazam source pages: {report.source_pages:,}",
        f"Classified Allakhazam source pages: {report.classified_pages:,}",
        f"Pages with normalized DB derivatives: {report.normalized_pages:,}",
        "",
        "Structured page flow by kind:",
        "  kind   captured -> persisted -> normalized | capture gap | normalize gap",
    ]
    for kind in report.kinds:
        lines.append(
            f"  {kind.kind:<6} {kind.captured_pages:>8,} -> {kind.persisted_pages:>8,} "
            f"({_pct(kind.persisted_fraction_of_capture):>6}) -> "
            f"{kind.normalized_pages:>8,} "
            f"({_pct(kind.normalized_fraction_of_persisted):>6}) | "
            f"{kind.captured_not_persisted:>8,} | {kind.persisted_not_normalized:>8,}"
        )
        if kind.persisted_not_in_capture:
            lines.append(
                f"         note: {kind.persisted_not_in_capture:,} persisted {kind.kind} "
                "page(s) are not represented by this mirror inventory artifact"
            )

    lines += [
        "",
        "Normalized derivatives from Allakhazam:",
        f"  canonical entity links: {report.entity_links:,} ({report.primary_entity_links:,} primary)",
        f"  relationships: {report.relationships:,}",
        f"  locations: {report.locations:,}",
        f"  quest steps: {report.quest_steps:,}",
        f"  rich details: {report.details:,}",
        f"  source-granular lifecycle records: {report.lifecycle_records:,}",
        f"  captured spell pages with reviewed Expansion: {report.mirror_spell_pages_with_expansion:,}",
    ]
    if report.other_persisted_pages or report.other_normalized_pages:
        lines += [
            "",
            "Other persisted Allakhazam page types:",
            f"  persisted: {report.other_persisted_pages:,}",
            f"  normalized: {report.other_normalized_pages:,}",
        ]

    lines += [
        "",
        "Interpretation:",
        "  • captured→persisted isolates importer/capture handoff gaps by structured source-page kind.",
        "  • persisted→normalized isolates pages stored as provenance but lacking any canonical/graph/detail/lifecycle derivative.",
        "  • Canonical entity links are not expected to equal source pages: one source page may discover or link multiple entities.",
        "  • Unattached spell lifecycle records still count as normalized source evidence; conservative identity reconciliation is a separate question.",
        "  • This report is diagnostic only. It does not invent thresholds, mutate knowledge, or rescan the source mirror.",
    ]
    return "\n".join(lines)
