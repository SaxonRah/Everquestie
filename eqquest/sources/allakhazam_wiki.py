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

    def import_folder(self, folder: str | Path) -> WikiImportResult:
        root = Path(folder)
        if not root.is_dir():
            raise ValueError(f"Wiki mirror directory does not exist: {root}")
        result = WikiImportResult()
        with self.db.batch():
            for path in sorted(root.rglob("*.htm*")):
                if path.name.lower().endswith(".tmp"):
                    continue
                try:
                    raw = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    result.ignored += 1
                    continue
                canonical = extract_canonical_url(raw)
                if not canonical or not is_allakhazam_url(canonical):
                    result.ignored += 1
                    continue
                key = _wiki_key(canonical)
                if not key:
                    result.ignored += 1
                    continue

                digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
                existing = self.db.conn.execute(
                    "SELECT id, sha256 FROM source_pages WHERE url=?", (canonical,)
                ).fetchone()
                if existing is not None and existing["sha256"] == digest:
                    result.unchanged += 1
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
                    local_path=str(path.resolve()),
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
        return result
