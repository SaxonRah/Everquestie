from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from eqquest.allakhazam import AllakhazamImporter
from eqquest.db import Database


class AllakhazamZoneTravelDirectionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def test_connected_zones_preserve_structured_direction_text(self):
        html = """
        <html>
          <head>
            <title>Plane of Sky :: Zones :: EverQuest :: ZAM</title>
            <link rel="canonical" href="https://everquest.allakhazam.com/db/zone.html?zone=70">
          </head>
          <body>
            <h1>Plane of Sky</h1>
            <div class="db-infobox">
              Type: Outdoor Expansion: Planes Instanced: No Keyed: No Level Range: 46 - 65
            </div>
            <div id="Connected_Zones_t">
              <table>
                <tr><th>Name</th><th>Direction</th></tr>
                <tr>
                  <td><a href="https://everquest.allakhazam.com/db/zone.html?zone=10">East Freeport</a></td>
                  <td>Entrance To East Freeport</td>
                </tr>
                <tr>
                  <td><a href="https://everquest.allakhazam.com/db/zone.html?zone=345">Guild Hall</a></td>
                  <td>Exit From Guild Hall</td>
                </tr>
                <tr>
                  <td><a href="https://everquest.allakhazam.com/db/zone.html?zone=203">Plane of Tranquility</a></td>
                  <td>Both</td>
                </tr>
              </table>
            </div>
          </body>
        </html>
        """
        path = self.root / "plane-of-sky.html"
        path.write_text(html, encoding="utf-8")

        result = AllakhazamImporter(self.db).import_saved_html(path)
        self.assertEqual(result.kind, "zone")
        self.assertEqual(result.name, "Plane of Sky")
        self.assertEqual(result.relationships, 3)

        rows = self.db.conn.execute(
            """
            SELECT te.name AS target_name,r.evidence,r.data_json
            FROM entity_relationships r
            JOIN entities te ON te.id=r.target_entity_id
            WHERE r.source_entity_id=? AND r.relation='connected_to'
            ORDER BY te.name
            """,
            (result.entity_id,),
        ).fetchall()
        self.assertEqual(len(rows), 3)

        directions = {
            str(row["target_name"]): json.loads(row["data_json"])["direction"]
            for row in rows
        }
        self.assertEqual(directions["East Freeport"], "Entrance To East Freeport")
        self.assertEqual(directions["Guild Hall"], "Exit From Guild Hall")
        self.assertEqual(directions["Plane of Tranquility"], "Both")

        evidence = {str(row["target_name"]): str(row["evidence"]) for row in rows}
        self.assertEqual(
            evidence["East Freeport"],
            "East Freeport / Entrance To East Freeport",
        )
        self.assertEqual(evidence["Guild Hall"], "Guild Hall / Exit From Guild Hall")
        self.assertEqual(evidence["Plane of Tranquility"], "Plane of Tranquility / Both")


if __name__ == "__main__":
    unittest.main()
