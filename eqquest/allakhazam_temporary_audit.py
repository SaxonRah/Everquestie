from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from .allakhazam import (
    AllakhazamImporter,
    MiniDOMParser,
    VisibleTextParser,
    extract_canonical_url,
    infer_kind_and_external_id,
)
from .allakhazam_mirror_importer import _spell_numeric_id


STRUCTURED_KINDS = {"quest", "npc", "item", "zone", "spell"}
_HTML_END_RE = re.compile(r"</html\s*>", re.I)
_BODY_END_RE = re.compile(r"</body\s*>", re.I)
_HEAD_PROBE_BYTES = 16 * 1024
_TAIL_PROBE_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class TemporaryPageAudit:
    root: Path
    temporary_files: int
    final_temporary_files: int
    temporary_bytes: int
    readable_files: int
    read_errors: int
    files_with_canonical_url: int
    unique_canonical_pages: int
    duplicate_canonical_files: int
    structured_canonical_files: int
    likely_complete_structured_files: int
    structured_files_missing_document_end: int
    duplicate_of_completed_page_files: int
    full_content_fallback_reads: int
    files_changed_while_reading: int
    files_added_during_scan: int
    files_removed_during_scan: int
    mirror_changed_during_scan: bool
    by_filename_family: tuple[tuple[str, int], ...]
    by_canonical_kind: tuple[tuple[str, int], ...]
    by_status: tuple[tuple[str, int], ...]
    sample_paths_by_status: tuple[tuple[str, tuple[str, ...]], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "temporary_files": self.temporary_files,
            "final_temporary_files": self.final_temporary_files,
            "temporary_bytes": self.temporary_bytes,
            "readable_files": self.readable_files,
            "read_errors": self.read_errors,
            "files_with_canonical_url": self.files_with_canonical_url,
            "unique_canonical_pages": self.unique_canonical_pages,
            "duplicate_canonical_files": self.duplicate_canonical_files,
            "structured_canonical_files": self.structured_canonical_files,
            "likely_complete_structured_files": self.likely_complete_structured_files,
            "structured_files_missing_document_end": self.structured_files_missing_document_end,
            "duplicate_of_completed_page_files": self.duplicate_of_completed_page_files,
            "full_content_fallback_reads": self.full_content_fallback_reads,
            "files_changed_while_reading": self.files_changed_while_reading,
            "files_added_during_scan": self.files_added_during_scan,
            "files_removed_during_scan": self.files_removed_during_scan,
            "mirror_changed_during_scan": self.mirror_changed_during_scan,
            "by_filename_family": dict(self.by_filename_family),
            "by_canonical_kind": dict(self.by_canonical_kind),
            "by_status": dict(self.by_status),
            "sample_paths_by_status": {
                status: list(paths) for status, paths in self.sample_paths_by_status
            },
        }


def _filename_family(path: Path) -> str:
    name = path.name.casefold()
    for family in ("npc", "item", "quest", "zone", "spell"):
        if name.startswith(family) and ".htm" in name:
            return family
    return "other"


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _read_probe(path: Path) -> tuple[str, str, int, bool]:
    """Read only the head/tail needed for identity and completion signals.

    The old audit decoded every byte of every temporary page. On a live mirror this
    meant repeatedly streaming roughly ten GiB from the same tree HTTrack was still
    writing. Canonical metadata normally lives in the document head and completion
    markers live at the physical tail, so probe those regions first. Callers may fall
    back to a full read only when the head cannot establish identity or when the real
    importer needs document markup to classify a legacy generic canonical URL.
    """

    before = path.stat()
    size = int(before.st_size)
    with path.open("rb") as handle:
        head = handle.read(min(size, _HEAD_PROBE_BYTES))
        if size <= _TAIL_PROBE_BYTES:
            tail = head[-_TAIL_PROBE_BYTES:]
        else:
            handle.seek(max(0, size - _TAIL_PROBE_BYTES))
            tail = handle.read(_TAIL_PROBE_BYTES)
    after = path.stat()
    changed = (
        int(before.st_size) != int(after.st_size)
        or int(before.st_mtime_ns) != int(after.st_mtime_ns)
    )
    return _decode(head), _decode(tail), size, changed


def _read_full_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _document_fallback_kind(raw: str, canonical: str) -> tuple[str | None, str | None]:
    """Use the production importer's legacy-document identity fallback exactly.

    Some Allakhazam bestiary/NPC pages advertise a generic ``search.html?id=...``
    canonical URL. ``infer_kind_and_external_id`` therefore cannot classify them from
    the URL alone even though their markup is a normal NPC page. The real importer
    already handles this through ``_infer_kind_and_external_id_from_document``; the
    audit must reuse that rule rather than reporting tens of thousands of NPC pages as
    ``canonical_other``.
    """

    visible = VisibleTextParser()
    visible.feed(raw)
    dom = MiniDOMParser()
    dom.feed(raw)
    importer = object.__new__(AllakhazamImporter)
    return importer._infer_kind_and_external_id_from_document(  # noqa: SLF001
        dom.root,
        visible.title,
        canonical,
    )


