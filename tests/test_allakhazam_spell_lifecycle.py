from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from eqquest.allakhazam_mirror_importer import (
    AllakhazamMirrorImporter,
    normalize_allakhazam_mirror_href,
)
from eqquest.db import Database
from eqquest.entity_lifecycle import entity_expansion_evidence, entity_lifecycle_decision
from eqquest.entity_lifecycle_records import reconcile_allakhazam_spell_lifecycle
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.profile_lifecycle_audit import profile_lifecycle_audit


SPELL_URL = "https://everquest.allakhazam.com/db/spell.html?spell=111"


def spell_html(name: str = "Malaisement", expansion: str = "Original", *, quick_facts: bool = True) -> str:
    if quick_facts:
        facts = f"""
        <section class="spell-facts">
          <h3>Quick Facts</h3>
          <div><b>Scroll:</b> Spell: {name}</div>
          <hr>
          <div><b>Class Level</b><span>SHM 32</span></div>
          <hr>
          <div><b>Expansion:</b><img alt="{expansion}" src="/images/expansion.gif"></div>
          <hr>
          <div><b>Duration:</b><span>7.4 mins</span></div>
        </section>
        """
    else:
        facts = "<h3>Description</h3><p>No structured quick facts are present.</p>"
    return f"""<!doctype html>
    <html>
      <head>
        <title>{name} :: Spells :: EverQuest :: ZAM</title>
        <link rel="canonical" href="{SPELL_URL}">
      </head>
      <body>
        <h1>{name}</h1>
        {facts}
        <h3>Comments</h3>
        <p>A player comment says Expansion: The Serpent's Spine, which is not source lifecycle metadata.</p>
      </body>
    </html>
    """


class AllakhazamSpellLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        try:
            self.db.close()
        except Exception:
            pass
        self.tempdir.cleanup()

    def _write_spell(self, html: str) -> Path:
        path = self.root / "spell111.html"
        path.write_text(html, encoding="utf-8")
        return path

    def _mcp_source(self) -> int:
        return self.db.upsert_source_page(
            url="mcp://inventory/spells",
            title="MCP spells",
            entity_type="multi",
            sha256="mcp-spells",
            plain_text="",
            raw_html="",
            source_name="EverQuest Client via everquest1-mcp",
            source_kind="mcp_local_snapshot",
            source_key="spells",
        )

    def _canonical_spell(self, name: str = "Malaisement", spell_id: str = "111") -> int:
        source = self._mcp_source()
        return self.db.upsert_entity(
            kind="spell",
            name=name,
            source_page_id=source,
            external_id=spell_id,
            external_namespace="eqclient:spell",
            merge_by_name=False,
            data={"system": "spells"},
        )

    def test_mcp_first_exact_id_and_name_adds_lifecycle_without_overwriting_canonical_detail(self):
        spell_id = self._canonical_spell()
        detail_source = self.db.upsert_source_page(
            url="mcp://details/spells",
            title="MCP spell detail",
            entity_type="multi",
            sha256="mcp-details",
            plain_text="",
            raw_html="",
            source_name="EverQuest Client via everquest1-mcp",
            source_kind="mcp_local_details",
            source_key="details",
        )
        self.db.upsert_entity_detail(
            spell_id,
            source_page_id=detail_source,
            detail_format="mcp-json",
            detail_json={"name": "Malaisement", "mana": 100},
        )
        original_primary_source = int(self.db.entity(spell_id)["source_page_id"])

        result = AllakhazamMirrorImporter(self.db).import_saved_html(self._write_spell(spell_html()))

        self.assertEqual(result.kind, "spell")
        self.assertEqual(result.entity_id, spell_id)
        self.assertEqual(int(self.db.entity(spell_id)["source_page_id"]), original_primary_source)
        self.assertEqual(self.db.entity_detail(spell_id)["detail_json"], '{"name": "Malaisement", "mana": 100}')
        evidence = entity_expansion_evidence(self.db, spell_id)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].expansion, "Original")
        self.assertEqual(evidence[0].origin, "entity_lifecycle_records")
        self.assertEqual(evidence[0].source_kind, "local_mirror")
        self.assertTrue(entity_lifecycle_decision(self.db, spell_id, "p99").compatibility)
        external = self.db.entity_by_namespaced_external_id("allakhazam:spell", "spell:111")
        self.assertIsNotNone(external)
        self.assertEqual(int(external["id"]), spell_id)

    def test_allakhazam_first_preserves_unattached_record_then_exact_reconciles(self):
        result = AllakhazamMirrorImporter(self.db).import_saved_html(self._write_spell(spell_html()))
        self.assertEqual(result.entity_id, 0)
        self.assertEqual(int(self.db.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]), 0)
        row = self.db.conn.execute(
            "SELECT entity_id,source_external_id,source_entity_name,field_value FROM entity_lifecycle_records"
        ).fetchone()
        self.assertIsNone(row["entity_id"])
        self.assertEqual(row["source_external_id"], "spell:111")
        self.assertEqual(row["source_entity_name"], "Malaisement")
        self.assertEqual(row["field_value"], "Original")

        spell_id = self._canonical_spell()

        # Runtime/audit correctness does not depend on a write-time reconciliation pass.
        evidence = entity_expansion_evidence(self.db, spell_id)
        self.assertEqual([(e.expansion, e.origin) for e in evidence], [("Original", "entity_lifecycle_records")])
        audit = profile_lifecycle_audit(self.db)
        by_kind = {item.kind: item for item in audit.by_kind}
        self.assertEqual(by_kind["spell"].with_expansion_evidence, 1)
        self.assertEqual(by_kind["spell"].profile_available, 1)

        reconciled = reconcile_allakhazam_spell_lifecycle(self.db)
        self.assertEqual(reconciled.scanned, 1)
        self.assertEqual(reconciled.linked, 1)
        self.assertEqual(reconciled.name_mismatch, 0)
        attached = self.db.conn.execute("SELECT entity_id FROM entity_lifecycle_records").fetchone()
        self.assertEqual(int(attached["entity_id"]), spell_id)
        source_link = self.db.conn.execute(
            "SELECT 1 FROM entity_sources WHERE entity_id=? AND role='lifecycle'",
            (spell_id,),
        ).fetchone()
        self.assertIsNotNone(source_link)

    def test_numeric_id_without_exact_name_never_attaches(self):
        AllakhazamMirrorImporter(self.db).import_saved_html(self._write_spell(spell_html(name="Malaisement")))
        spell_id = self._canonical_spell(name="Different Spell")

        self.assertEqual(entity_expansion_evidence(self.db, spell_id), ())
        reconciled = reconcile_allakhazam_spell_lifecycle(self.db)
        self.assertEqual(reconciled.scanned, 1)
        self.assertEqual(reconciled.linked, 0)
        self.assertEqual(reconciled.name_mismatch, 1)
        self.assertIsNone(
            self.db.entity_by_namespaced_external_id("allakhazam:spell", "spell:111")
        )
        row = self.db.conn.execute("SELECT entity_id FROM entity_lifecycle_records").fetchone()
        self.assertIsNone(row["entity_id"])

    def test_comment_expansion_text_without_quick_facts_is_not_promoted(self):
        self._canonical_spell()
        AllakhazamMirrorImporter(self.db).import_saved_html(
            self._write_spell(spell_html(quick_facts=False))
        )
        self.assertEqual(
            int(self.db.conn.execute("SELECT COUNT(*) FROM entity_lifecycle_records").fetchone()[0]),
            0,
        )

    def test_spell_httrack_link_recovery_is_narrow_and_structured(self):
        source = "https://everquest.allakhazam.com/db/zone.html?zone=1"
        recovered = normalize_allakhazam_mirror_href(
            "spellA1B2.html?spell=111",
            source,
        )
        self.assertEqual(recovered, SPELL_URL)

    def test_finalized_snapshot_persists_exact_attachment_and_remains_queryable(self):
        AllakhazamMirrorImporter(self.db).import_saved_html(self._write_spell(spell_html(expansion="Omens of War")))
        spell_id = self._canonical_spell()
        self.db.close()

        snapshot = self.root / "everquestie-knowledge.sqlite3"
        report = create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="spell-lifecycle-test",
        )
        self.assertEqual(report.lifecycle_reconciliation["scanned"], 1)
        self.assertEqual(report.lifecycle_reconciliation["linked"], 1)

        conn = sqlite3.connect(snapshot.as_uri() + "?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT entity_id,field_value FROM entity_lifecycle_records"
            ).fetchone()
            self.assertEqual(int(row["entity_id"]), spell_id)
            self.assertEqual(row["field_value"], "Omens of War")
            source = conn.execute(
                """
                SELECT sp.source_name,sp.source_kind
                FROM entity_sources es
                JOIN source_pages sp ON sp.id=es.source_page_id
                WHERE es.entity_id=? AND es.role='lifecycle'
                """,
                (spell_id,),
            ).fetchone()
            self.assertEqual((source["source_name"], source["source_kind"]), ("Allakhazam", "local_mirror"))
        finally:
            conn.close()

        # Avoid tearDown closing an already closed builder handle.
        self.db = type("ClosedDB", (), {"close": lambda self: None})()


if __name__ == "__main__":
    unittest.main()
