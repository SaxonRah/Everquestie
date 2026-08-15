from __future__ import annotations

import html as html_lib
import urllib.parse

from .allakhazam import (
    ALLA_HOST,
    AllakhazamImporter,
    HtmlNode,
    extract_canonical_url,
    is_allakhazam_url,
)


_DB_LINK_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("quest", ("quest", "id"), "quest.html"),
    ("item", ("item", "id"), "item.html"),
    ("npc", ("id",), "npc.html"),
    ("zone", ("zone", "zstrat", "id"), "zone.html"),
)


def normalize_allakhazam_mirror_href(href: str, source_url: str) -> str:
    """Recover a safe source URL from an HTTrack-rewritten relationship href.

    HTTrack's default mirror mode rewrites same-site links to relative local filenames.
    Query-bearing pages can also receive a short hash in the local basename while the
    original query string is retained.  EverQuestie needs the source URL identity, not
    the mirror filename, before its structured relationship extractor can classify the
    target.

    This helper is intentionally narrow:

    * only http(s) URLs resolving to ``everquest.allakhazam.com`` are canonicalized;
    * relative/root-relative/protocol-relative links are resolved against the page's
      already-proven canonical Allakhazam URL;
    * only known ``/db/`` entity basenames with their expected structured query keys
      may have an HTTrack hash/local suffix removed;
    * non-web schemes and external hosts are never promoted to Allakhazam evidence.
    """
    raw = html_lib.unescape(str(href or "")).strip()
    base = str(source_url or "").strip()
    if not raw or raw.startswith("#") or not is_allakhazam_url(base):
        return raw

    parsed_raw = urllib.parse.urlparse(raw)
    if parsed_raw.scheme and parsed_raw.scheme.casefold() not in {"http", "https"}:
        return raw

    if raw.startswith("//"):
        candidate = "https:" + raw
    elif parsed_raw.scheme:
        candidate = raw
    else:
        candidate = urllib.parse.urljoin(base, raw)

    if not is_allakhazam_url(candidate):
        return candidate

    parsed = urllib.parse.urlparse(candidate)
    path = parsed.path or ""
    if "/db/" not in path.casefold():
        return candidate

    query = urllib.parse.parse_qs(parsed.query)
    basename = path.rsplit("/", 1)[-1]
    folded_basename = basename.casefold()
    canonical_basename: str | None = None

    for prefix, query_keys, canonical in _DB_LINK_RULES:
        # Standard links are left untouched.  For HTTrack's default K0 form, the
        # rewritten basename still starts with the source page stem (for example
        # zone4B54.html?zone=155).  Requiring both that prefix and a known query key
        # prevents arbitrary local filenames from becoming provider entities.
        if not folded_basename.startswith(prefix):
            continue
        if not any(query.get(key) for key in query_keys):
            continue
        canonical_basename = canonical
        break

    if canonical_basename is None or folded_basename == canonical_basename:
        return candidate

    parent = path.rsplit("/", 1)[0]
    canonical_path = f"{parent}/{canonical_basename}" if parent else f"/{canonical_basename}"
    return urllib.parse.urlunparse(
        (
            parsed.scheme,
            ALLA_HOST,
            canonical_path,
            parsed.params,
            parsed.query,
            "",
        )
    )


class AllakhazamMirrorImporter(AllakhazamImporter):
    """Allakhazam importer with HTTrack link recovery scoped to mirror builds.

    The base importer remains the parser/normalizer owner.  This subclass changes only
    anchor URL presentation while a mirror page is being extracted; all entity,
    relationship, provenance, quest, location and direction semantics stay in the base
    importer.
    """

    def __init__(self, db):
        super().__init__(db)
        self._mirror_source_url = ""

    def _import_html_text(
        self,
        raw: str,
        html_path,
        source_url: str | None = None,
        *,
        kind_hint: str | None = None,
        name_hint: str | None = None,
    ):
        previous = self._mirror_source_url
        self._mirror_source_url = (
            str(source_url or "").strip() or extract_canonical_url(raw) or ""
        )
        try:
            return super()._import_html_text(
                raw,
                html_path,
                source_url,
                kind_hint=kind_hint,
                name_hint=name_hint,
            )
        finally:
            self._mirror_source_url = previous

    def _anchors(self, node: HtmlNode) -> list[tuple[str, str]]:
        anchors = super()._anchors(node)
        if not self._mirror_source_url:
            return anchors
        return [
            (
                text,
                normalize_allakhazam_mirror_href(url, self._mirror_source_url),
            )
            for text, url in anchors
        ]
