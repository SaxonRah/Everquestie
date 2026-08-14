from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if new and new in text:
            return
        raise RuntimeError(f"Expected patch anchor not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    mapview = ROOT / "eqquest" / "mapview.py"
    text = mapview.read_text(encoding="utf-8")
    text = text.replace("        self.after(700, self.ensure_map_catalog)\n", "")
    text = text.replace("        self.after(50, self.ensure_map_catalog)\n", "")
    mapview.write_text(text, encoding="utf-8")

    replace_once(
        mapview,
        """                self.load_map(chosen.path)\n                self.after(80, lambda: self._center_map_point(chosen.x, chosen.y))\n                self.lookup_status.set(f\"Opened linked map evidence for {chosen.text}\")\n                return\n""",
        """                local_path = self._catalog_hit_local_path(chosen)\n                if local_path is None:\n                    self.lookup_status.set(\n                        f\"Linked catalog evidence found for {chosen.text}, but that map file is not present in the selected local map pack.\"\n                    )\n                    return\n                self.load_map(local_path)\n                self.after(80, lambda: self._center_map_point(chosen.x, chosen.y))\n                self.lookup_status.set(f\"Opened linked map evidence for {chosen.text}\")\n                return\n""",
    )

    catalog = ROOT / "eqquest" / "map_catalog.py"
    replace_once(
        catalog,
        """            SELECT ml.*,ms.path FROM map_labels ml\n            JOIN map_sources ms ON ms.id=ml.source_id\n            WHERE ml.linked_entity_id=?\n            ORDER BY ml.zone_name,ml.map_stem,ml.layer,ml.source_line\n            LIMIT ?\n""",
        """            SELECT ml.*,ms.path,ms.source_name,ms.source_version,ms.source_key\n            FROM map_labels ml\n            JOIN map_sources ms ON ms.id=ml.source_id\n            WHERE ml.linked_entity_id=?\n            ORDER BY ml.zone_name,ml.map_stem,ml.layer,ml.source_line\n            LIMIT ?\n""",
    )
    replace_once(
        catalog,
        'return [self._hit(row, (0, i), "linked local map evidence") for i, row in enumerate(rows)]',
        'return [self._hit(row, (0, i), "linked map catalog evidence") for i, row in enumerate(rows)]',
    )
    replace_once(
        catalog,
        """        query = parse_local_query(raw_query)\n        if query.source:\n            src = normalize_name(query.source)\n            if not any(token in src for token in (\"map\", \"good\", \"brewall\", \"everquest\")):\n                return []\n\n        requested_zone = query.zone\n""",
        """        query = parse_local_query(raw_query)\n        source_filter = normalize_name(query.source or \"\")\n        if source_filter in {\"map\", \"maps\", \"map catalog\"}:\n            source_filter = \"\"\n\n        requested_zone = query.zone\n""",
    )
    replace_once(
        catalog,
        """        for row in rows:\n            zone_norm = normalize_map_name(str(row[\"zone_name\"] or \"\"))\n""",
        """        for row in rows:\n            if source_filter and source_filter not in normalize_name(str(row[\"source_name\"] or \"\")):\n                continue\n            zone_norm = normalize_map_name(str(row[\"zone_name\"] or \"\"))\n""",
    )

    tests = ROOT / "tests" / "test_map_catalog.py"
    test_text = tests.read_text(encoding="utf-8")
    if "test_map_evidence_renderer_uses_portable_provenance" not in test_text:
        anchor = """    def test_same_catalog_source_can_move_without_duplicate_rows(self):\n"""
        addition = """    def test_map_evidence_renderer_uses_portable_provenance(self):\n        from eqquest.map_catalog import map_evidence_lines\n\n        self.catalog.index_root(self.root, source_name=\"Brewall\", source_version=\"2026-08\")\n        lines = map_evidence_lines(self.db, self.npc_id)\n        rendered = \"\\n\".join(lines)\n        self.assertIn(\"Map catalog evidence:\", rendered)\n        self.assertIn(\"Brewall:stonehive_1.txt\", rendered)\n        self.assertNotIn(str(self.root), rendered)\n\n"""
        if anchor not in test_text:
            raise RuntimeError("Map evidence test anchor not found")
        tests.write_text(test_text.replace(anchor, addition + anchor, 1), encoding="utf-8")

    test_text = tests.read_text(encoding="utf-8")
    if "test_source_filter_uses_catalog_source_name" not in test_text:
        anchor = """    def test_type_only_query_does_not_invent_map_entity_types(self):\n"""
        addition = """    def test_source_filter_uses_catalog_source_name(self):\n        self.catalog.index_root(self.root, source_name=\"Brewall\")\n        self.assertTrue(self.catalog.search('source:Brewall Warwing'))\n        self.assertEqual(self.catalog.search('source:Good Warwing'), [])\n        self.assertTrue(self.catalog.search('source:map Warwing'))\n\n"""
        if anchor not in test_text:
            raise RuntimeError("Source filter test anchor not found")
        tests.write_text(test_text.replace(anchor, addition + anchor, 1), encoding="utf-8")

    print("portable map catalog follow-up applied")


if __name__ == "__main__":
    main()
