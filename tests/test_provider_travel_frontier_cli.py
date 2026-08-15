from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from eqquest.db import Database
from eqquest.provider_zone_travel import ProviderZoneTravelCatalog
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog
from tools.audit_provider_travel_frontier import main, open_read_only


class ProviderTravelFrontierCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "provider-frontier.sqlite3"
        db = Database(self.path)
        try:
            stone = db.upsert_entity(
                kind="zone", name="Stone Hive", external_id="400",
                external_namespace="eqclient:zone", merge_by_name=False,
            )
            blight = db.upsert_entity(
                kind="zone", name="Blightfire Moors", external_id="401",
                external_namespace="eqclient:zone", merge_by_name=False,
            )
            page = db.upsert_source_page(
                url="https://everquest.allakhazam.com/db/zone.html?zstrat=100",
                title="Stone Hive", entity_type="zone", sha256="stone",
                plain_text="Connected Zones", raw_html="", source_name="Allakhazam",
                source_kind="local_mirror", source_key="zone:100", source_version="cli-test",
            )
            p_stone = db.upsert_entity(
                kind="zone", name="Stone Hive", external_id="zone:100",
                external_namespace="allakhazam:zone", source_page_id=page, merge_by_name=False,
            )
            page2 = db.upsert_source_page(
                url="https://everquest.allakhazam.com/db/zone.html?zstrat=101",
                title="Blightfire Moors", entity_type="zone", sha256="blight",
                plain_text="Connected Zones", raw_html="", source_name="Allakhazam",
                source_kind="local_mirror", source_key="zone:101", source_version="cli-test",
            )
            p_blight = db.upsert_entity(
                kind="zone", name="Blightfire Moors", external_id="zone:101",
                external_namespace="allakhazam:zone", source_page_id=page2, merge_by_name=False,
            )
            db.upsert_relationship(
                p_stone, p_blight, "connected_to", source_page_id=page,
                evidence="Blightfire Moors / Both",
                data={"confidence": "structured", "direction": "Both"},
            )
            ProviderZoneReconciliationCatalog(db).reconcile()
            ProviderZoneTravelCatalog(db).reconcile()
            self.stone = stone
            self.blight = blight
        finally:
            db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_read_only_rejects_writes(self):
        conn = open_read_only(self.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM entities")
        finally:
            conn.close()

    def test_json_can_focus_one_exact_zone(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.path), "--zone", "Blightfire Moors", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status_counts"], {"compiled": 1})
        self.assertEqual(len(payload["zones"]), 1)
        zone = payload["zones"][0]
        self.assertEqual(zone["canonical_zone_entity_id"], self.blight)
        self.assertEqual(zone["incoming_count"], 1)
        self.assertEqual(zone["outgoing_count"], 1)
        self.assertEqual(zone["relationships"][0]["classification"], "compiled")

    def test_human_output_is_source_and_direction_aware(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.path), "--zone", "Stone Hive"])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("Stone Hive: compiled", text)
        self.assertIn("Allakhazam", text)
        self.assertIn("direction=Both / both", text)
        self.assertIn("canonical outgoing / incoming: 1 / 1", text)


if __name__ == "__main__":
    unittest.main()
