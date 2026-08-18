from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Callable

from .allakhazam import ImportResult, extract_canonical_url, infer_kind_and_external_id
from .allakhazam_mirror_importer import AllakhazamMirrorImporter, _spell_numeric_id
from .allakhazam_temporary_audit import (
    STRUCTURED_KINDS,
    _BODY_END_RE,
    _HTML_END_RE,
    _TAIL_PROBE_BYTES,
    _completed_canonical_urls,
    _document_fallback_kind,
    _read_full_text,
    _read_probe,
    _temporary_paths,
)


@dataclass(frozen=True, slots=True)
class TemporaryRecoveryPage:
    path: Path
    status: str
    canonical_url: str
    kind: str
    external_id: str
    size: int
    changed_while_reading: bool
    has_document_end: bool
    used_full_content_fallback: bool

    @property
    def recoverable(self) -> bool:
        return self.status == "likely_complete_structured" and not self.changed_while_reading


@dataclass(slots=True)
class TemporaryRecoveryResult:
    root: Path
    temporary_files: int = 0
    candidates: int = 0
    imported: list[ImportResult] = field(default_factory=list)
    unchanged: int = 0
    read_errors: int = 0
    parse_errors: int = 0
    skipped_unstable: int = 0
    skipped_duplicate_completed: int = 0
    skipped_duplicate_temporary: int = 0
    skipped_revalidation: int = 0
    mirror_changed_during_scan: bool = False
    by_status: Counter[str] = field(default_factory=Counter)

    @property
    def changed(self) -> int:
        return len(self.imported)

    def as_dict(self) -> dict[str, object]:
        kinds: Counter[str] = Counter(result.kind for result in self.imported)
        return {
            "root": str(self.root),
            "temporary_files": self.temporary_files,
            "candidates": self.candidates,
            "imported": self.changed,
            "unchanged": self.unchanged,
            "read_errors": self.read_errors,
            "parse_errors": self.parse_errors,
            "skipped_unstable": self.skipped_unstable,
            "skipped_duplicate_completed": self.skipped_duplicate_completed,
            "skipped_duplicate_temporary": self.skipped_duplicate_temporary,
            "skipped_revalidation": self.skipped_revalidation,
            "mirror_changed_during_scan": self.mirror_changed_during_scan,
            "imported_by_kind": dict(sorted(kinds.items())),
            "by_status": dict(sorted(self.by_status.items())),
        }


def _structured_identity(raw: str, canonical: str) -> tuple[str, str]:
    kind, external_id = infer_kind_and_external_id(canonical)
    if _spell_numeric_id(canonical):
        return "spell", f"spell:{_spell_numeric_id(canonical)}"
    if kind not in STRUCTURED_KINDS:
        try:
            fallback_kind, fallback_external_id = _document_fallback_kind(raw, canonical)
        except (OSError, ValueError):
            return "", ""
        if fallback_kind in STRUCTURED_KINDS:
            return str(fallback_kind), str(fallback_external_id or "")
        return "", ""
    return str(kind), str(external_id or "")


