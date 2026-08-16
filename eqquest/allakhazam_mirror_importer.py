from __future__ import annotations

import hashlib
import html as html_lib
from pathlib import Path
import urllib.parse

from .allakhazam import (
    ALLA_HOST,
    ENTITY_KINDS,
    AllakhazamImporter,
    HtmlNode,
    ImportResult,
    MiniDOMParser,
    MirrorImportResult,
    VisibleTextParser,
    extract_canonical_url,
    is_allakhazam_url,
)
from .db import normalize_name
from .entity_lifecycle_records import (
    clear_lifecycle_records_for_source,
    upsert_lifecycle_record,
)


_DB_LINK_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("quest", ("quest", "id"), "quest.html"),
    ("item", ("item", "id"), "item.html"),
    ("npc", ("id",), "npc.html"),
    ("zone", ("zone", "zstrat", "id"), "zone.html"),
    ("spell", ("spell",), "spell.html"),
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


def _spell_numeric_id(url: str) -> str:
    if not is_allakhazam_url(url):
        return ""
    parsed = urllib.parse.urlparse(url)
    if not parsed.path.casefold().endswith("/db/spell.html"):
        return ""
    value = (urllib.parse.parse_qs(parsed.query).get("spell") or [""])[0]
    text = str(value or "").strip()
    return text if text.isdigit() else ""


def _walk_nodes(nodes: list[HtmlNode]) -> list[HtmlNode]:
    out: list[HtmlNode] = []
    for node in nodes:
        out.append(node)
        out.extend(node.descendants())
    return out


def _quick_facts_segment(root: HtmlNode) -> list[HtmlNode]:
    """Return only DOM nodes structurally following the Quick Facts heading.

    Spell comments and description prose can contain the word "expansion". Lifecycle
    extraction therefore fails closed unless the page exposes a Quick Facts heading and
    an exact Expansion label inside that structural section.
    """
    heading = next(
        (
            node
            for node in root.descendants()
            if node.tag in {"h2", "h3", "h4"}
            and normalize_name(node.text()) == "quick facts"
        ),
        None,
    )
    if heading is None or heading.parent is None:
        return []
    siblings = heading.parent.children
    try:
        start = siblings.index(heading) + 1
    except ValueError:
        return []
    segment: list[HtmlNode] = []
    for sibling in siblings[start:]:
        if not isinstance(sibling, HtmlNode):
            continue
        if sibling.tag in {"h2", "h3", "h4"}:
            break
        segment.append(sibling)
    return _walk_nodes(segment)


def _image_label(node: HtmlNode) -> str:
    for image in ([node] if node.tag == "img" else []) + list(node.descendants("img")):
        for key in ("alt", "title"):
            value = " ".join(str(image.attrs.get(key, "")).split()).strip()
            if value and normalize_name(value) not in {"image", "spell icon"}:
                return value
    return ""


def _quick_facts_expansion(root: HtmlNode) -> str:
    nodes = _quick_facts_segment(root)
    if not nodes:
        return ""
    for node in nodes:
        text = " ".join(node.text().split()).strip()
        folded = text.casefold()
        if folded.startswith("expansion:") and len(text) <= 160:
            remainder = text.split(":", 1)[1].strip()
            if remainder:
                return remainder
            image_value = _image_label(node)
            if image_value:
                return image_value
        if text.rstrip(":").strip().casefold() != "expansion":
            continue

        container = node.parent
        if container is not None:
            container_text = " ".join(container.text().split()).strip()
            if container_text.casefold().startswith("expansion:") and len(container_text) <= 160:
                remainder = container_text.split(":", 1)[1].strip()
                if remainder:
                    return remainder
            image_value = _image_label(container)
            if image_value:
                return image_value
            try:
                siblings = container.children
                position = siblings.index(node)
            except (ValueError, AttributeError):
                siblings = []
                position = -1
            if position >= 0:
                for sibling in siblings[position + 1 : position + 4]:
                    if isinstance(sibling, str):
                        value = " ".join(sibling.split()).strip()
                    else:
                        value = " ".join(sibling.text().split()).strip() or _image_label(sibling)
                    if value and value.casefold() != "expansion:":
                        return value
    return ""


