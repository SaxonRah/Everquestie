from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .allakhazam import MiniDOMParser, extract_canonical_url, infer_kind_and_external_id
from .allakhazam_mirror_importer import _quick_facts_expansion, _spell_numeric_id


@dataclass(frozen=True, slots=True)
class AllakhazamMirrorAudit:
    root: Path
    all_files: int
    html_candidates: int
    temporary_files: int
    readable_files: int
    read_errors: int
    canonical_files: int
    unique_canonical_pages: int
    duplicate_canonical_files: int
    importable_pages: int
    missing_canonical: int
    unclassified_canonical: int
    pages_by_kind: tuple[tuple[str, int], ...]
    spell_pages: int
    spell_pages_with_expansion: int
    spell_pages_missing_expansion: int
    duplicate_urls: tuple[tuple[str, int], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "all_files": self.all_files,
            "html_candidates": self.html_candidates,
            "temporary_files": self.temporary_files,
            "readable_files": self.readable_files,
            "read_errors": self.read_errors,
            "canonical_files": self.canonical_files,
            "unique_canonical_pages": self.unique_canonical_pages,
            "duplicate_canonical_files": self.duplicate_canonical_files,
            "importable_pages": self.importable_pages,
            "missing_canonical": self.missing_canonical,
            "unclassified_canonical": self.unclassified_canonical,
            "pages_by_kind": dict(self.pages_by_kind),
            "spell_pages": self.spell_pages,
            "spell_pages_with_expansion": self.spell_pages_with_expansion,
            "spell_pages_missing_expansion": self.spell_pages_missing_expansion,
            "duplicate_urls": dict(self.duplicate_urls),
        }


def _mirror_page_kind(canonical: str) -> str | None:
    """Classify exactly the structured page families the mirror importer accepts."""
    kind, _external_id = infer_kind_and_external_id(canonical)
    if kind:
        return kind
    if _spell_numeric_id(canonical):
        return "spell"
    return None


def _spell_has_reviewed_expansion(raw_html: str) -> bool:
    """Use the importer's exact Quick Facts parser; never scan arbitrary prose."""
    dom = MiniDOMParser()
    dom.feed(raw_html)
    return bool(_quick_facts_expansion(dom.root))


def audit_allakhazam_mirror(folder: str | Path) -> AllakhazamMirrorAudit:
    """Classify a local mirror without importing or modifying any EverQuestie DB.

    This intentionally mirrors the builder importer's first-stage acceptance rules:
    only saved HTML-like files are considered, `.tmp` files are excluded, canonical
    Allakhazam URLs are extracted from the document itself, and recognized structured
    page identity is inferred from that canonical URL. Spell lifecycle readiness also
    uses the mirror importer's exact labeled Quick Facts ``Expansion`` parser.

    No database writes and no network access are performed.
    """
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    all_files = 0
    paths: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        all_files += 1
        # Match the importer's historical `rglob("*.htm*")` acceptance rule.
        if ".htm" in path.name.casefold():
            paths.append(path)
    paths.sort()

    html_candidates = len(paths)
    temporary_files = 0
    readable_files = 0
    read_errors = 0
    missing_canonical = 0

    canonical_counts: dict[str, int] = {}
    canonical_kind: dict[str, str | None] = {}
    spell_expansion_by_url: dict[str, bool] = {}

    for path in paths:
        if path.name.casefold().endswith(".tmp"):
            temporary_files += 1
            continue
        try:
            raw_html = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            read_errors += 1
            continue
        readable_files += 1

        canonical = extract_canonical_url(raw_html)
        if not canonical:
            missing_canonical += 1
            continue
        canonical_counts[canonical] = canonical_counts.get(canonical, 0) + 1
        kind = _mirror_page_kind(canonical)
        canonical_kind.setdefault(canonical, kind)
        if kind == "spell":
            # Duplicate local files for one source URL still represent one source page.
            # If any completed copy contains the reviewed structured field, the unique
            # source page is lifecycle-ready; the importer will preserve that exact fact.
            spell_expansion_by_url[canonical] = (
                spell_expansion_by_url.get(canonical, False)
                or _spell_has_reviewed_expansion(raw_html)
            )

    canonical_files = sum(canonical_counts.values())
    unique_canonical_pages = len(canonical_counts)
    duplicate_canonical_files = sum(
        max(0, count - 1) for count in canonical_counts.values()
    )

    pages_by_kind_dict: dict[str, int] = {}
    unclassified_canonical = 0
    importable_pages = 0
    for url in sorted(canonical_counts):
        kind = canonical_kind.get(url)
        if kind:
            pages_by_kind_dict[kind] = pages_by_kind_dict.get(kind, 0) + 1
            importable_pages += 1
        else:
            unclassified_canonical += 1

    spell_pages = int(pages_by_kind_dict.get("spell", 0))
    spell_pages_with_expansion = sum(
        1 for has_expansion in spell_expansion_by_url.values() if has_expansion
    )
    spell_pages_missing_expansion = max(0, spell_pages - spell_pages_with_expansion)

    duplicate_urls = tuple(
        sorted(
            ((url, count) for url, count in canonical_counts.items() if count > 1),
            key=lambda item: (-item[1], item[0]),
        )
    )

    return AllakhazamMirrorAudit(
        root=root,
        all_files=all_files,
        html_candidates=html_candidates,
        temporary_files=temporary_files,
        readable_files=readable_files,
        read_errors=read_errors,
        canonical_files=canonical_files,
        unique_canonical_pages=unique_canonical_pages,
        duplicate_canonical_files=duplicate_canonical_files,
        importable_pages=importable_pages,
        missing_canonical=missing_canonical,
        unclassified_canonical=unclassified_canonical,
        pages_by_kind=tuple(
            sorted(pages_by_kind_dict.items(), key=lambda item: (-item[1], item[0]))
        ),
        spell_pages=spell_pages,
        spell_pages_with_expansion=spell_pages_with_expansion,
        spell_pages_missing_expansion=spell_pages_missing_expansion,
        duplicate_urls=duplicate_urls,
    )


