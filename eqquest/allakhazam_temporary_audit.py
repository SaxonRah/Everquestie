from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from .allakhazam import extract_canonical_url, infer_kind_and_external_id


STRUCTURED_KINDS = {"quest", "npc", "item", "zone"}
_HTML_END_RE = re.compile(r"</html\s*>", re.I)
_BODY_END_RE = re.compile(r"</body\s*>", re.I)


@dataclass(frozen=True, slots=True)
class TemporaryPageAudit:
    root: Path
    temporary_files: int
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
    by_filename_family: tuple[tuple[str, int], ...]
    by_canonical_kind: tuple[tuple[str, int], ...]
    by_status: tuple[tuple[str, int], ...]
    sample_paths_by_status: tuple[tuple[str, tuple[str, ...]], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "temporary_files": self.temporary_files,
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
            "by_filename_family": dict(self.by_filename_family),
            "by_canonical_kind": dict(self.by_canonical_kind),
            "by_status": dict(self.by_status),
            "sample_paths_by_status": {
                status: list(paths) for status, paths in self.sample_paths_by_status
            },
        }


def _filename_family(path: Path) -> str:
    name = path.name.casefold()
    for family in ("npc", "item", "quest", "zone"):
        if name.startswith(family) and ".htm" in name:
            return family
    return "other"


def _has_document_end(raw: str) -> bool:
    # A closing HTML element near the physical end is a useful conservative signal
    # that HTTrack received the end of the response. It is not, by itself, permission
    # to import or rename a .tmp file.
    tail = raw[-16384:]
    return bool(_HTML_END_RE.search(tail) and _BODY_END_RE.search(tail))


def _completed_canonical_urls(root: Path) -> set[str]:
    urls: set[str] = set()
    for path in root.rglob("*.htm*"):
        if not path.is_file() or path.name.casefold().endswith(".tmp"):
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        canonical = extract_canonical_url(raw)
        if canonical:
            urls.add(canonical)
    return urls


def audit_allakhazam_temporary_pages(
    folder: str | Path,
    *,
    sample_limit: int = 8,
    progress: Callable[[int, int], None] | None = None,
) -> TemporaryPageAudit:
    """Inspect HTTrack .tmp pages without importing, renaming or modifying them.

    The audit deliberately separates three questions:

    * did the temporary file contain a proven canonical Allakhazam URL;
    * does that URL identify one of EverQuestie's structured entity page families;
    * did the response include normal closing body/html markers near its physical end.

    ``likely_complete_structured`` is therefore a recovery *candidate* classification,
    not a claim that the file is safe to promote automatically. A later recovery step
    can run the normal parser against a copy/staging area if the corpus justifies it.
    """

    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    paths = sorted(
        path for path in root.rglob("*.tmp") if path.is_file() and ".htm" in path.name.casefold()
    )
    total = len(paths)
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

    for index, path in enumerate(paths, start=1):
        filename_families[_filename_family(path)] += 1
        try:
            total_bytes += int(path.stat().st_size)
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            read_errors += 1
            statuses["read_error"] += 1
            if len(examples.setdefault("read_error", [])) < sample_limit:
                examples["read_error"].append(str(path.relative_to(root)))
            if progress is not None:
                progress(index, total)
            continue

        readable += 1
        canonical = extract_canonical_url(raw)
        has_end = _has_document_end(raw)

        if not canonical:
            status = "no_canonical_with_document_end" if has_end else "no_canonical_missing_document_end"
        else:
            files_with_canonical += 1
            canonical_counts[canonical] += 1
            kind, _external_id = infer_kind_and_external_id(canonical)
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

    return TemporaryPageAudit(
        root=root,
        temporary_files=total,
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
        f"Temporary HTML-like files: {audit.temporary_files:,}",
        f"Temporary bytes: {mib:,.1f} MiB",
        f"Readable temporary files: {audit.readable_files:,}",
        f"Read errors: {audit.read_errors:,}",
        f"Files with canonical Allakhazam URL: {audit.files_with_canonical_url:,}",
        f"Unique canonical pages represented: {audit.unique_canonical_pages:,}",
        f"Duplicate canonical temporary files: {audit.duplicate_canonical_files:,}",
        f"Structured quest/NPC/item/zone temporary files: {audit.structured_canonical_files:,}",
        f"Likely-complete structured recovery candidates: {audit.likely_complete_structured_files:,}",
        f"Structured files missing document-end markers: {audit.structured_files_missing_document_end:,}",
        f"Structured temporary files duplicating an already completed page: {audit.duplicate_of_completed_page_files:,}",
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
    ]
    return "\n".join(lines)