class AllakhazamMirrorImporter(AllakhazamImporter):
    """Allakhazam importer with HTTrack recovery plus explicit lifecycle fields.

    The base importer remains the parser/normalizer owner for quest/NPC/item/zone pages.
    This subclass changes mirror anchor presentation, preserves reviewed lifecycle fields,
    and handles spell Quick Facts without turning Allakhazam spell IDs into canonical
    client identity by assumption.
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
        resolved_source = (
            str(source_url or "").strip() or extract_canonical_url(raw) or ""
        )
        if _spell_numeric_id(resolved_source):
            return self._import_spell_html(raw, html_path, resolved_source)

        previous = self._mirror_source_url
        self._mirror_source_url = resolved_source
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

    def _import_spell_html(self, raw: str, html_path, source_url: str) -> ImportResult:
        spell_id = _spell_numeric_id(source_url)
        if not spell_id:
            raise ValueError("Allakhazam spell page is missing a numeric spell ID")

        visible = VisibleTextParser()
        visible.feed(raw)
        dom = MiniDOMParser()
        dom.feed(raw)
        source_name = self._source_entity_name(dom.root, visible.title, "spell")
        if not source_name:
            raise ValueError("Allakhazam spell page has no source spell name")

        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
        source_key = f"spell:{spell_id}"
        source_page_id = self.db.upsert_source_page(
            url=source_url,
            title=visible.title,
            entity_type="spell",
            sha256=digest,
            plain_text=visible.text,
            raw_html=raw,
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=source_key,
            local_path=str(Path(html_path).resolve()),
        )
        clear_lifecycle_records_for_source(self.db, source_page_id)

        canonical = self.db.entity_by_namespaced_external_id("eqclient:spell", spell_id)
        canonical_id: int | None = None
        if canonical is not None and normalize_name(str(canonical["name"] or "")) == normalize_name(source_name):
            canonical_id = int(canonical["id"])
            self.db.link_entity_source(canonical_id, source_page_id, role="lifecycle")
            self.db.add_external_id(
                canonical_id,
                "allakhazam:spell",
                source_key,
                source_page_id=source_page_id,
            )

        expansion = _quick_facts_expansion(dom.root)
        if expansion:
            upsert_lifecycle_record(
                self.db,
                source_page_id=source_page_id,
                entity_kind="spell",
                source_external_id=source_key,
                source_entity_name=source_name,
                field_name="expansion",
                field_value=expansion,
                evidence="Allakhazam spell Quick Facts / Expansion",
                entity_id=canonical_id,
            )

        # ImportResult predates source records that can intentionally remain unattached.
        # A zero entity_id means the source fact was preserved but awaits exact post-
        # provider reconciliation; provider summaries use source_page_id/kind/counts.
        return ImportResult(
            source_page_id=source_page_id,
            entity_id=canonical_id or 0,
            kind="spell",
            name=source_name,
            external_id=source_key,
            sha256=digest,
        )

    def import_mirror(self, folder: str | Path) -> MirrorImportResult:
        """Incrementally compile recognized local HTTrack pages, including spell facts."""
        root = Path(folder)
        if not root.is_dir():
            raise ValueError(f"Allakhazam mirror directory does not exist: {root}")

        recognized_entity_types = set(ENTITY_KINDS) | {"spell"}
        summary = MirrorImportResult()
        with self.db.batch():
            for path in sorted(root.rglob("*.htm*")):
                if path.name.lower().endswith(".tmp"):
                    summary.ignored += 1
                    continue
                try:
                    raw = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    summary.read_errors += 1
                    continue

                canonical = extract_canonical_url(raw)
                if not canonical or not is_allakhazam_url(canonical):
                    summary.ignored += 1
                    continue

                digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
                existing = self.db.conn.execute(
                    """
                    SELECT id, sha256, entity_type
                    FROM source_pages
                    WHERE url=? AND source_name='Allakhazam'
                    """,
                    (canonical,),
                ).fetchone()
                if (
                    existing is not None
                    and existing["sha256"] == digest
                    and existing["entity_type"] in recognized_entity_types
                ):
                    summary.unchanged += 1
                    continue

                try:
                    result = self._import_html_text(raw, path, canonical)
                except ValueError:
                    summary.ignored += 1
                    continue
                summary.imported.append(result)
        return summary

    def rebuild_imported_pages(self) -> list[ImportResult]:
        """Rebuild legacy recognized pages plus stored Allakhazam spell lifecycle pages."""
        results = super().rebuild_imported_pages()
        for page in self.db.source_pages():
            if page["source_name"] != "Allakhazam" or page["entity_type"] != "spell":
                continue
            source_url = str(page["url"] or "")
            if not _spell_numeric_id(source_url):
                continue
            raw = str(page["raw_html"] or "")
            if not raw:
                continue
            path = str(page["local_path"] or "allakhazam-spell.html")
            results.append(self._import_spell_html(raw, path, source_url))
        return results

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
        """Merge one legacy source-owned lifecycle field onto its source entity."""
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