def classify_temporary_recovery_page(
    path: str | Path,
    *,
    completed_urls: set[str] | None = None,
) -> TemporaryRecoveryPage:
    """Classify one HTTrack temporary page using the audit's exact trust signals.

    This helper is intentionally read-only. ``recoverable`` means only that the file
    has structured Allakhazam identity, normal body/html closing markers near its
    physical tail, no completed-page duplicate, and did not change during the probe.
    Recovery performs a second full-file stability check before importing anything.
    """

    candidate = Path(path).expanduser().resolve()
    completed = completed_urls or set()
    try:
        head, tail, size, changed = _read_probe(candidate)
        full_raw: str | None = None
        used_full = False
        canonical = extract_canonical_url(head)
        if canonical is None:
            full_raw = _read_full_text(candidate)
            used_full = True
            canonical = extract_canonical_url(full_raw)
    except OSError:
        return TemporaryRecoveryPage(
            path=candidate,
            status="read_error",
            canonical_url="",
            kind="",
            external_id="",
            size=0,
            changed_while_reading=False,
            has_document_end=False,
            used_full_content_fallback=False,
        )

    has_end = bool(_HTML_END_RE.search(tail) and _BODY_END_RE.search(tail))
    if not canonical:
        status = "no_canonical_with_document_end" if has_end else "no_canonical_missing_document_end"
        return TemporaryRecoveryPage(
            path=candidate,
            status=status,
            canonical_url="",
            kind="",
            external_id="",
            size=size,
            changed_while_reading=changed,
            has_document_end=has_end,
            used_full_content_fallback=used_full,
        )

    kind, external_id = infer_kind_and_external_id(canonical)
    if _spell_numeric_id(canonical):
        kind = "spell"
        external_id = f"spell:{_spell_numeric_id(canonical)}"
    if kind not in STRUCTURED_KINDS:
        try:
            if full_raw is None:
                full_raw = _read_full_text(candidate)
                used_full = True
            fallback_kind, fallback_external_id = _document_fallback_kind(full_raw, canonical)
            if fallback_kind in STRUCTURED_KINDS:
                kind = fallback_kind
                external_id = fallback_external_id
        except (OSError, ValueError):
            pass

    if kind in STRUCTURED_KINDS:
        if canonical in completed:
            status = "structured_duplicate_of_completed_page"
        elif has_end:
            status = "likely_complete_structured"
        else:
            status = "structured_missing_document_end"
    else:
        status = "canonical_other_with_document_end" if has_end else "canonical_other_missing_document_end"

    return TemporaryRecoveryPage(
        path=candidate,
        status=status,
        canonical_url=str(canonical),
        kind=str(kind or ""),
        external_id=str(external_id or ""),
        size=size,
        changed_while_reading=changed,
        has_document_end=has_end,
        used_full_content_fallback=used_full,
    )


def _stable_full_read(path: Path) -> tuple[str, bool]:
    before = path.stat()
    raw = path.read_text(encoding="utf-8", errors="replace")
    after = path.stat()
    changed = (
        int(before.st_size) != int(after.st_size)
        or int(before.st_mtime_ns) != int(after.st_mtime_ns)
    )
    return raw, changed


def _revalidate_full_page(raw: str, page: TemporaryRecoveryPage) -> bool:
    canonical = extract_canonical_url(raw)
    if canonical != page.canonical_url:
        return False
    tail = raw[-_TAIL_PROBE_BYTES:]
    if not (_HTML_END_RE.search(tail) and _BODY_END_RE.search(tail)):
        return False
    kind, external_id = _structured_identity(raw, canonical)
    if kind != page.kind:
        return False
    if page.external_id and external_id and external_id != page.external_id:
        return False
    return kind in STRUCTURED_KINDS


