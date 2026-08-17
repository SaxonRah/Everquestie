from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_TOOL = REPO_ROOT / "tools" / "audit_map_catalog.py"


class ReleaseMapCatalogAuditTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "knowledge.sqlite3"
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _index_source(self, source_name: str, source_version: str) -> None:
        maps = self.root / source_name
        maps.mkdir()
        (maps / "stonehive.txt").write_text(
            "L 0,0,0,10,10,0,0,0,0\n",
            encoding="utf-8",
        )
        (maps / "stonehive_1.txt").write_text(
            "P 279,529,-27,255,0,0,2,Warwing_Wendlez_(Q)\n",
            encoding="utf-8",
        )
        MapCatalog(self.db).index_root(
            maps,
            source_name=source_name,
            source_version=source_version,
        )

    def _audit(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(AUDIT_TOOL),
                str(self.db_path),
                "--json",
                *extra,
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_read_only_release_audit_accepts_versioned_goods_and_brewall(self):
        self._index_source("Goods", "2026-08-17")
        self._index_source("Brewall", "2026-08-17")
        self.db.conn.commit()
        before = self.db_path.read_bytes()

        completed = self._audit(
            "--require-source",
            "Goods",
            "--require-source",
            "Brewall",
            "--require-versioned-sources",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["required_sources"], ["Goods", "Brewall"])
        self.assertEqual(payload["totals"]["sources"], 2)
        self.assertEqual(payload["totals"]["base_maps"], 2)
        self.assertEqual(payload["totals"]["files"], 4)
        self.assertEqual(payload["totals"]["labels"], 2)
        self.assertEqual(
            {source["source_name"] for source in payload["sources"]},
            {"Goods", "Brewall"},
        )
        self.assertTrue(all(source["portable"] for source in payload["sources"]))
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_release_audit_rejects_missing_required_source(self):
        self._index_source("Brewall", "2026-08-17")

        completed = self._audit(
            "--require-source",
            "Goods",
            "--require-source",
            "Brewall",
            "--require-versioned-sources",
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn(
            "required map catalog source is missing: Goods",
            payload["errors"],
        )

    def test_release_audit_rejects_builder_local_catalog_provenance(self):
        self._index_source("Goods", "2026-08-17")
        self._index_source("Brewall", "2026-08-17")
        self.db.conn.execute(
            "UPDATE map_sources SET root=? WHERE source_name='Goods'",
            (str(self.root / "Goods"),),
        )
        self.db.conn.commit()

        completed = self._audit(
            "--require-source",
            "Goods",
            "--require-source",
            "Brewall",
            "--require-versioned-sources",
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertIn(
            "map source 'Goods' retains builder-local root metadata",
            payload["errors"],
        )

    def test_release_audit_rejects_unversioned_required_catalog(self):
        self._index_source("Goods", "")
        self._index_source("Brewall", "2026-08-17")

        completed = self._audit(
            "--require-source",
            "Goods",
            "--require-source",
            "Brewall",
            "--require-versioned-sources",
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertIn(
            "map source 'Goods' has unversioned indexed files",
            payload["errors"],
        )


class ReleaseMapCatalogPackagingContractTests(unittest.TestCase):
    def test_release_audits_finalized_snapshot_without_rebuilding_catalog(self):
        script = (REPO_ROOT / "tools" / "build_release.ps1").read_text(encoding="utf-8")

        self.assertIn('audit_map_catalog.py', script)
        self.assertIn('& $PythonCommand $MapCatalogAuditTool $Snapshot', script)
        self.assertIn('--require-source Goods', script)
        self.assertIn('--require-source Brewall', script)
        self.assertIn('--require-versioned-sources', script)
        self.assertIn('Map catalog audit failed', script)
        self.assertIn('map_catalog_verified = $true', script)
        self.assertNotIn('build_map_catalog.py', script)

        finalize_pos = script.index('& $PythonCommand $FinalizeTool')
        reviewed_pos = script.index('& $PythonCommand $ReleaseInputAuditTool $Snapshot')
        map_audit_pos = script.index('& $PythonCommand $MapCatalogAuditTool $Snapshot')
        windows_build_pos = script.index('& $WindowsBuilder @BuilderParams')
        self.assertLess(finalize_pos, reviewed_pos)
        self.assertLess(reviewed_pos, map_audit_pos)
        self.assertLess(map_audit_pos, windows_build_pos)


if __name__ == "__main__":
    unittest.main()
