from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_travel import ZoneTravelCatalog


class ProviderZoneTravelRuntimeTests(unittest.TestCase):
    def test_snapshot_compiles_allakhazam_connected_zones_for_runtime_routing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            working = root / "working.sqlite3"
            db = Database(working)
            try:
                client_stone = db.upsert_entity(
                    kind="zone",
                    name="Stone Hive",
                    external_id="400",
                    external_namespace="eqclient:zone",
                    merge_by_name=False,
                )
                client_blight = db.upsert_entity(
                    kind="zone",
                    name="Blightfire Moors",
                    external_id="401",
                    external_namespace="eqclient:zone",
                    merge_by_name=False,
                )
                provider_stone = db.upsert_entity(
                    kind="zone",
                    name="Stone Hive",
                    external_id="zone:100",
                    external_namespace="allakhazam:zone",
                    merge_by_name=False,
                )
                provider_blight = db.upsert_entity(
                    kind="zone",
                    name="Blightfire Moors",
                    external_id="zone:101",
                    external_namespace="allakhazam:zone",
                    merge_by_name=False,
                )
                page = db.upsert_source_page(
                    url="https://everquest.allakhazam.com/db/zone.html?zstrat=100",
                    title="Stone Hive :: EverQuest",
                    entity_type="zone",
                    sha256="provider-zone-travel-runtime",
                    plain_text="Connected Zones: Blightfire Moors",
                    raw_html="",
                    source_name="Allakhazam",
                    source_kind="local_mirror",
                    source_key="zone:100",
                    source_version="mirror-runtime-test",
                )
                db.upsert_relationship(
                    provider_stone,
                    provider_blight,
                    "connected_to",
                    source_page_id=page,
                    evidence="Blightfire Moors / Both",
                    data={"confidence": "structured", "direction": "Both"},
                )
            finally:
                db.close()

            snapshot = root / "everquestie-knowledge.sqlite3"
            report = create_knowledge_snapshot(
                working,
                snapshot,
                snapshot_version="provider-zone-travel-runtime-test",
            )
            self.assertEqual(report.provider_zone_reconciliation["linked"], 2)
            self.assertEqual(report.provider_zone_travel["relationships_scanned"], 1)
            self.assertEqual(report.provider_zone_travel["linked"], 1)
            self.assertEqual(report.provider_zone_travel["ignored_unstructured"], 0)

            raw = sqlite3.connect(snapshot)
            raw.row_factory = sqlite3.Row
            try:
                rows = raw.execute(
                    """
                    SELECT source_zone_entity_id,target_zone_entity_id,connection_kind,
                           bidirectional,status,source_name,source_kind,source_version,
                           data_json,x,y,z
                    FROM zone_travel_edges
                    WHERE source_kind='provider_zone_relationship'
                    """
                ).fetchall()
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(int(row["source_zone_entity_id"]), client_stone)
                self.assertEqual(int(row["target_zone_entity_id"]), client_blight)
                self.assertEqual(str(row["connection_kind"]), "zone_connection")
                self.assertEqual(int(row["bidirectional"]), 1)
                self.assertEqual(str(row["status"]), "linked")
                self.assertEqual(str(row["source_name"]), "Allakhazam")
                self.assertEqual(str(row["source_version"]), "mirror-runtime-test")
                self.assertIn('"mode": "both"', str(row["data_json"]))
                self.assertIsNone(row["x"])
                self.assertIsNone(row["y"])
                self.assertIsNone(row["z"])

                meta = dict(raw.execute("SELECT key,value FROM app_meta").fetchall())
                self.assertEqual(meta["provider_zone_travel_catalog_version"], "2")
                self.assertIn("provider_zone_travel_catalog_coverage", meta)
            finally:
                raw.close()

            knowledge_hash_before = snapshot.read_bytes()
            runtime = RuntimeDatabase(
                snapshot,
                root / "everquestie-user.sqlite3",
                migrate_legacy=False,
            )
            try:
                travel = ZoneTravelCatalog(runtime)
                self.assertEqual(
                    travel.shortest_path(client_stone, client_blight),
                    [client_stone, client_blight],
                )
                self.assertEqual(
                    travel.shortest_path(client_blight, client_stone),
                    [client_blight, client_stone],
                )

                # Runtime is a pure reader of the finalized graph.
                with self.assertRaises(Exception):
                    runtime.conn.execute(
                        "DELETE FROM zone_travel_edges WHERE source_kind='provider_zone_relationship'"
                    )
            finally:
                runtime.close()

            self.assertEqual(snapshot.read_bytes(), knowledge_hash_before)
            self.assertFalse(Path(str(snapshot) + "-wal").exists())
            self.assertFalse(Path(str(snapshot) + "-shm").exists())

    def test_snapshot_name_variants_unblock_canonical_provider_travel(self):
        """Real provider/client display-name differences must not strand source topology."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            working = root / "working.sqlite3"
            db = Database(working)
            try:
                client_hole = db.upsert_entity(
                    kind="zone",
                    name="The Hole",
                    external_id="39",
                    external_namespace="eqclient:zone",
                    merge_by_name=False,
                )
                client_paineel = db.upsert_entity(
                    kind="zone",
                    name="Paineel",
                    external_id="75",
                    external_namespace="eqclient:zone",
                    merge_by_name=False,
                )
                client_faydark = db.upsert_entity(
                    kind="zone",
                    name="The Greater Faydark",
                    external_id="54",
                    external_namespace="eqclient:zone",
                    merge_by_name=False,
                )
                client_crushbone = db.upsert_entity(
                    kind="zone",
                    name="Crushbone",
                    external_id="58",
                    external_namespace="eqclient:zone",
                    merge_by_name=False,
                )

                provider_hole = db.upsert_entity(
                    kind="zone",
                    name="Ruins of Old Paineel (The Hole)",
                    external_id="zone:99",
                    external_namespace="allakhazam:zone",
                    merge_by_name=False,
                )
                provider_paineel = db.upsert_entity(
                    kind="zone",
                    name="Paineel",
                    external_id="zone:75",
                    external_namespace="allakhazam:zone",
                    merge_by_name=False,
                )
                provider_faydark = db.upsert_entity(
                    kind="zone",
                    name="Greater Faydark",
                    external_id="zone:300",
                    external_namespace="allakhazam:zone",
                    merge_by_name=False,
                )
                provider_crushbone = db.upsert_entity(
                    kind="zone",
                    name="Crushbone",
                    external_id="zone:301",
                    external_namespace="allakhazam:zone",
                    merge_by_name=False,
                )

                hole_page = db.upsert_source_page(
                    url="https://everquest.allakhazam.com/db/zone.html?zstrat=99",
                    title="Ruins of Old Paineel (The Hole) :: EverQuest",
                    entity_type="zone",
                    sha256="provider-hole-name-variant",
                    plain_text="Connected Zones: Paineel",
                    raw_html="",
                    source_name="Allakhazam",
                    source_kind="local_mirror",
                    source_key="zone:99",
                    source_version="mirror-name-variant-test",
                )
                faydark_page = db.upsert_source_page(
                    url="https://everquest.allakhazam.com/db/zone.html?zstrat=300",
                    title="Greater Faydark :: EverQuest",
                    entity_type="zone",
                    sha256="provider-faydark-name-variant",
                    plain_text="Connected Zones: Crushbone",
                    raw_html="",
                    source_name="Allakhazam",
                    source_kind="local_mirror",
                    source_key="zone:300",
                    source_version="mirror-name-variant-test",
                )
                db.upsert_relationship(
                    provider_hole,
                    provider_paineel,
                    "connected_to",
                    source_page_id=hole_page,
                    evidence="Paineel / Both",
                    data={"confidence": "structured", "direction": "Both"},
                )
                db.upsert_relationship(
                    provider_faydark,
                    provider_crushbone,
                    "connected_to",
                    source_page_id=faydark_page,
                    evidence="Crushbone / Both",
                    data={"confidence": "structured", "direction": "Both"},
                )
            finally:
                db.close()

            snapshot = root / "everquestie-knowledge.sqlite3"
            report = create_knowledge_snapshot(
                working,
                snapshot,
                snapshot_version="provider-zone-name-variant-runtime-test",
            )
            self.assertEqual(report.provider_zone_reconciliation["linked"], 4)
            self.assertEqual(report.provider_zone_reconciliation["unresolved"], 0)
            self.assertEqual(report.provider_zone_travel["relationships_scanned"], 2)
            self.assertEqual(report.provider_zone_travel["linked"], 2)
            self.assertEqual(report.provider_zone_travel["blocked_source"], 0)
            self.assertEqual(report.provider_zone_travel["blocked_target"], 0)

            raw = sqlite3.connect(snapshot)
            raw.row_factory = sqlite3.Row
            try:
                bindings = raw.execute(
                    """
                    SELECT provider_zone_name,gameplay_zone_name,status,reason,evidence_json,catalog_version
                    FROM zone_provider_bindings
                    WHERE provider_zone_entity_id IN (?,?)
                    ORDER BY provider_zone_name
                    """,
                    (provider_hole, provider_faydark),
                ).fetchall()
                self.assertEqual(len(bindings), 2)
                by_provider = {str(row["provider_zone_name"]): row for row in bindings}
                hole_binding = by_provider["Ruins of Old Paineel (The Hole)"]
                faydark_binding = by_provider["Greater Faydark"]
                self.assertEqual(str(hole_binding["gameplay_zone_name"]), "The Hole")
                self.assertEqual(str(faydark_binding["gameplay_zone_name"]), "The Greater Faydark")
                self.assertEqual(str(hole_binding["status"]), "linked")
                self.assertEqual(str(faydark_binding["status"]), "linked")
                self.assertIn("terminal parenthetical", str(hole_binding["reason"]))
                self.assertIn("leading-article variant", str(faydark_binding["reason"]))
                self.assertEqual(str(hole_binding["catalog_version"]), "2")
                self.assertEqual(str(faydark_binding["catalog_version"]), "2")
                self.assertIn('"provider_zone_match_kind": "parenthetical_alias"', str(hole_binding["evidence_json"]))
                self.assertIn('"provider_zone_match_kind": "article_variant"', str(faydark_binding["evidence_json"]))
            finally:
                raw.close()

            runtime = RuntimeDatabase(
                snapshot,
                root / "everquestie-user.sqlite3",
                migrate_legacy=False,
            )
            try:
                travel = ZoneTravelCatalog(runtime)
                self.assertEqual(
                    travel.shortest_path(client_hole, client_paineel),
                    [client_hole, client_paineel],
                )
                self.assertEqual(
                    travel.shortest_path(client_paineel, client_hole),
                    [client_paineel, client_hole],
                )
                self.assertEqual(
                    travel.shortest_path(client_faydark, client_crushbone),
                    [client_faydark, client_crushbone],
                )
                self.assertEqual(
                    travel.shortest_path(client_crushbone, client_faydark),
                    [client_crushbone, client_faydark],
                )
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
