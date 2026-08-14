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

    tests = ROOT / "tests" / "test_map_catalog.py"
    test_text = tests.read_text(encoding="utf-8")
    if "test_map_evidence_renderer_uses_portable_provenance" not in test_text:
        anchor = """    def test_same_catalog_source_can_move_without_duplicate_rows(self):\n"""
        addition = """    def test_map_evidence_renderer_uses_portable_provenance(self):\n        from eqquest.map_catalog import map_evidence_lines\n\n        self.catalog.index_root(self.root, source_name=\"Brewall\", source_version=\"2026-08\")\n        lines = map_evidence_lines(self.db, self.npc_id)\n        rendered = \"\\n\".join(lines)\n        self.assertIn(\"Map catalog evidence:\", rendered)\n        self.assertIn(\"Brewall:stonehive_1.txt\", rendered)\n        self.assertNotIn(str(self.root), rendered)\n\n"""
        if anchor not in test_text:
            raise RuntimeError("Map evidence test anchor not found")
        tests.write_text(test_text.replace(anchor, addition + anchor, 1), encoding="utf-8")

    print("portable map catalog follow-up applied")


if __name__ == "__main__":
    main()
