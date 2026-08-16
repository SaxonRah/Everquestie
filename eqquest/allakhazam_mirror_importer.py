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
    """Allakhazam importer with HTTrack recovery plus explicit lifecycle fields.

    The base importer remains the parser/normalizer owner. This subclass changes
    anchor URL presentation while a mirror page is being extracted and preserves a
    small set of explicit source lifecycle fields needed by server-profile projection.
    It does not derive lifecycle from dates, names, locations, walkthrough prose, or
    other indirect evidence.
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

    def _merge_explicit_lifecycle(
        self,
        entity_id: int,
        *,
        source_page_id: int,
        source_url: str,
        key: str,
        value: str | None,
    ) -> None:
        """Merge one explicit source lifecycle field onto the canonical source entity."""
        cleaned = " ".join(str(value or "").split()).strip()
        if not cleaned:
            return
        current = self.db.entity(int(entity_id))
        if current is None:
            return
        self.db.upsert_entity(
            kind=str(current["kind"]),
            name=str(current["name"]),
            source_page_id=int(source_page_id),
            source_url=source_url,
            external_id=(str(current["external_id"]) if current["external_id"] else None),
            data={key: cleaned},
        )

    def _extract_quest(
        self,
        root: HtmlNode,
        quest_id: int,
        source_page_id: int,
        source_url: str,
        stats: dict[str, int],
    ) -> None:
        super()._extract_quest(root, quest_id, source_page_id, source_url, stats)

        table = self._quest_table(root)
        if table is None:
            return
        rows = self._field_rows(table)
        era_row = rows.get("era")
        era = self._row_value(era_row, "Era") if era_row is not None else None
        self._merge_explicit_lifecycle(
            quest_id,
            source_page_id=source_page_id,
            source_url=source_url,
            key="era",
            value=era,
        )

    def _extract_item(
        self,
        root: HtmlNode,
        item_id: int,
        source_page_id: int,
        source_url: str,
        stats: dict[str, int],
    ) -> None:
        super()._extract_item(root, item_id, source_page_id, source_url, stats)

        # Allakhazam item pages expose a structured metadata table. Preserve only its
        # explicit Expansion row as lifecycle evidence; do not infer from IC/Page
        # update dates or where the item happens to be found.
        meta_table = self._node_by_id(root, "sortableTable0")
        if meta_table is None:
            return
        for row in self._table_rows(meta_table):
            cells = self._row_cells(row)
            if len(cells) < 2:
                continue
            label = cells[0].text().strip().rstrip(":").strip()
            if label.casefold() != "expansion":
                continue
            expansion = cells[1].text().strip()
            self._merge_explicit_lifecycle(
                item_id,
                source_page_id=source_page_id,
                source_url=source_url,
                key="expansion",
                value=expansion,
            )
            break