def recover_allakhazam_temporary_pages(
    db,
    folder: str | Path,
    *,
    source_version: str = "",
    progress: Callable[[int, int, str], None] | None = None,
) -> TemporaryRecoveryResult:
    """Explicitly import only stable likely-complete structured HTTrack ``.tmp`` pages.

    Normal mirror import intentionally ignores every temporary file. This function is a
    separate builder/developer recovery action for partial mirrors whose temporary-page
    audit exposes usable structured responses. It never renames, deletes, repairs, or
    otherwise modifies the mirror.

    Candidate classification uses the same canonical/document-end/fallback signals as
    the temporary audit. Each candidate is then read in full under a second stat check,
    its canonical identity and completion markers are revalidated, and only then is the
    existing production Allakhazam importer invoked. A completed non-temporary page
    always wins over a temporary copy.
    """

    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    paths = _temporary_paths(root)
    initial_relative = {str(path.relative_to(root)) for path in paths}
    completed_before = _completed_canonical_urls(root)
    result = TemporaryRecoveryResult(root=root, temporary_files=len(paths))

    classified: list[TemporaryRecoveryPage] = []
    for index, path in enumerate(paths, start=1):
        page = classify_temporary_recovery_page(path, completed_urls=completed_before)
        classified.append(page)
        result.by_status[page.status] += 1
        if page.status == "read_error":
            result.read_errors += 1
        if page.status == "likely_complete_structured":
            result.candidates += 1
        if progress is not None:
            progress(index, len(paths), page.status)

    # Re-scan finalized pages after classification. If HTTrack completed a response
    # while this read-only scan was running, the finalized page wins and its .tmp peer
    # is never imported by the recovery action.
    completed_after = _completed_canonical_urls(root)
    final_paths = _temporary_paths(root)
    final_relative = {str(path.relative_to(root)) for path in final_paths}
    result.mirror_changed_during_scan = bool(
        initial_relative != final_relative or completed_before != completed_after
    )

    importer = AllakhazamMirrorImporter(db)
    accepted_canonicals: set[str] = set()
    recognized_types = set(STRUCTURED_KINDS)
    version = str(source_version or "").strip()

    with db.batch():
        for page in classified:
            if page.status != "likely_complete_structured":
                continue
            if page.changed_while_reading:
                result.skipped_unstable += 1
                continue
            canonical = page.canonical_url
            if canonical in completed_after:
                result.skipped_duplicate_completed += 1
                continue
            if canonical in accepted_canonicals:
                result.skipped_duplicate_temporary += 1
                continue

            try:
                raw, changed = _stable_full_read(page.path)
            except OSError:
                result.read_errors += 1
                continue
            if changed:
                result.skipped_unstable += 1
                continue
            if not _revalidate_full_page(raw, page):
                result.skipped_revalidation += 1
                continue

            digest = sha256(raw.encode("utf-8", errors="replace")).hexdigest()
            existing = db.conn.execute(
                """
                SELECT id,sha256,entity_type
                FROM source_pages
                WHERE url=? AND source_name='Allakhazam'
                """,
                (canonical,),
            ).fetchone()
            if (
                existing is not None
                and str(existing["sha256"] or "") == digest
                and str(existing["entity_type"] or "") in recognized_types
            ):
                if version:
                    db.conn.execute(
                        "UPDATE source_pages SET source_version=? WHERE id=?",
                        (version, int(existing["id"])),
                    )
                result.unchanged += 1
                accepted_canonicals.add(canonical)
                continue

            try:
                imported = importer._import_html_text(raw, page.path, canonical)  # noqa: SLF001
            except ValueError:
                result.parse_errors += 1
                continue
            if version:
                db.conn.execute(
                    "UPDATE source_pages SET source_version=? WHERE id=?",
                    (version, int(imported.source_page_id)),
                )
            result.imported.append(imported)
            accepted_canonicals.add(canonical)

    return result


def temporary_recovery_text(result: TemporaryRecoveryResult) -> str:
    lines = [
        "EverQuestie Allakhazam temporary-page recovery",
        "",
        f"Mirror root: {result.root}",
        "Builder-only explicit recovery. Mirror files are read-only and never promoted in place.",
        f"Temporary HTML-like files: {result.temporary_files:,}",
        f"Likely-complete structured candidates: {result.candidates:,}",
        f"Imported structured pages: {result.changed:,}",
        f"Already imported / unchanged: {result.unchanged:,}",
        f"Read errors: {result.read_errors:,}",
        f"Parser rejects: {result.parse_errors:,}",
        f"Skipped unstable files: {result.skipped_unstable:,}",
        f"Skipped completed-page duplicates: {result.skipped_duplicate_completed:,}",
        f"Skipped duplicate temporary canonicals: {result.skipped_duplicate_temporary:,}",
        f"Skipped failed full-read revalidation: {result.skipped_revalidation:,}",
        "Mirror changed during classification scan: "
        + ("YES" if result.mirror_changed_during_scan else "no"),
    ]
    if result.by_status:
        lines += ["", "Classification status:"]
        lines.extend(f"  {name}: {count:,}" for name, count in sorted(result.by_status.items()))
    return "\n".join(lines)