def _completed_canonical_urls(root: Path) -> set[str]:
    urls: set[str] = set()
    for path in root.rglob("*.htm*"):
        if not path.is_file() or path.name.casefold().endswith(".tmp"):
            continue
        try:
            head, _tail, _size, _changed = _read_probe(path)
            canonical = extract_canonical_url(head)
            if canonical is None:
                canonical = extract_canonical_url(_read_full_text(path))
        except OSError:
            continue
        if canonical:
            urls.add(canonical)
    return urls


def _temporary_paths(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.tmp")
        if path.is_file() and ".htm" in path.name.casefold()
    )


def audit_allakhazam_temporary_pages(
    folder: str | Path,
    *,
    sample_limit: int = 8,
    progress: Callable[[int, int], None] | None = None,
) -> TemporaryPageAudit:
    """Inspect HTTrack .tmp pages without importing, renaming or modifying them.

    The audit deliberately separates three questions:

    * did the temporary file contain a proven canonical Allakhazam URL;
    * does that URL/document identify one of EverQuestie's structured entity families;
    * did the response include normal closing body/html markers near its physical end.

    The initial temporary-file list is a point-in-time scan snapshot. A cheap metadata
    pass at the end reports files added/removed while the audit was running, and each
    probed file is stat-checked around its read. This is particularly important for a
    mirror that HTTrack is still actively growing.

    ``likely_complete_structured`` is a recovery *candidate* classification, not a
    claim that a .tmp file is safe to promote automatically.
    """

    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    paths = _temporary_paths(root)
    total = len(paths)
    initial_relative_paths = {str(path.relative_to(root)) for path in paths}
    completed_urls = _completed_canonical_urls(root)

    filename_families: Counter[str] = Counter()
    canonical_kinds: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    canonical_counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}

    readable = 0
    read_errors = 0
    total_bytes = 0
    files_with_canonical = 0
    structured = 0
    likely_complete_structured = 0
    structured_missing_end = 0
    duplicate_of_completed = 0
    full_content_fallback_reads = 0
    files_changed_while_reading = 0

    for index, path in enumerate(paths, start=1):
        filename_families[_filename_family(path)] += 1
        try:
            head, tail, size, changed = _read_probe(path)
            total_bytes += size
            if changed:
                files_changed_while_reading += 1

            full_raw: str | None = None
            canonical = extract_canonical_url(head)
            if canonical is None:
                full_raw = _read_full_text(path)
                full_content_fallback_reads += 1
                canonical = extract_canonical_url(full_raw)
        except OSError:
            read_errors += 1
            statuses["read_error"] += 1
            if len(examples.setdefault("read_error", [])) < sample_limit:
                examples["read_error"].append(str(path.relative_to(root)))
            if progress is not None:
                progress(index, total)
            continue

        readable += 1
        has_end = bool(_HTML_END_RE.search(tail) and _BODY_END_RE.search(tail))

        if not canonical:
            status = "no_canonical_with_document_end" if has_end else "no_canonical_missing_document_end"
        else:
            files_with_canonical += 1
            canonical_counts[canonical] += 1
            kind, _external_id = infer_kind_and_external_id(canonical)
            if _spell_numeric_id(canonical):
                kind = "spell"

            if kind not in STRUCTURED_KINDS:
                try:
                    if full_raw is None:
                        full_raw = _read_full_text(path)
                        full_content_fallback_reads += 1
                    fallback_kind, _fallback_external_id = _document_fallback_kind(full_raw, canonical)
                    if fallback_kind in STRUCTURED_KINDS:
                        kind = fallback_kind
                except (OSError, ValueError):
                    # Audit classification remains conservative: a failed fallback is
                    # still canonical_other rather than a guessed structured identity.
                    pass

            if kind in STRUCTURED_KINDS:
                structured += 1
                canonical_kinds[str(kind)] += 1
                if canonical in completed_urls:
                    duplicate_of_completed += 1
                    status = "structured_duplicate_of_completed_page"
                elif has_end:
                    likely_complete_structured += 1
                    status = "likely_complete_structured"
                else:
                    structured_missing_end += 1
                    status = "structured_missing_document_end"
            else:
                status = "canonical_other_with_document_end" if has_end else "canonical_other_missing_document_end"

        statuses[status] += 1
        if len(examples.setdefault(status, [])) < sample_limit:
            examples[status].append(str(path.relative_to(root)))

        if progress is not None:
            progress(index, total)

    duplicate_canonical_files = sum(max(0, count - 1) for count in canonical_counts.values())

    final_paths = _temporary_paths(root)
    final_relative_paths = {str(path.relative_to(root)) for path in final_paths}
    files_added_during_scan = len(final_relative_paths - initial_relative_paths)
    files_removed_during_scan = len(initial_relative_paths - final_relative_paths)
    mirror_changed_during_scan = bool(
        files_changed_while_reading
        or files_added_during_scan
        or files_removed_during_scan
    )

    return TemporaryPageAudit(
        root=root,
        temporary_files=total,
        final_temporary_files=len(final_paths),
        temporary_bytes=total_bytes,
        readable_files=readable,
        read_errors=read_errors,
        files_with_canonical_url=files_with_canonical,
        unique_canonical_pages=len(canonical_counts),
        duplicate_canonical_files=duplicate_canonical_files,
        structured_canonical_files=structured,
        likely_complete_structured_files=likely_complete_structured,
        structured_files_missing_document_end=structured_missing_end,
        duplicate_of_completed_page_files=duplicate_of_completed,
        full_content_fallback_reads=full_content_fallback_reads,
        files_changed_while_reading=files_changed_while_reading,
        files_added_during_scan=files_added_during_scan,
        files_removed_during_scan=files_removed_during_scan,
        mirror_changed_during_scan=mirror_changed_during_scan,
        by_filename_family=tuple(sorted(filename_families.items(), key=lambda item: (-item[1], item[0]))),
        by_canonical_kind=tuple(sorted(canonical_kinds.items(), key=lambda item: (-item[1], item[0]))),
        by_status=tuple(sorted(statuses.items(), key=lambda item: (-item[1], item[0]))),
        sample_paths_by_status=tuple(
            (status, tuple(paths)) for status, paths in sorted(examples.items())
        ),
    )


