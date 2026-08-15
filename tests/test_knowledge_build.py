import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from eqquest.knowledge_build import (
    KnowledgeProviderRegistry,
    ProviderBuildResult,
    ProviderInvocation,
    build_and_finalize_knowledge,
    build_working_knowledge_db,
    default_provider_registry,
)


class KnowledgeBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.working = self.root / "working.sqlite3"
        self.snapshot = self.root / "knowledge.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _future_allakhazam_provider(context, config):
        source_id = context.db.upsert_source_page(
            url="allakhazam-db://zone/202",
            title="Future Mirrored Zone",
            entity_type="zone",
            sha256="future-zone-hash",
            plain_text="future mirror payload",
            raw_html="",
            source_name="Allakhazam DB",
            source_kind="builder_mirror",
            source_key="zone:202",
            source_version=str(config.get("version") or "future-test"),
            local_path=r"C:\builder\allakhazam-db\zone-202.json",
        )
        context.db.upsert_entity(
            kind="zone",
            name="Future Mirrored Zone",
            source_page_id=source_id,
            source_url="allakhazam-db://zone/202",
            external_id="zone:202",
            external_namespace="allakhazam:zone",
        )
        return ProviderBuildResult(
            provider="allakhazam-db",
            label="future Allakhazam mirror",
            counts={"zones": 1},
        )

    def _write_allakhazam_zone_page(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "stone-hive.html"
        path.write_text(
            """
            <html>
              <head>
                <title>The Stone Hive :: Zones :: EverQuest :: ZAM</title>
                <link rel="canonical" href="https://everquest.allakhazam.com/db/zone.html?zstrat=100">
              </head>
              <body>
                <h1>The Stone Hive</h1>
                <div class="db-infobox">
                  Type: Outdoor Expansion: The Serpent's Spine Instanced: No Keyed: No Level Range: 35 - 45
                </div>
                <div id="Connected_Zones_t">
                  <table>
                    <tr><th>Name</th><th>Direction</th></tr>
                    <tr>
                      <td><a href="https://everquest.allakhazam.com/db/zone.html?zstrat=101">Blightfire Moors</a></td>
                      <td>Both</td>
                    </tr>
                  </table>
                </div>
              </body>
            </html>
            """,
            encoding="utf-8",
        )
        return path

    def test_default_build_includes_optional_allakhazam_mirror_provider(self):
        self.assertEqual(
            set(default_provider_registry().names()),
            {"allakhazam-mirror", "eqclient", "mcp", "map-pack"},
        )

    def test_allakhazam_mirror_provider_imports_structured_pages_and_provenance(self):
        mirror = self.root / "mirror"
        page = self._write_allakhazam_zone_page(mirror)

        report = build_working_knowledge_db(
            self.working,
            [
                ProviderInvocation(
                    "allakhazam-mirror",
                    {"path": str(mirror), "source_version": "mirror-2026-08-15"},
                    label="test mirror",
                )
            ],
        )
        self.assertEqual(len(report.providers), 1)
        result = report.providers[0]
        self.assertEqual(result.provider, "allakhazam-mirror")
        self.assertEqual(result.counts["pages_changed"], 1)
        self.assertEqual(result.counts["zones"], 1)
        self.assertEqual(result.counts["relationships"], 1)
        self.assertEqual(result.counts["read_errors"], 0)
        self.assertEqual(result.details["source_version"], "mirror-2026-08-15")

        db = sqlite3.connect(self.working)
        db.row_factory = sqlite3.Row
        try:
            source = db.execute(
                """
                SELECT source_name,source_kind,source_version,local_path
                FROM source_pages
                WHERE source_name='Allakhazam'
                """
            ).fetchone()
            self.assertIsNotNone(source)
            self.assertEqual(source["source_kind"], "local_mirror")
            self.assertEqual(source["source_version"], "mirror-2026-08-15")
            self.assertEqual(Path(source["local_path"]), page.resolve())

            relationship = db.execute(
                """
                SELECT r.data_json,se.name AS source_name,te.name AS target_name
                FROM entity_relationships r
                JOIN entities se ON se.id=r.source_entity_id
                JOIN entities te ON te.id=r.target_entity_id
                WHERE r.relation='connected_to'
                """
            ).fetchone()
            self.assertIsNotNone(relationship)
            self.assertEqual(relationship["source_name"], "The Stone Hive")
            self.assertEqual(relationship["target_name"], "Blightfire Moors")
            self.assertEqual(json.loads(relationship["data_json"])["direction"], "Both")
        finally:
            db.close()

    def test_future_provider_registers_without_coordinator_changes(self):
        registry = default_provider_registry()
        registry.register("allakhazam-db", self._future_allakhazam_provider)

        report = build_and_finalize_knowledge(
            self.working,
            self.snapshot,
            [
                ProviderInvocation(
                    "allakhazam-db",
                    {"version": "mirror-2030-01"},
                    label="future mirror",
                )
            ],
            snapshot_version="future-provider-test",
            registry=registry,
        )

        self.assertEqual(report.providers[0].provider, "allakhazam-db")
        self.assertEqual(report.providers[0].counts, {"zones": 1})
        self.assertIsNotNone(report.snapshot)

        working = sqlite3.connect(self.working)
        working.row_factory = sqlite3.Row
        try:
            source = working.execute(
                "SELECT source_name,source_version,local_path FROM source_pages"
            ).fetchone()
            self.assertEqual(source["source_name"], "Allakhazam DB")
            self.assertEqual(source["source_version"], "mirror-2030-01")
            self.assertTrue(source["local_path"])
        finally:
            working.close()

        snapshot = sqlite3.connect(self.snapshot)
        snapshot.row_factory = sqlite3.Row
        try:
            source = snapshot.execute(
                "SELECT source_name,source_version,local_path FROM source_pages"
            ).fetchone()
            self.assertEqual(source["source_name"], "Allakhazam DB")
            self.assertEqual(source["source_version"], "mirror-2030-01")
            self.assertEqual(source["local_path"], "")
            entity = snapshot.execute(
                "SELECT name FROM entities WHERE kind='zone'"
            ).fetchone()
            self.assertEqual(entity["name"], "Future Mirrored Zone")
            namespaced = snapshot.execute(
                "SELECT namespace,external_id FROM entity_external_ids"
            ).fetchone()
            self.assertEqual(
                (namespaced["namespace"], namespaced["external_id"]),
                ("allakhazam:zone", "zone:202"),
            )
        finally:
            snapshot.close()

    def test_failed_provider_does_not_publish_partial_working_db(self):
        registry = KnowledgeProviderRegistry()

        def fail(_context, _config):
            raise RuntimeError("provider exploded")

        registry.register("failure-test", fail)
        with self.assertRaisesRegex(RuntimeError, "provider exploded"):
            build_working_knowledge_db(
                self.working,
                [ProviderInvocation("failure-test")],
                registry=registry,
            )
        self.assertFalse(self.working.exists())
        self.assertFalse(self.working.with_name(self.working.name + ".building").exists())

    def test_unknown_provider_reports_registered_choices(self):
        registry = KnowledgeProviderRegistry()
        registry.register(
            "known",
            lambda _context, _config: ProviderBuildResult("known", "known"),
        )
        with self.assertRaisesRegex(KeyError, "registered providers: known"):
            build_working_knowledge_db(
                self.working,
                [ProviderInvocation("not-installed")],
                registry=registry,
            )


if __name__ == "__main__":
    unittest.main()
