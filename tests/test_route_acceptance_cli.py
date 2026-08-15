from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from eqquest.db import Database
from eqquest.zone_travel import ZoneTravelCatalog
from tools.audit_route_acceptance import main, open_read_only


class RouteAcceptanceCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "route-acceptance.sqlite3"
        db = Database(self.path)
        try:
            hole = db.upsert_entity(
                kind="zone",
                name="The Hole",
                external_id="39",
                external_namespace="eqclient:zone",
            )
            paineel = db.upsert_entity(
                kind="zone",
                name="Paineel",
                external_id="75",
                external_namespace="eqclient:zone",
            )
            feldax = db.upsert_entity(
                kind="zone",
                name="Feldax Hive",
                external_id="5000",
                external_namespace="eqclient:zone",
            )
            ZoneTravelCatalog(db).add_provider_connection(
                feldax,
                paineel,
                connection_kind="zone_connection",
                source_name="CLI regression topology",
                source_kind="test_confirmed_topology",
                source_key="feldax-paineel",
                evidence="confirmed CLI regression edge",
            )
            ZoneTravelCatalog(db).add_provider_connection(
                paineel,
                hole,
                connection_kind="barrier",
                source_name="CLI regression topology",
                source_kind="test_confirmed_topology",
                source_key="paineel-hole",
                evidence="confirmed CLI regression edge",
            )
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

    def test_json_route_report_is_machine_readable(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(
                [
                    str(self.path),
                    "--json",
                    "--route",
                    "Feldax Hive",
                    "The Hole",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["accepted"], 1)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(payload["results"][0]["status"], "reachable")
        self.assertEqual(payload["results"][0]["hop_count"], 2)
        self.assertEqual(
            payload["results"][0]["path_zone_names"],
            ["Feldax Hive", "Paineel", "The Hole"],
        )

    def test_fail_unreachable_returns_two_without_mutating_snapshot(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(
                [
                    str(self.path),
                    "--fail-unreachable",
                    "--route",
                    "The Hole",
                    "Feldax Hive",
                ]
            )
        self.assertEqual(code, 2)
        text = stdout.getvalue()
        self.assertIn("[FAIL directionality_blocked] The Hole → Feldax Hive", text)

        conn = open_read_only(self.path)
        try:
            count = conn.execute("SELECT COUNT(*) AS n FROM zone_travel_edges").fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(count, 2)

    def test_human_report_names_unresolved_endpoint_without_guessing(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(
                [
                    str(self.path),
                    "--route",
                    "Definitely Not A Zone",
                    "The Hole",
                ]
            )
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("[FAIL source_unresolved] Definitely Not A Zone → The Hole", text)
        self.assertIn("no conservative canonical zone identity match", text)


if __name__ == "__main__":
    unittest.main()