def format_allakhazam_mirror_audit(
    audit: AllakhazamMirrorAudit,
    *,
    duplicate_limit: int = 12,
) -> str:
    """Render a previously collected mirror audit without touching the filesystem."""
    lines = [
        "EverQuestie Allakhazam mirror inventory audit",
        "",
        f"Mirror root: {audit.root}",
        "Read-only filesystem audit. No DB writes and no network access.",
        "",
        f"All mirror files: {audit.all_files:,}",
        f"HTML-like files discovered: {audit.html_candidates:,}",
        f"Temporary/in-progress files ignored: {audit.temporary_files:,}",
        f"Readable completed HTML files: {audit.readable_files:,}",
        f"Read errors: {audit.read_errors:,}",
        f"Files with canonical Allakhazam URL: {audit.canonical_files:,}",
        f"Unique canonical pages: {audit.unique_canonical_pages:,}",
        f"Duplicate canonical files: {audit.duplicate_canonical_files:,}",
        f"Unique structured pages ready for import: {audit.importable_pages:,}",
        f"Readable files with no canonical URL: {audit.missing_canonical:,}",
        f"Canonical helper/search/other pages not mapped to a structured kind: {audit.unclassified_canonical:,}",
    ]
    if audit.pages_by_kind:
        lines += ["", "Structured pages by kind:"]
        lines.extend(f"  {kind}: {count:,}" for kind, count in audit.pages_by_kind)
    if audit.spell_pages:
        lines += [
            "",
            "Structured spell lifecycle coverage:",
            f"  Spell pages: {audit.spell_pages:,}",
            f"  With reviewed Quick Facts Expansion: {audit.spell_pages_with_expansion:,}",
            f"  Missing reviewed Quick Facts Expansion: {audit.spell_pages_missing_expansion:,}",
        ]
    if audit.duplicate_urls:
        lines += ["", "Most duplicated canonical URLs:"]
        for url, count in audit.duplicate_urls[: max(0, duplicate_limit)]:
            lines.append(f"  {count:,} files -> {url}")
    lines += [
        "",
        "Interpretation:",
        "  • HTTrack/raw mirror file count includes assets and helper pages; it is not expected to equal EverQuestie source_pages.",
        "  • importable_pages is the upper bound of unique structured pages the current Allakhazam mirror importer can classify from canonical URLs.",
        "  • spell_pages_with_expansion counts only labeled Quick Facts Expansion values accepted by the production spell lifecycle parser; comments/prose do not count.",
        "  • Run the DB normalization coverage audit after import to compare mirror inventory with what was actually normalized into SQLite.",
    ]
    return "\n".join(lines)


def allakhazam_mirror_audit_text(
    folder: str | Path,
    *,
    duplicate_limit: int = 12,
) -> str:
    """Backward-compatible scan-and-render convenience wrapper."""
    return format_allakhazam_mirror_audit(
        audit_allakhazam_mirror(folder),
        duplicate_limit=duplicate_limit,
    )
