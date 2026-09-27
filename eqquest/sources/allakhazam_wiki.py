from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import urllib.parse

from ..allakhazam import VisibleTextParser, extract_canonical_url, is_allakhazam_url
from ..db import Database


@dataclass(slots=True)
class WikiImportResult:
    imported: int = 0
    unchanged: int = 0
    ignored: int = 0
    cancelled: bool = False

    @property
    def processed(self) -> int:
        return self.imported + self.unchanged + self.ignored


def _wiki_key(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or ""
    if path.startswith("/wiki/") and len(path) > len("/wiki/"):
        return urllib.parse.unquote(path[len("/wiki/"):])
    if path.endswith("/wiki.html"):
        qs = urllib.parse.parse_qs(parsed.query)
        for key in ("i", "wikit", "h"):
            value = (qs.get(key) or [""])[0]
            if value:
                return urllib.parse.unquote(value)
    return None


class AllakhazamWikiImporter:
    """Index a local HTTrack Allakhazam wiki mirror into EverQuestie's DB."""

    def __init__(self, db: Database):
        self.db = db

    def import_folder(
        self,
        folder: str | Path,
        *,
        progress=None,
        cancelled=None,
        progress_every: int = 250,
    ) -> WikiImportResult:
        root = Path(folder)
        if not root.is_dir():
            raise ValueError(f"Wiki mirror directory does not exist: {root}")

        result = WikiImportResult()
        report_every = max(1, int(progress_every))
        last_reported = 0

        def report(path=None, *, force: bool = False) -> None:
            nonlocal last_reported
            if progress is None:
                return
            processed = result.processed
            if not force and processed % report_every != 0:
                return
            if not force and processed == last_reported:
                return
            progress(result, path)
            last_reported = processed

        with self.db.batch():
            for path in root.rglob("*.htm*"):
                if cancelled is not None and cancelled():
                    result.cancelled = True
                    break
                if path.name.lower().endswith(".tmp"):
                    result.ignored += 1
                    report(path)
                    continue

                try:
                    stat = path.stat()
                except OSError:
                    result.ignored += 1
                    report(path)
                    continue
                local_path = str(path.resolve())

                cached = self.db.conn.execute(
                    """
                    SELECT id
                    FROM source_pages
                    WHERE source_name='Allakhazam Wiki'
                      AND local_path=?
                      AND local_mtime_ns=?
                      AND local_size=?
                    LIMIT 1
                    """,
                    (local_path, int(stat.st_mtime_ns), int(stat.st_size)),
                ).fetchone()
                if cached is not None:
                    result.unchanged += 1
                    report(path)
                    continue

                try:
                    raw = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    result.ignored += 1
                    report(path)
                    continue
                canonical = extract_canonical_url(raw)
                if not canonical or not is_allakhazam_url(canonical):
                    result.ignored += 1
                    report(path)
                    continue
                key = _wiki_key(canonical)
                if not key:
                    result.ignored += 1
                    report(path)
                    continue

                digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
                existing = self.db.conn.execute(
                    "SELECT id, sha256 FROM source_pages WHERE url=?", (canonical,)
                ).fetchone()
                if existing is not None and existing["sha256"] == digest:
                    self.db.conn.execute(
                        """
                        UPDATE source_pages
                        SET local_path=?, local_mtime_ns=?, local_size=?
                        WHERE id=?
                        """,
                        (
                            local_path,
                            int(stat.st_mtime_ns),
                            int(stat.st_size),
                            int(existing["id"]),
                        ),
                    )
                    result.unchanged += 1
                    report(path)
                    continue

                visible = VisibleTextParser()
                visible.feed(raw)
                title = visible.title or key.replace("_", " ")
                source_id = self.db.upsert_source_page(
                    url=canonical,
                    title=title,
                    entity_type="wiki",
                    sha256=digest,
                    plain_text=visible.text,
                    raw_html=raw,
                    source_name="Allakhazam Wiki",
                    source_kind="local_mirror",
                    source_key=key,
                    local_path=local_path,
                )
                self.db.conn.execute(
                    """
                    UPDATE source_pages
                    SET local_mtime_ns=?, local_size=?
                    WHERE id=?
                    """,
                    (int(stat.st_mtime_ns), int(stat.st_size), int(source_id)),
                )
                self.db.upsert_entity(
                    kind="wiki",
                    name=title,
                    source_page_id=source_id,
                    source_url=canonical,
                    external_id=key,
                    notes="Indexed from the player's local Allakhazam wiki mirror.",
                    data={"wiki_key": key},
                )
                result.imported += 1
                report(path)

        report(None, force=True)
        return result

