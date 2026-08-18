from __future__ import annotations

import contextlib
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest

from eqquest.allakhazam_mirror_audit import audit_allakhazam_mirror
from eqquest.allakhazam_normalization_delta import allakhazam_normalization_delta
from eqquest.db import Database
from eqquest.entity_lifecycle_records import upsert_lifecycle_record
from eqquest.knowledge_coverage import provider_normalization_coverage
from tools.audit_allakhazam_normalization_delta import main


class AllakhazamNormalizationDeltaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "knowledge.sqlite3"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _source_page(
        db: Database,
        *,
        kind: str,
        key: str,
        url: str,
    ) -> int:
        return db.upsert_source_page(
            url=url,
            title=f"{kind} {key}",
            entity_type=kind,
            sha256=f"sha-{kind}-{key}",
            plain_text=f"{kind} fixture",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=key,
        )

    def _populate_delta_fixture(self) -> None:
        db = Database(self.db_path)
        try:
            quest_page = self._source_page(
                db,
                kind="quest",
                key="quest:1",
                url="https://everquest.allakhazam.com/db/quest.html?quest=1",
            )
            db.upsert_entity(
                kind="quest",
                name="Persisted Quest",
                source_page_id=quest_page,
                source_url="https://everquest.allakhazam.com/db/quest.html?quest=1",
                external_id="quest:1",
            )

            # Persisted source page with no derivative: this is the normalization gap.
            self._source_page(
                db,
                kind="npc",
                key="npc:2",
                url="https://everquest.allakhazam.com/db/npc.html?id=2",
            )

            item_page = self._source_page(
                db,
                kind="item",
                key="item:3",
                url="https://everquest.allakhazam.com/db/item.html?item=3",
            )
            db.upsert_entity(
                kind="item",
                name="Persisted Item",
                source_page_id=item_page,
                source_url="https://everquest.allakhazam.com/db/item.html?item=3",
                external_id="item:3",
            )

            spell_page = self._source_page(
                db,
                kind="spell",
                key="spell:4",
                url="https://everquest.allakhazam.com/db/spell.html?spell=4",
            )
            # A lifecycle source fact is deliberately valid without canonical attachment.
            upsert_lifecycle_record(
                db,
                source_page_id=spell_page,
                entity_kind="spell",
                source_external_id="spell:4",
                source_entity_name="Unattached Spell",
                field_name="expansion",
                field_value="Original",
                evidence="Quick Facts / Expansion",
                entity_id=None,
            )
        finally:
            db.close()

    @staticmethod
    def _mirror_payload() -> dict[str, object]:
        return {
            "importable_pages": 5,
            "temporary_files": 0,
            "read_errors": 0,
            "pages_by_kind": {
                "quest": 2,
                "npc": 1,
                "item": 1,
                "zone": 0,
                "spell": 1,
            },
            "spell_pages_with_expansion": 1,
        }

    def test_completed_mirror_audit_uses_importer_document_fallback(self) -> None:
        mirror = self.root / "mirror"
        mirror.mkdir()
        (mirror / "legacy-bestiary.html").write_text(
            """
            <html>
              <head>
                <title>Legacy Goblin :: Bestiary :: EverQuest :: ZAM</title>
                <link rel="canonical" href="https://everquest.allakhazam.com/search.html?id=44">
              </head>
              <body><div class="mobDisplay"><h1>Legacy Goblin</h1></div></body>
            </html>
            """,
            encoding="utf-8",
        )

        audit = audit_allakhazam_mirror(mirror)
        self.assertEqual(audit.importable_pages, 1)
        self.assertEqual(audit.unclassified_canonical, 0)
        self.assertEqual(dict(audit.pages_by_kind), {"npc": 1})

    def test_lifecycle_only_spell_page_counts_as_normalized(self) -> None:
        db = Database(self.db_path)
        try:
            spell_page = self._source_page(
                db,
                kind="spell",
                key="spell:99",
                url="https://everquest.allakhazam.com/db/spell.html?spell=99",
            )
            upsert_lifecycle_record(
                db,
                source_page_id=spell_page,
                entity_kind="spell",
                source_external_id="spell:99",
                source_entity_name="Lifecycle Only",
                field_name="expansion",
                field_value="Original",
                entity_id=None,
            )
            coverage = provider_normalization_coverage(
                db, "Allakhazam", "local_mirror"
            )
        finally:
            db.close()

        self.assertEqual(coverage.source_pages, 1)
        self.assertEqual(coverage.normalized_pages, 1)
        self.assertEqual(coverage.lifecycle_records, 1)
        self.assertEqual(dict(coverage.normalized_page_types), {"spell": 1})
        self.assertEqual(coverage.entity_links, 0)

    def test_delta_separates_capture_gap_from_normalization_gap(self) -> None:
        self._populate_delta_fixture()
        db = Database(self.db_path)
        try:
            report = allakhazam_normalization_delta(db, self._mirror_payload())
        finally:
            db.close()

        by_kind = {row.kind: row for row in report.kinds}
        self.assertEqual(report.mirror_importable_pages, 5)
        self.assertEqual(report.source_pages, 4)
        self.assertEqual(report.normalized_pages, 3)
        self.assertEqual(report.captured_not_persisted, 1)
        self.assertEqual(report.persisted_not_normalized, 1)
        self.assertEqual(by_kind["quest"].captured_pages, 2)
        self.assertEqual(by_kind["quest"].persisted_pages, 1)
        self.assertEqual(by_kind["quest"].captured_not_persisted, 1)
        self.assertEqual(by_kind["npc"].persisted_not_normalized, 1)
        self.assertEqual(by_kind["spell"].normalized_pages, 1)
        self.assertEqual(report.lifecycle_records, 1)

    def test_cli_reuses_json_artifact_and_database_read_only(self) -> None:
        self._populate_delta_fixture()
        mirror_json = self.root / "mirror-audit.json"
        output = self.root / "reports" / "normalization-delta.json"
        mirror_json.write_text(
            json.dumps(self._mirror_payload()),
            encoding="utf-8",
        )
        before = sha256(self.db_path.read_bytes()).hexdigest()
        wal = Path(str(self.db_path) + "-wal")
        shm = Path(str(self.db_path) + "-shm")
        wal_before = wal.read_bytes() if wal.exists() else None
        shm_before = shm.read_bytes() if shm.exists() else None

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(
                [
                    str(mirror_json),
                    str(self.db_path),
                    "--json",
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        written = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload, written)
        self.assertEqual(payload["captured_not_persisted"], 1)
        self.assertEqual(payload["persisted_not_normalized"], 1)
        self.assertEqual(payload["lifecycle_records"], 1)
        self.assertEqual(sha256(self.db_path.read_bytes()).hexdigest(), before)
        self.assertEqual(wal.read_bytes() if wal.exists() else None, wal_before)
        self.assertEqual(shm.read_bytes() if shm.exists() else None, shm_before)

    def test_inconsistent_mirror_report_fails_closed(self) -> None:
        self._populate_delta_fixture()
        payload = self._mirror_payload()
        payload["importable_pages"] = 999
        mirror_json = self.root / "bad-mirror-audit.json"
        mirror_json.write_text(json.dumps(payload), encoding="utf-8")

        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            code = main([str(mirror_json), str(self.db_path)])

        self.assertEqual(code, 2)
        self.assertIn("internally inconsistent", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
