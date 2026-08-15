from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from eqquest.allakhazam_mirror_importer import (
    AllakhazamMirrorImporter,
    normalize_allakhazam_mirror_href,
)
from eqquest.db import Database
from eqquest.knowledge_build import (
    ProviderBuildResult,
    ProviderInvocation,
    build_and_finalize_knowledge,
    default_provider_registry,
)


class AllakhazamMirrorLinkTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "direct.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def test_safe_mirror_href_normalization(self):
        base = "https://everquest.allakhazam.com/db/zone.html?zone=155"
        cases = {
            "zone4B54.html?zone=166": (
                "https://everquest.allakhazam.com/db/zone.html?zone=166"
            ),
            "/db/zone.html?zone=54": (
                "https://everquest.allakhazam.com/db/zone.html?zone=54"
            ),
            "//everquest.allakhazam.com/db/zone.html?zone=58": (
                "https://everquest.allakhazam.com/db/zone.html?zone=58"
            ),
            "../db/questAB12.html?quest=123": (
                "https://everquest.allakhazam.com/db/quest.html?quest=123"
            ),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_allakhazam_mirror_href(raw, base), expected)

        # Same-looking links on another host remain another host and will subsequently
        # be rejected by the ordinary Allakhazam relationship policy.
        external = "https://example.invalid/db/zone.html?zone=999"
        self.assertEqual(normalize_allakhazam_mirror_href(external, base), external)
        self.assertEqual(
            normalize_allakhazam_mirror_href("file:///C:/mirror/zone.html", base),
            "file:///C:/mirror/zone.html",
        )

    def test_connected_zones_survive_relative_httrack_links(self):
        html = """
        <html>
          <head>
            <title>Shar Vahl :: Zones :: EverQuest :: ZAM</title>
            <link rel="canonical" href="https://everquest.allakhazam.com/db/zone.html?zone=155">
          </head>
          <body>
            <h1>Shar Vahl</h1>
            <div class="db-infobox">
              Type: City Expansion: Luclin Instanced: No Keyed: No Level Range: 1 - 20
            </div>
            <div id="Connected_Zones_t">
              <table>
                <tr><th>Name</th><th>Direction</th></tr>
                <tr>
                  <td><a href="zone4B54.html?zone=166">Hollowshade Moor</a></td>
                  <td>Both</td>
                </tr>
                <tr>
                  <td><a href="/db/zone.html?zone=165">Shadeweaver's Thicket</a></td>
                  <td>Both</td>
                </tr>
                <tr>
                  <td><a href="//everquest.allakhazam.com/db/zone.html?zone=302">Dranik's Scar</a></td>
                  <td>Both</td>
                </tr>
                <tr>
                  <td><a href="https://example.invalid/db/zone.html?zone=999">Not Source Evidence</a></td>
                  <td>Both</td>
                </tr>
              </table>
            </div>
          </body>
        </html>
        """
        path = self.root / "shar-vahl.html"
        path.write_text(html, encoding="utf-8")

        result = AllakhazamMirrorImporter(self.db).import_saved_html(path)
        self.assertEqual(result.kind, "zone")
        self.assertEqual(result.name, "Shar Vahl")
        self.assertEqual(result.relationships, 3)

        rows = self.db.conn.execute(
            """
            SELECT te.name AS target_name,te.source_url,r.data_json
            FROM entity_relationships r
            JOIN entities te ON te.id=r.target_entity_id
            WHERE r.source_entity_id=? AND r.relation='connected_to'
            ORDER BY te.name
            """,
            (result.entity_id,),
        ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            {str(row["target_name"]) for row in rows},
            {"Dranik's Scar", "Hollowshade Moor", "Shadeweaver's Thicket"},
        )
        self.assertNotIn("Not Source Evidence", {str(row["target_name"]) for row in rows})
        for row in rows:
            self.assertTrue(
                str(row["source_url"]).startswith(
                    "https://everquest.allakhazam.com/db/zone.html?"
                )
            )
            self.assertEqual(json.loads(row["data_json"])["direction"], "Both")

    @staticmethod
    def _client_fixture(context, _config):
        for zone_id, name in (
            (155, "Shar Vahl"),
            (166, "Hollowshade Moor"),
        ):
            context.db.upsert_entity(
                kind="zone",
                name=name,
                external_id=str(zone_id),
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
        return ProviderBuildResult(
            provider="client-fixture",
            label="client fixture",
            counts={"zones": 2},
        )

    def test_builder_mirror_relative_link_finalizes_into_canonical_travel(self):
        mirror = self.root / "mirror"
        mirror.mkdir()
        (mirror / "shar-vahl.html").write_text(
            """
            <html>
              <head>
                <title>Shar Vahl :: Zones :: EverQuest :: ZAM</title>
                <link rel="canonical" href="https://everquest.allakhazam.com/db/zone.html?zone=155">
              </head>
              <body>
                <h1>Shar Vahl</h1>
                <div class="db-infobox">
                  Type: City Expansion: Luclin Instanced: No Keyed: No Level Range: 1 - 20
                </div>
                <div id="Connected_Zones_t">
                  <table>
                    <tr><th>Name</th><th>Direction</th></tr>
                    <tr>
                      <td><a href="zone4B54.html?zone=166">Hollowshade Moor</a></td>
                      <td>Both</td>
                    </tr>
                  </table>
                </div>
              </body>
            </html>
            """,
            encoding="utf-8",
        )

        working = self.root / "working.sqlite3"
        snapshot = self.root / "snapshot.sqlite3"
        registry = default_provider_registry()
        registry.register("client-fixture", self._client_fixture)
        report = build_and_finalize_knowledge(
            working,
            snapshot,
            [
                ProviderInvocation("client-fixture"),
                ProviderInvocation(
                    "allakhazam-mirror",
                    {"path": str(mirror), "source_version": "real-shape-mirror"},
                ),
            ],
            snapshot_version="mirror-link-test",
            registry=registry,
        )

        self.assertIsNotNone(report.snapshot)
        assert report.snapshot is not None
        self.assertEqual(report.providers[1].counts["relationships"], 1)
        self.assertEqual(report.snapshot.provider_zone_reconciliation["linked"], 2)
        self.assertEqual(report.snapshot.provider_zone_travel["relationships_scanned"], 1)
        self.assertEqual(report.snapshot.provider_zone_travel["linked"], 1)
        self.assertEqual(report.snapshot.provider_zone_travel["blocked_source"], 0)
        self.assertEqual(report.snapshot.provider_zone_travel["blocked_target"], 0)

        conn = sqlite3.connect(snapshot)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT se.name AS source_name,te.name AS target_name,zte.bidirectional
                FROM zone_travel_edges zte
                JOIN entities se ON se.id=zte.source_zone_entity_id
                JOIN entities te ON te.id=zte.target_zone_entity_id
                WHERE zte.source_kind='provider_zone_relationship'
                """
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(str(row["source_name"]), "Shar Vahl")
            self.assertEqual(str(row["target_name"]), "Hollowshade Moor")
            self.assertEqual(int(row["bidirectional"]), 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