def allakhazam_temporary_audit_text(
    folder: str | Path,
    *,
    sample_limit: int = 8,
    progress: Callable[[int, int], None] | None = None,
) -> str:
    audit = audit_allakhazam_temporary_pages(
        folder,
        sample_limit=sample_limit,
        progress=progress,
    )
    mib = audit.temporary_bytes / (1024 * 1024)
    lines = [
        "EverQuestie Allakhazam temporary-page audit",
        "",
        f"Mirror root: {audit.root}",
        "Read-only filesystem audit. No renames, imports, DB writes or network access.",
        "",
        f"Temporary HTML-like files at scan start: {audit.temporary_files:,}",
        f"Temporary HTML-like files at scan end: {audit.final_temporary_files:,}",
        f"Temporary bytes in start snapshot: {mib:,.1f} MiB",
        f"Readable temporary files: {audit.readable_files:,}",
        f"Read errors: {audit.read_errors:,}",
        f"Files with canonical Allakhazam URL: {audit.files_with_canonical_url:,}",
        f"Unique canonical pages represented: {audit.unique_canonical_pages:,}",
        f"Duplicate canonical temporary files: {audit.duplicate_canonical_files:,}",
        f"Structured quest/NPC/item/zone/spell temporary files: {audit.structured_canonical_files:,}",
        f"Likely-complete structured recovery candidates: {audit.likely_complete_structured_files:,}",
        f"Structured files missing document-end markers: {audit.structured_files_missing_document_end:,}",
        f"Structured temporary files duplicating an already completed page: {audit.duplicate_of_completed_page_files:,}",
        f"Full-content fallback reads: {audit.full_content_fallback_reads:,}",
        (
            "Mirror changed during scan: "
            + ("YES" if audit.mirror_changed_during_scan else "no")
            + (
                f" | added={audit.files_added_during_scan:,}"
                f" removed={audit.files_removed_during_scan:,}"
                f" changed-while-reading={audit.files_changed_while_reading:,}"
            )
        ),
    ]

    if audit.by_filename_family:
        lines += ["", "Temporary files by filename family:"]
        lines.extend(f"  {name}: {count:,}" for name, count in audit.by_filename_family)
    if audit.by_canonical_kind:
        lines += ["", "Structured canonical temporary files by kind:"]
        lines.extend(f"  {name}: {count:,}" for name, count in audit.by_canonical_kind)
    if audit.by_status:
        lines += ["", "Temporary-page status:"]
        lines.extend(f"  {name}: {count:,}" for name, count in audit.by_status)
    if audit.sample_paths_by_status:
        lines += ["", "Sample paths by status:"]
        for status, paths in audit.sample_paths_by_status:
            lines.append(f"  {status}:")
            lines.extend(f"    {path}" for path in paths)

    lines += [
        "",
        "Interpretation:",
        "  • .tmp remains untrusted builder input regardless of size or closing tags.",
        "  • likely_complete_structured means canonical structured identity + body/html end markers; it is a recovery candidate, not an automatic promotion.",
        "  • structured_missing_document_end strongly suggests an interrupted/truncated response and should be resumed/re-fetched rather than renamed.",
        "  • duplicate_of_completed_page can normally be ignored for knowledge coverage because a completed canonical copy already exists.",
        "  • generic legacy bestiary canonicals are classified with the same document fallback used by the production importer.",
        "  • numeric Allakhazam spell canonicals use the same exact spell-ID rule as the production mirror importer.",
        "  • if 'Mirror changed during scan' is YES, all counts are an in-progress point-in-time snapshot rather than a final mirror inventory.",
    ]
    return "\n".join(lines)
