from __future__ import annotations

import hashlib
import html as html_lib
import re
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

from .db import Database, normalize_name


ALLA_HOST = "everquest.allakhazam.com"
ENTITY_KINDS = {"quest", "npc", "item", "zone"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def is_allakhazam_url(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return p.scheme in {"http", "https"} and p.netloc.casefold() == ALLA_HOST


def allakhazam_search_url(query: str) -> str:
    return "https://everquest.allakhazam.com/search.html?q=" + urllib.parse.quote_plus(query)


def open_allakhazam_search(query: str) -> None:
    webbrowser.open(allakhazam_search_url(query))


def open_url(url: str) -> None:
    webbrowser.open(url)


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: "HtmlNode | None" = None
    children: list["HtmlNode | str"] = field(default_factory=list)

    def text(self, separator: str = " ") -> str:
        parts: list[str] = []

        def walk(node: "HtmlNode") -> None:
            for child in node.children:
                if isinstance(child, str):
                    value = " ".join(child.split())
                    if value:
                        parts.append(value)
                else:
                    walk(child)

        walk(self)
        return separator.join(parts).strip()

    def descendants(self, tag: str | None = None) -> Iterable["HtmlNode"]:
        for child in self.children:
            if isinstance(child, HtmlNode):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.descendants(tag)

    def first(self, tag: str) -> "HtmlNode | None":
        return next(self.descendants(tag), None)


class MiniDOMParser(HTMLParser):
    """Tiny stdlib DOM sufficient for Allakhazam's saved legacy HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        node = HtmlNode(tag, {k.casefold(): (v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


class VisibleTextParser(HTMLParser):
    BLOCKED = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked_depth = 0
        self._title_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.BLOCKED:
            self._blocked_depth += 1
        if tag == "title":
            self._title_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.BLOCKED and self._blocked_depth:
            self._blocked_depth -= 1
        if tag == "title" and self._title_depth:
            self._title_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._blocked_depth:
            return
        data = " ".join(data.split())
        if not data:
            return
        if self._title_depth:
            self.title_parts.append(data)
        self.text_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def text(self) -> str:
        return "\n".join(self.text_parts)


def infer_kind_and_external_id(url: str) -> tuple[str | None, str | None]:
    p = urllib.parse.urlparse(url)
    path = p.path.casefold()
    qs = urllib.parse.parse_qs(p.query)

    if path.endswith("/db/quest.html"):
        value = (qs.get("quest") or [None])[0]
        return "quest", f"quest:{value}" if value else None
    if path.endswith("/db/item.html"):
        value = (qs.get("item") or [None])[0]
        return "item", f"item:{value}" if value else None
    if path.endswith("/db/npc.html"):
        value = (qs.get("id") or [None])[0]
        return "npc", f"npc:{value}" if value else None
    if path.endswith("/db/zone.html") or path.endswith("/db/zones.html"):
        value = (qs.get("zstrat") or qs.get("id") or [None])[0]
        return "zone", f"zone:{value}" if value else None
    return None, None


def clean_title(title: str) -> str:
    title = html_lib.unescape(" ".join(title.split())).strip()
    if " :: " in title:
        title = title.split(" :: ", 1)[0].strip()
    title = re.sub(r"\s*[-|:]\s*(?:EverQuest|EQ).*?$", "", title, flags=re.I)
    return title.strip() or "Untitled Allakhazam page"


def short_quest_alias(name: str) -> str | None:
    # "Gubjak #1: Summon the Spirits" -> "Summon the Spirits"
    m = re.match(r"^.+?\s+#\d+\s*:\s*(.+)$", name)
    if m:
        return m.group(1).strip()
    return None


def extract_canonical_url(raw_html: str) -> str | None:
    patterns = [
        r'<link\s+[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)',
        r'<meta\s+[^>]*property=["\']og:url["\'][^>]*content=["\']([^"\']+)',
        r'<!--\s*saved from url=\([^)]*\)(https?://everquest\.allakhazam\.com/[^ ]+)\s*-->',
    ]
    for pattern in patterns:
        m = re.search(pattern, raw_html, re.I)
        if m:
            url = html_lib.unescape(m.group(1)).strip()
            if is_allakhazam_url(url):
                return url
    return None


COUNT_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}
COUNT_TOKEN = r"\d+|" + "|".join(COUNT_WORDS)


def parse_count(text: str | None, default: int = 1) -> int:
    if not text:
        return default
    if text.isdigit():
        return int(text)
    return COUNT_WORDS.get(text.casefold(), default)


def loose_name_key(name: str) -> str:
    words = re.findall(r"[a-z0-9']+", name.casefold())
    if words and words[0] in {"a", "an", "the"}:
        words = words[1:]
    out: list[str] = []
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 3 and word.endswith("es") and not word.endswith(("ses", "xes")):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return " ".join(out)


@dataclass(slots=True)
class ImportResult:
    source_page_id: int
    entity_id: int
    kind: str
    name: str
    external_id: str | None
    sha256: str
    relationships: int = 0
    discovered_entities: int = 0
    quest_steps: int = 0
    locations: int = 0


@dataclass(slots=True)
class MirrorImportResult:
    imported: list[ImportResult] = field(default_factory=list)
    unchanged: int = 0
    ignored: int = 0
    read_errors: int = 0

    @property
    def changed(self) -> int:
        return len(self.imported)


class AllakhazamImporter:
    def __init__(self, db: Database):
        self.db = db

    def import_saved_html(
        self,
        html_path: str | Path,
        source_url: str | None = None,
        *,
        kind_hint: str | None = None,
        name_hint: str | None = None,
    ) -> ImportResult:
        path = Path(html_path)
        raw = path.read_text(encoding="utf-8", errors="replace")
        return self._import_html_text(
            raw,
            path,
            source_url,
            kind_hint=kind_hint,
            name_hint=name_hint,
        )

    def _import_html_text(
        self,
        raw: str,
        html_path: str | Path,
        source_url: str | None = None,
        *,
        kind_hint: str | None = None,
        name_hint: str | None = None,
    ) -> ImportResult:
        source_url = (source_url or "").strip() or extract_canonical_url(raw)
        if not source_url or not is_allakhazam_url(source_url):
            raise ValueError(
                "Could not establish an everquest.allakhazam.com source URL. "
                "Paste the source URL or save a page containing its canonical URL."
            )

        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()

        visible = VisibleTextParser()
        visible.feed(raw)
        dom = MiniDOMParser()
        dom.feed(raw)

        inferred_kind, external_id = infer_kind_and_external_id(source_url)
        if inferred_kind not in ENTITY_KINDS:
            inferred_kind, external_id = self._infer_kind_and_external_id_from_document(
                dom.root, visible.title, source_url
            )
        kind = kind_hint or inferred_kind
        if kind not in ENTITY_KINDS:
            raise ValueError(
                "Could not infer whether this is a quest/NPC/item/zone page. "
                "Choose an entity type in the importer."
            )

        source_name = self._source_entity_name(dom.root, visible.title, kind)
        existing = self.db.entity_by_external_id(kind, external_id)
        if name_hint:
            name = name_hint
        elif existing is not None and existing["source_page_id"] is not None:
            # Preserve a user's earlier canonical naming choice on re-import.
            name = existing["name"]
        else:
            name = source_name

        source_page_id = self.db.upsert_source_page(
            url=source_url,
            title=visible.title,
            entity_type=kind,
            sha256=digest,
            plain_text=visible.text,
            raw_html=raw,
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=external_id or source_url,
            local_path=str(Path(html_path).resolve()),
        )

        entity_id = self.db.upsert_entity(
            kind=kind,
            name=name,
            source_page_id=source_page_id,
            source_url=source_url,
            external_id=external_id,
            notes="Imported from a user-saved Allakhazam HTML page.",
        )

        self.db.clear_page_derivatives(source_page_id)
        self.db.add_alias(entity_id, source_name, alias_type="source_title", source_page_id=source_page_id)
        if kind == "quest":
            alias = short_quest_alias(source_name)
            if alias:
                self.db.add_alias(entity_id, alias, alias_type="quest_short_name", source_page_id=source_page_id)

        stats = {"relationships": 0, "discovered": 0, "steps": 0, "locations": 0}
        if kind == "quest":
            self._extract_quest(dom.root, entity_id, source_page_id, source_url, stats)
        elif kind == "npc":
            self._extract_npc(dom.root, entity_id, source_page_id, source_url, stats)
        elif kind == "item":
            self._extract_item(dom.root, entity_id, source_page_id, source_url, stats)
        elif kind == "zone":
            self._extract_zone(dom.root, entity_id, source_page_id, source_url, stats)

        return ImportResult(
            source_page_id=source_page_id,
            entity_id=entity_id,
            kind=kind,
            name=name,
            external_id=external_id,
            sha256=digest,
            relationships=stats["relationships"],
            discovered_entities=stats["discovered"],
            quest_steps=stats["steps"],
            locations=stats["locations"],
        )

    def rebuild_imported_pages(self) -> list[ImportResult]:
        """Explicitly backfill graph data for legacy imported Allakhazam pages.

        This is a builder/developer migration helper. Normal EverQuestie startup must
        not call it because packaged knowledge snapshots are release artifacts rather
        than source-specific mutable caches.
        """
        results: list[ImportResult] = []
        for page in self.db.source_pages():
            # source_pages is now the general provenance table. Only rebuild the
            # structured DB pages owned by the Allakhazam entity importer; wiki
            # pages and future sources must not be reinterpreted as quest/NPC/etc.
            if page["source_name"] != "Allakhazam":
                continue
            source_url = page["url"]
            if not is_allakhazam_url(source_url):
                continue
            raw = page["raw_html"] or ""
            dom = MiniDOMParser()
            dom.feed(raw)
            kind, external_id = infer_kind_and_external_id(source_url)
            if kind not in ENTITY_KINDS:
                kind, external_id = self._infer_kind_and_external_id_from_document(
                    dom.root, page["title"] or "", source_url
                )
            if kind not in ENTITY_KINDS:
                continue
            existing = self.db.entity_by_external_id(kind, external_id)
            if existing is None:
                visible = VisibleTextParser()
                visible.feed(raw)
                name = self._source_entity_name(dom.root, visible.title or page["title"], kind)
                entity_id = self.db.upsert_entity(
                    kind=kind,
                    name=name,
                    source_page_id=int(page["id"]),
                    source_url=source_url,
                    external_id=external_id,
                    notes="Imported from a user-saved Allakhazam HTML page.",
                )
            else:
                entity_id = int(existing["id"])

            source_name = self._source_entity_name(dom.root, page["title"] or existing["name"], kind)
            self.db.clear_page_derivatives(int(page["id"]))
            self.db.add_alias(entity_id, source_name, alias_type="source_title", source_page_id=int(page["id"]))
            if kind == "quest":
                alias = short_quest_alias(source_name)
                if alias:
                    self.db.add_alias(entity_id, alias, alias_type="quest_short_name", source_page_id=int(page["id"]))

            stats = {"relationships": 0, "discovered": 0, "steps": 0, "locations": 0}
            if kind == "quest":
                self._extract_quest(dom.root, entity_id, int(page["id"]), source_url, stats)
            elif kind == "npc":
                self._extract_npc(dom.root, entity_id, int(page["id"]), source_url, stats)
            elif kind == "item":
                self._extract_item(dom.root, entity_id, int(page["id"]), source_url, stats)
            elif kind == "zone":
                self._extract_zone(dom.root, entity_id, int(page["id"]), source_url, stats)

            results.append(ImportResult(
                source_page_id=int(page["id"]),
                entity_id=entity_id,
                kind=kind,
                name=self.db.entity(entity_id)["name"],
                external_id=external_id,
                sha256=page["sha256"],
                relationships=stats["relationships"],
                discovered_entities=stats["discovered"],
                quest_steps=stats["steps"],
                locations=stats["locations"],
            ))
        return results

    def import_mirror(self, folder: str | Path) -> MirrorImportResult:
        """Incrementally compile a local HTTrack DB mirror.

        Finalized HTML is hashed before the relatively expensive DOM extraction.
        Pages already present with the same SHA-256 are skipped, which makes routine
        HTTrack refresh -> EverQuestie refresh cycles scale with changed pages rather
        than total mirror size.  HTTrack ``*.tmp`` files are deliberately ignored.
        """
        root = Path(folder)
        if not root.is_dir():
            raise ValueError(f"Allakhazam mirror directory does not exist: {root}")

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
                    and existing["entity_type"] in ENTITY_KINDS
                ):
                    summary.unchanged += 1
                    continue

                try:
                    result = self._import_html_text(raw, path, canonical)
                except ValueError:
                    # Index/search/advertising/helper pages are useful discovery roots
                    # for HTTrack but are not normalized entities yet.
                    summary.ignored += 1
                    continue
                summary.imported.append(result)
        return summary

    def import_folder(self, folder: str | Path) -> list[ImportResult]:
        """Backward-compatible wrapper returning only changed structured pages."""
        return self.import_mirror(folder).imported

    def _infer_kind_and_external_id_from_document(
        self, root: HtmlNode, title: str, source_url: str
    ) -> tuple[str | None, str | None]:
        """Fallback for legacy Allakhazam pages whose canonical URL is generic.

        In particular, saved Bestiary pages can advertise `search.html?id=...`
        even though their internal links and markup identify them as NPC pages.
        """
        parsed = urllib.parse.urlparse(source_url)
        qs = urllib.parse.parse_qs(parsed.query)
        numeric_id = (qs.get("id") or [None])[0]

        if self._first_with_class(root, "mobDisplay") or self._first_with_class(root, "npcinfo"):
            return "npc", f"npc:{numeric_id}" if numeric_id else None
        if self._first_with_class(root, "db-infobox") and "zone" in title.casefold():
            value = (qs.get("zstrat") or qs.get("id") or [None])[0]
            return "zone", f"zone:{value}" if value else None
        if self._node_by_id(root, "drops") and "item" in title.casefold():
            value = (qs.get("item") or qs.get("id") or [None])[0]
            return "item", f"item:{value}" if value else None
        if self._quest_table(root) is not None:
            value = (qs.get("quest") or qs.get("id") or [None])[0]
            return "quest", f"quest:{value}" if value else None
        return None, None

    def _source_entity_name(self, root: HtmlNode, title: str, kind: str) -> str:
        for h1 in root.descendants("h1"):
            value = h1.text()
            if value:
                return clean_title(value)
        return clean_title(title)

    @staticmethod
    def _node_by_id(root: HtmlNode, node_id: str) -> HtmlNode | None:
        for node in root.descendants():
            if node.attrs.get("id") == node_id:
                return node
        return None

    @staticmethod
    def _nodes_with_class(root: HtmlNode, class_name: str) -> list[HtmlNode]:
        return [
            node for node in root.descendants()
            if class_name in node.attrs.get("class", "").split()
        ]

    @staticmethod
    def _first_with_class(root: HtmlNode, class_name: str) -> HtmlNode | None:
        return next((
            node for node in root.descendants()
            if class_name in node.attrs.get("class", "").split()
        ), None)

    @staticmethod
    def _direct_children(node: HtmlNode, tag: str | None = None) -> list[HtmlNode]:
        return [
            child for child in node.children
            if isinstance(child, HtmlNode) and (tag is None or child.tag == tag)
        ]

    def _table_rows(self, table: HtmlNode | None) -> list[HtmlNode]:
        if table is None:
            return []
        tbody = next((c for c in self._direct_children(table) if c.tag == "tbody"), None)
        if tbody is not None:
            return self._direct_children(tbody, "tr")
        return self._direct_children(table, "tr")

    def _row_cells(self, row: HtmlNode) -> list[HtmlNode]:
        return [c for c in self._direct_children(row) if c.tag in {"td", "th"}]

    @staticmethod
    def _parse_level_range(text: str) -> tuple[int | None, int | None]:
        m = re.search(r"(?P<lo>\d+)\s*-\s*(?P<hi>\d+)", text)
        if m:
            return int(m.group("lo")), int(m.group("hi"))
        m = re.search(r"\b(?P<n>\d+)\b", text)
        if m:
            n = int(m.group("n"))
            return n, n
        return None, None

    @staticmethod
    def _parse_preview_counts(text: str) -> tuple[int | None, int | None]:
        m = re.search(r"Showing\s+(\d+)\s+out of\s+(\d+)", text, re.I)
        return (int(m.group(1)), int(m.group(2))) if m else (None, None)

    def _quest_table(self, root: HtmlNode) -> HtmlNode | None:
        for table in root.descendants("table"):
            text = table.text()
            if "Quest Started By:" in text and "Description:" in text:
                return table
        return None

    @staticmethod
    def _anchors(node: HtmlNode) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for a in node.descendants("a"):
            href = html_lib.unescape(a.attrs.get("href", "")).strip()
            text = a.text().strip()
            if href and text:
                out.append((text, href))
        return out

    def _field_rows(self, table: HtmlNode) -> dict[str, HtmlNode]:
        rows: dict[str, HtmlNode] = {}
        for tr in table.descendants("tr"):
            strong = tr.first("strong")
            if not strong:
                continue
            label = strong.text().strip().rstrip(":").casefold()
            if label:
                rows[label] = tr
        return rows

    @staticmethod
    def _row_value(row: HtmlNode, label: str) -> str:
        text = row.text()
        prefix = label.rstrip(":") + ":"
        if text.casefold().startswith(prefix.casefold()):
            return text[len(prefix):].strip()
        return text

    def _ensure_linked_entity(
        self,
        text: str,
        url: str,
        source_page_id: int,
        stats: dict[str, int],
    ) -> tuple[int | None, str | None]:
        if not is_allakhazam_url(url):
            return None, None
        kind, external_id = infer_kind_and_external_id(url)
        if kind not in ENTITY_KINDS:
            return None, None
        existing = self.db.entity_by_external_id(kind, external_id)
        entity_id = self.db.upsert_entity(
            kind=kind,
            name=text,
            source_url=url,
            external_id=external_id,
            notes="Discovered through a relationship on an imported Allakhazam page.",
            data={"discovered_from_source_page_id": source_page_id},
        )
        if existing is None:
            stats["discovered"] += 1
        return entity_id, kind

    def _add_link_relationships(
        self,
        quest_id: int,
        row: HtmlNode | None,
        relation: str,
        source_page_id: int,
        stats: dict[str, int],
    ) -> list[int]:
        ids: list[int] = []
        if row is None:
            return ids
        evidence = row.text()
        for text, url in self._anchors(row):
            entity_id, _kind = self._ensure_linked_entity(text, url, source_page_id, stats)
            if entity_id is None:
                continue
            self.db.upsert_relationship(
                quest_id, entity_id, relation,
                source_page_id=source_page_id,
                evidence=evidence,
            )
            stats["relationships"] += 1
            ids.append(entity_id)
        return ids

    def _best_entity(self, phrase: str, candidates: list[int]) -> int | None:
        phrase_key = loose_name_key(phrase)
        if not phrase_key:
            return None
        scored: list[tuple[int, int]] = []
        for entity_id in candidates:
            row = self.db.entity(entity_id)
            if not row:
                continue
            key = loose_name_key(row["name"])
            if phrase_key == key:
                score = 100
            elif phrase_key.startswith(key) or key.startswith(phrase_key):
                score = 80
            elif phrase_key in key or key in phrase_key:
                score = 60
            else:
                a, b = set(phrase_key.split()), set(key.split())
                score = 10 * len(a & b)
            scored.append((score, entity_id))
        scored.sort(reverse=True)
        return scored[0][1] if scored and scored[0][0] >= 20 else None

    def _extract_quest(
        self,
        root: HtmlNode,
        quest_id: int,
        source_page_id: int,
        source_url: str,
        stats: dict[str, int],
    ) -> None:
        table = self._quest_table(root)
        if table is None:
            return
        rows = self._field_rows(table)

        zone_ids = self._add_link_relationships(
            quest_id, rows.get("where"), "occurs_in", source_page_id, stats
        )
        starter_ids = self._add_link_relationships(
            quest_id, rows.get("who"), "started_by", source_page_id, stats
        )
        item_ids = self._add_link_relationships(
            quest_id, rows.get("quest items"), "quest_item", source_page_id, stats
        )
        creature_ids = self._add_link_relationships(
            quest_id, rows.get("related creatures"), "related_creature", source_page_id, stats
        )
        self._add_link_relationships(
            quest_id, rows.get("related quests"), "related_quest", source_page_id, stats
        )

        zone_name = None
        if zone_ids:
            z = self.db.entity(zone_ids[0])
            zone_name = z["name"] if z else None

        def scalar(label: str) -> str | None:
            row = rows.get(label.casefold())
            return self._row_value(row, label) if row else None

        level = scalar("Level")
        max_level = scalar("Maximum Level")
        data = {
            "quest_type": scalar("Quest Type"),
            "repeatable": scalar("Repeatable"),
            "group_size": scalar("Group Size"),
            "min_players": scalar("Min. # of Players"),
            "max_players": scalar("Max. # of Players"),
            "quest_goal": [t for t, _u in self._anchors(rows.get("quest goal"))] if rows.get("quest goal") else [],
            "factions_raised": [t for t, _u in self._anchors(rows.get("factions raised"))] if rows.get("factions raised") else [],
            "factions_lowered": [t for t, _u in self._anchors(rows.get("factions lowered"))] if rows.get("factions lowered") else [],
        }
        current = self.db.entity(quest_id)
        self.db.upsert_entity(
            kind="quest",
            name=current["name"],
            source_page_id=source_page_id,
            source_url=source_url,
            external_id=current["external_id"],
            zone=zone_name,
            level_min=int(level) if level and level.isdigit() else None,
            level_max=int(max_level) if max_level and max_level.isdigit() else None,
            notes=current["notes"],
            data=data,
        )

        # Explicit underlined task objectives are considerably safer to turn into
        # steps than free-form walkthrough prose/comments.
        objectives = [u.text().strip() for u in table.descendants("u") if u.text().strip()]
        for order, objective in enumerate(objectives, 1):
            rule, relation_specs = self._objective_rule(
                objective, quest_id, item_ids, creature_ids, starter_ids, source_page_id
            )
            self.db.add_quest_step(
                quest_id, order, objective,
                zone=zone_name,
                match=rule,
                source_page_id=source_page_id,
            )
            stats["steps"] += 1
            for target_id, relation, quantity, evidence, data_extra in relation_specs:
                self.db.upsert_relationship(
                    quest_id, target_id, relation,
                    quantity=quantity,
                    source_page_id=source_page_id,
                    evidence=evidence,
                    data=data_extra,
                )
                stats["relationships"] += 1

        self._extract_quest_locations(
            table, quest_id, zone_ids[0] if zone_ids else None,
            starter_ids, creature_ids, source_page_id, stats
        )

    def _add_relationship(
        self,
        source_id: int,
        target_id: int,
        relation: str,
        source_page_id: int,
        stats: dict[str, int],
        *,
        quantity: int | None = None,
        evidence: str = "",
        data: dict | None = None,
    ) -> None:
        self.db.upsert_relationship(
            source_id, target_id, relation,
            quantity=quantity,
            source_page_id=source_page_id,
            evidence=evidence,
            data=data or {"confidence": "structured"},
        )
        stats["relationships"] += 1

    def _extract_npc(
        self,
        root: HtmlNode,
        npc_id: int,
        source_page_id: int,
        source_url: str,
        stats: dict[str, int],
    ) -> None:
        current = self.db.entity(npc_id)
        if current is None:
            return

        mobtype = self._first_with_class(root, "mobtype")
        moblevel = self._first_with_class(root, "moblevel")
        npcinfo = self._first_with_class(root, "npcinfo")
        mobzones = self._first_with_class(root, "mobzones")
        mobquest = self._first_with_class(root, "mobquest")

        level_min = level_max = None
        if moblevel:
            m = re.search(r"Level\s*:\s*(\d+)", moblevel.text(), re.I)
            if m:
                level_min = level_max = int(m.group(1))

        data: dict[str, object] = {}
        if mobtype and mobtype.text():
            data["npc_type"] = mobtype.text()
        if moblevel:
            m = re.search(r"Expansion\s*:\s*(.*)$", moblevel.text(), re.I)
            if m and m.group(1).strip():
                data["expansion"] = m.group(1).strip()
        if npcinfo:
            info = npcinfo.text()
            m = re.search(r"NPC Added:\s*(.*?)\s+NPC Last Updated:", info, re.I)
            if m:
                data["npc_added"] = m.group(1).strip()
            m = re.search(r"NPC Last Updated:\s*(.*?)(?:\s+Known Habitats\s*:|\s+Quests\s*:|\s+Report a correction|$)", info, re.I)
            if m:
                data["npc_last_updated"] = m.group(1).strip()

        habitat_names: list[str] = []
        zone_name: str | None = None
        if mobzones:
            for text, url in self._anchors(mobzones):
                entity_id, kind = self._ensure_linked_entity(text, url, source_page_id, stats)
                if entity_id is None or kind != "zone":
                    continue
                habitat_names.append(text)
                zone_name = zone_name or text
                self._add_relationship(
                    npc_id, entity_id, "found_in", source_page_id, stats,
                    evidence=mobzones.text(),
                    data={"confidence": "structured", "source_field": "Known Habitats"},
                )
        if habitat_names:
            data["known_habitats"] = habitat_names

        if mobquest:
            quests: list[str] = []
            for text, url in self._anchors(mobquest):
                entity_id, kind = self._ensure_linked_entity(text, url, source_page_id, stats)
                if entity_id is None or kind != "quest":
                    continue
                quests.append(text)
                self._add_relationship(
                    npc_id, entity_id, "related_quest", source_page_id, stats,
                    evidence=mobquest.text(),
                    data={"confidence": "structured", "source_field": "Quests"},
                )
            if quests:
                data["related_quests"] = quests

        self.db.upsert_entity(
            kind="npc",
            name=current["name"],
            source_page_id=source_page_id,
            source_url=source_url,
            external_id=current["external_id"],
            zone=zone_name,
            level_min=level_min,
            level_max=level_max,
            notes=current["notes"],
            data=data,
        )

    def _extract_item(
        self,
        root: HtmlNode,
        item_id: int,
        source_page_id: int,
        source_url: str,
        stats: dict[str, int],
    ) -> None:
        current = self.db.entity(item_id)
        if current is None:
            return

        data: dict[str, object] = {}
        main = self._first_with_class(root, "nobgrd")
        main_text = main.text() if main else ""
        if main_text:
            m = re.search(r"Recommended level of\s+(\d+)", main_text, re.I)
            if m:
                data["recommended_level"] = int(m.group(1))
            m = re.search(r"Required level of\s+(\d+)", main_text, re.I)
            if m:
                data["required_level"] = int(m.group(1))
            m = re.search(r"Augmentation type:\s*(.*?)\s+Slot:", main_text, re.I)
            if m:
                data["augmentation_type"] = m.group(1).strip()
            m = re.search(r"Slot:\s*(.*?)(?:\s+AC:|\s+Recommended level|\s+Required level|\s+WT:|\s+Class:)", main_text, re.I)
            if m:
                data["slots"] = m.group(1).strip().split()
            m = re.search(r"Class:\s*(.*?)\s+Race:", main_text, re.I)
            if m:
                data["classes"] = m.group(1).strip().split()
            m = re.search(r"Race:\s*(.*?)(?:\s+Item Information:|$)", main_text, re.I)
            if m:
                data["races"] = m.group(1).strip().split()
            flags = []
            for flag in ("Lore Item", "No Trade", "Attuneable", "Heirloom", "Augmentation", "Magic Item"):
                if re.search(rf"\b{re.escape(flag)}\b", main_text, re.I):
                    flags.append(flag)
            if flags:
                data["flags"] = flags

        meta_table = self._node_by_id(root, "sortableTable0")
        if meta_table:
            metadata: dict[str, str] = {}
            for row in self._table_rows(meta_table):
                cells = self._row_cells(row)
                if len(cells) < 2:
                    continue
                label = cells[0].text().strip().rstrip(":").strip()
                value = cells[1].text().strip()
                if label and value:
                    metadata[label] = value
            if metadata:
                data["metadata"] = metadata
                mapping = {
                    "Item Lore": "item_lore",
                    "Item Type": "item_type",
                    "Stackable": "stackable",
                    "Merchant Value": "merchant_value",
                    "Source": "data_source",
                    "IC Last Updated": "ic_last_updated",
                    "Page Updated": "page_updated",
                }
                for label, key in mapping.items():
                    if label in metadata:
                        data[key] = metadata[label]

        # Establish canonical zone entities first from the dedicated zone list.
        zone_map: dict[str, int] = {}
        zone_heading = None
        for h2 in root.descendants("h2"):
            if h2.text().casefold().startswith("zone(s) found in"):
                zone_heading = h2
                break
        if zone_heading and zone_heading.parent:
            siblings = zone_heading.parent.children
            try:
                pos = siblings.index(zone_heading)
            except ValueError:
                pos = -1
            if pos >= 0:
                for sibling in siblings[pos + 1:]:
                    if isinstance(sibling, HtmlNode) and sibling.tag == "h2":
                        break
                    if not isinstance(sibling, HtmlNode):
                        continue
                    candidates = [sibling] if sibling.tag == "table" else list(sibling.descendants("table"))
                    for table in candidates:
                        for text, url in self._anchors(table):
                            kind, _ext = infer_kind_and_external_id(url)
                            if kind != "zone":
                                continue
                            zid, _ = self._ensure_linked_entity(text, url, source_page_id, stats)
                            if zid is None:
                                continue
                            zone_map[normalize_name(text)] = zid
                            self._add_relationship(
                                item_id, zid, "found_in", source_page_id, stats,
                                evidence="Zone(s) Found In",
                                data={"confidence": "structured", "source_field": "Zone(s) Found In"},
                            )
                    if zone_map:
                        break

        # Drops are grouped by a strong zone heading followed by an NPC table.
        drops = self._node_by_id(root, "drops")
        current_zone_name: str | None = None
        if drops:
            for child in drops.children:
                if isinstance(child, str):
                    continue
                if child.tag == "strong":
                    current_zone_name = child.text().strip()
                    continue
                if child.tag != "table" or not current_zone_name:
                    continue
                zid = zone_map.get(normalize_name(current_zone_name))
                for text, url in self._anchors(child):
                    kind, _ext = infer_kind_and_external_id(url)
                    if kind != "npc":
                        continue
                    npc_id, _ = self._ensure_linked_entity(text, url, source_page_id, stats)
                    if npc_id is None:
                        continue
                    self._add_relationship(
                        item_id, npc_id, "drops_from", source_page_id, stats,
                        evidence=f"Drops: {current_zone_name} / {text}",
                        data={"confidence": "structured", "zone": current_zone_name, "zone_entity_id": zid},
                    )
                    if zid is not None:
                        self._add_relationship(
                            npc_id, zid, "found_in", source_page_id, stats,
                            evidence=f"Item drop table grouped under {current_zone_name}",
                            data={"confidence": "structured", "derived_from": "item_drop_group"},
                        )

        self.db.upsert_entity(
            kind="item",
            name=current["name"],
            source_page_id=source_page_id,
            source_url=source_url,
            external_id=current["external_id"],
            notes=current["notes"],
            data=data,
        )

    def _extract_zone(
        self,
        root: HtmlNode,
        zone_id: int,
        source_page_id: int,
        source_url: str,
        stats: dict[str, int],
    ) -> None:
        current = self.db.entity(zone_id)
        if current is None:
            return
        data: dict[str, object] = {}
        level_min = level_max = None

        quick = self._first_with_class(root, "db-infobox")
        if quick:
            text = quick.text()
            data["hot_zone"] = "HOT ZONE" in text.upper()
            patterns = [
                ("zone_type", r"Type:\s*(.*?)\s+Expansion:"),
                ("expansion", r"Expansion:\s*(.*?)\s+Instanced:"),
                ("instanced", r"Instanced:\s*(.*?)\s+Keyed:"),
                ("keyed", r"Keyed:\s*(.*?)\s+Level Range:"),
            ]
            for key, pattern in patterns:
                m = re.search(pattern, text, re.I)
                if m:
                    data[key] = m.group(1).strip()
            m = re.search(r"Level Range:\s*(\d+)\s*-\s*(\d+)", text, re.I)
            if m:
                level_min, level_max = int(m.group(1)), int(m.group(2))
                data["level_range"] = [level_min, level_max]

        # Connected Zones is complete on the saved zone page.
        connected = self._node_by_id(root, "Connected_Zones_t")
        if connected:
            table = connected.first("table")
            for row in self._table_rows(table):
                cells = self._row_cells(row)
                if len(cells) < 2:
                    continue
                anchors = self._anchors(cells[0])
                if not anchors:
                    continue
                name, url = anchors[0]
                other_id, kind = self._ensure_linked_entity(name, url, source_page_id, stats)
                if other_id is None or kind != "zone":
                    continue
                direction = cells[1].text().strip()
                self._add_relationship(
                    zone_id, other_id, "connected_to", source_page_id, stats,
                    evidence=f"{name} / {direction}",
                    data={"confidence": "structured", "direction": direction},
                )

        # The following tab tables are previews. Preserve that fact so UI/query
        # code never mistakes a saved page's first 25 rows for an exhaustive list.
        preview_specs = [
            ("NPCs_t", "npc", "found_in"),
            ("Items_t", "item", "found_in"),
            ("Quests_Starting_t", "quest", "starts_in"),
            ("Quests_In_t", "quest", "occurs_in"),
        ]
        previews: dict[str, dict[str, int | None]] = {}
        for container_id, expected_kind, relation in preview_specs:
            container = self._node_by_id(root, container_id)
            if not container:
                continue
            shown, total = self._parse_preview_counts(container.text())
            previews[container_id] = {"shown": shown, "total": total}
            table = container.first("table")
            if table is None:
                continue
            for row in self._table_rows(table):
                cells = self._row_cells(row)
                if not cells:
                    continue
                entity_anchor: tuple[str, str] | None = None
                for cell in cells:
                    for text, url in self._anchors(cell):
                        kind, _ext = infer_kind_and_external_id(url)
                        if kind == expected_kind:
                            entity_anchor = (text, url)
                            break
                    if entity_anchor:
                        break
                if not entity_anchor:
                    continue
                name, url = entity_anchor
                eid, kind = self._ensure_linked_entity(name, url, source_page_id, stats)
                if eid is None or kind != expected_kind:
                    continue

                # Store useful level/type metadata from the structured preview row.
                if expected_kind == "npc" and len(cells) >= 3:
                    lo, hi = self._parse_level_range(cells[1].text())
                    npc = self.db.entity(eid)
                    self.db.upsert_entity(
                        kind="npc", name=npc["name"], source_url=npc["source_url"],
                        external_id=npc["external_id"], level_min=lo, level_max=hi,
                        notes=npc["notes"], data={"npc_type": cells[2].text().strip(), "zone_preview_source": current["name"]},
                    )
                elif expected_kind == "quest":
                    # Account for the leading icon cell in the zone quest tables.
                    level_cell = next((c for c in cells if re.fullmatch(r"\s*\d+\s*-\s*\d+\s*", c.text())), None)
                    if level_cell:
                        lo, hi = self._parse_level_range(level_cell.text())
                        quest = self.db.entity(eid)
                        self.db.upsert_entity(
                            kind="quest", name=quest["name"], source_url=quest["source_url"],
                            external_id=quest["external_id"], level_min=lo, level_max=hi,
                            notes=quest["notes"], data={"zone_preview_source": current["name"]},
                        )

                # The relation is stored from the specific thing to its zone.
                self._add_relationship(
                    eid, zone_id, relation, source_page_id, stats,
                    evidence=f"{container_id} preview: {name}",
                    data={"confidence": "structured", "preview": True, "shown": shown, "total": total},
                )

        if previews:
            data["previews"] = previews

        self.db.upsert_entity(
            kind="zone",
            name=current["name"],
            source_page_id=source_page_id,
            source_url=source_url,
            external_id=current["external_id"],
            level_min=level_min,
            level_max=level_max,
            notes=current["notes"],
            data=data,
        )

    def _objective_rule(
        self,
        objective: str,
        quest_id: int,
        item_ids: list[int],
        creature_ids: list[int],
        starter_ids: list[int],
        source_page_id: int,
    ) -> tuple[dict, list[tuple[int, str, int | None, str, dict]]]:
        text = " ".join(objective.split()).strip().rstrip(".")
        relations: list[tuple[int, str, int | None, str, dict]] = []

        m = re.match(rf"^Kill\s+(?P<count>{COUNT_TOKEN})\s+(?P<npc>.+)$", text, re.I)
        if m:
            count = parse_count(m.group("count"))
            phrase = m.group("npc").strip()
            target_id = self._best_entity(phrase, creature_ids + starter_ids)
            rule = {"event": "kill", "npc": phrase, "count": count}
            if target_id:
                row = self.db.entity(target_id)
                rule.update({"npc": row["name"], "npc_entity_id": target_id})
                self.db.add_alias(target_id, phrase, alias_type="objective", source_page_id=source_page_id)
                relations.append((target_id, "objective_kill", count, objective, {}))
            return rule, relations

        m = re.match(
            rf"^Loot\s+(?P<count>{COUNT_TOKEN})\s+(?P<item>.+?)(?:\s+from\s+(?P<npc>.+))?$",
            text, re.I,
        )
        if m:
            count = parse_count(m.group("count"))
            item_phrase = m.group("item").strip()
            item_id = self._best_entity(item_phrase, item_ids)
            rule = {"event": "loot", "item": item_phrase, "count": count}
            if item_id:
                item = self.db.entity(item_id)
                rule.update({"item": item["name"], "item_entity_id": item_id})
                self.db.add_alias(item_id, item_phrase, alias_type="objective", source_page_id=source_page_id)
                relations.append((item_id, "objective_loot", count, objective, {}))
            npc_phrase = (m.group("npc") or "").strip()
            npc_id = self._best_entity(npc_phrase, creature_ids) if npc_phrase else None
            if npc_id:
                self.db.add_alias(npc_id, npc_phrase, alias_type="objective", source_page_id=source_page_id)
                if item_id:
                    # This direction reads naturally for Where:/Find: on the item.
                    self.db.upsert_relationship(
                        item_id, npc_id, "drops_from",
                        source_page_id=source_page_id,
                        evidence=objective,
                        data={"derived_from": "quest_objective"},
                    )
                relations.append((npc_id, "objective_source_creature", None, objective, {}))
            return rule, relations

        m = re.match(
            rf"^(?:Bring back|Hand in|Give)\s+(?:(?P<count>{COUNT_TOKEN})\s+)?(?:pieces?\s+of\s+)?(?P<item>.+?)\s+to\s+(?P<npc>.+)$",
            text, re.I,
        )
        if m:
            count = parse_count(m.group("count"), 1)
            item_phrase = m.group("item").strip()
            npc_phrase = m.group("npc").strip()
            item_id = self._best_entity(item_phrase, item_ids)
            npc_id = self._best_entity(npc_phrase, starter_ids + creature_ids)
            rule: dict = {}
            if item_id:
                self.db.add_alias(item_id, item_phrase, alias_type="objective", source_page_id=source_page_id)
                relations.append((item_id, "objective_turn_in_item", count, objective, {}))
            if npc_id:
                npc = self.db.entity(npc_id)
                self.db.add_alias(npc_id, npc_phrase, alias_type="objective", source_page_id=source_page_id)
                rule = {"event": "npc_say", "npc": npc["name"], "npc_entity_id": npc_id, "count": 1}
                relations.append((npc_id, "objective_turn_in_to", None, objective, {}))
                if item_id:
                    self.db.upsert_relationship(
                        item_id, npc_id, "turn_in_to",
                        quantity=count,
                        source_page_id=source_page_id,
                        evidence=objective,
                        data={"quest_entity_id": quest_id},
                    )
            return rule, relations

        m = re.match(r"^(?:Speak with|Talk to|Hail)\s+(?P<npc>.+)$", text, re.I)
        if m:
            phrase = m.group("npc").strip()
            npc_id = self._best_entity(phrase, starter_ids + creature_ids)
            rule: dict = {}
            if npc_id:
                npc = self.db.entity(npc_id)
                self.db.add_alias(npc_id, phrase, alias_type="objective", source_page_id=source_page_id)
                rule = {"event": "npc_say", "npc": npc["name"], "npc_entity_id": npc_id, "count": 1}
                relations.append((npc_id, "objective_speak", None, objective, {}))
            return rule, relations

        return {}, relations

    def _extract_quest_locations(
        self,
        table: HtmlNode,
        quest_id: int,
        zone_id: int | None,
        starter_ids: list[int],
        creature_ids: list[int],
        source_page_id: int,
        stats: dict[str, int],
    ) -> None:
        # EQ /loc convention is Y, X, Z. Allakhazam's two-number quest coordinates
        # are stored as Y then X so they line up with SessionState's parsed /loc.
        italic_lines = [i.text().strip() for i in table.descendants("i") if i.text().strip()]
        for line in italic_lines:
            start = re.search(
                r"begins with\s+(.+?)\s+at location\s+([+-]?\d+(?:\.\d+)?),\s*([+-]?\d+(?:\.\d+)?)\s+in\s+(.+?)(?:\.|$)",
                line, re.I,
            )
            if start:
                npc_id = self._best_entity(start.group(1), starter_ids + creature_ids)
                if npc_id:
                    self.db.add_location(
                        npc_id, zone_entity_id=zone_id,
                        y=float(start.group(2)), x=float(start.group(3)),
                        label="quest starter",
                        source_page_id=source_page_id,
                        evidence=line,
                        data={"coordinate_convention": "eq_y_x"},
                    )
                    stats["locations"] += 1

            found = re.search(
                rf"Kill\s+(?:{COUNT_TOKEN})\s+(.+?).*?found at\s+([+-]?\d+(?:\.\d+)?),\s*([+-]?\d+(?:\.\d+)?)",
                line, re.I,
            )
            if found:
                npc_id = self._best_entity(found.group(1), creature_ids)
                if npc_id:
                    self.db.add_location(
                        npc_id, zone_entity_id=zone_id,
                        y=float(found.group(2)), x=float(found.group(3)),
                        label="quest target",
                        source_page_id=source_page_id,
                        evidence=line,
                        data={"coordinate_convention": "eq_y_x"},
                    )
                    stats["locations"] += 1

            handin = re.search(
                r"(?:Hand in|Give|Bring back).+?\s+to\s+(.+?)\s+at\s+([+-]?\d+(?:\.\d+)?),\s*([+-]?\d+(?:\.\d+)?)",
                line, re.I,
            )
            if handin:
                npc_id = self._best_entity(handin.group(1), starter_ids + creature_ids)
                if npc_id:
                    self.db.add_location(
                        npc_id, zone_entity_id=zone_id,
                        y=float(handin.group(2)), x=float(handin.group(3)),
                        label="turn-in",
                        source_page_id=source_page_id,
                        evidence=line,
                        data={"coordinate_convention": "eq_y_x"},
                    )
                    stats["locations"] += 1
