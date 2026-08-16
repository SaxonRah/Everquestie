from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog


class MapReconcileAccelerationTests(unittest.TestCase):
    def test_reconcile_does_not_use_per_label_candidate_queries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "maps"
            root.mkdir()
            db = Database(Path(td) / "catalog.sqlite3")
            try:
                db.upsert_entity(
                    kind="zone",
                    name="Stone Hive",
                    merge_by_name=True,
                    data={"map_short_name": "stonehive"},
                )
                npc_id = db.upsert_entity(
                    kind="npc",
                    name="Warwing Wendlez",
                    zone="Stone Hive",
                    merge_by_name=True,
                )

                lines = [
                    f"P {index},529,-27,255,0,0,2,Warwing_Wendlez_(Q)"
                    for index in range(2000)
                ]
                (root / "stonehive.txt").write_text(
                    "\n".join(lines) + "\n",
                    encoding="utf-8",
                )

                catalog = MapCatalog(db)

                def legacy_candidate_query_must_not_run(_normalized_text: str):
                    raise AssertionError("slow per-label candidate query was called")

                catalog._candidate_entities = legacy_candidate_query_must_not_run  # type: ignore[method-assign]
                stats = catalog.index_root(
                    root,
                    source_name="Brewall",
                    source_version="test",
                )

                self.assertEqual(2000, stats.labels)
                self.assertEqual(2000, stats.linked)
                rows = db.conn.execute(
                    "SELECT DISTINCT linked_entity_id,link_status FROM map_labels"
                ).fetchall()
                self.assertEqual(1, len(rows))
                self.assertEqual(npc_id, int(rows[0]["linked_entity_id"]))
                self.assertEqual("linked", str(rows[0]["link_status"]))
            finally:
                db.close()

    def test_duplicate_alias_and_name_candidate_is_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "catalog.sqlite3")
            try:
                entity_id = db.upsert_entity(
                    kind="npc",
                    name="Repeated Name",
                    merge_by_name=True,
                )
                db.add_alias(entity_id, "Repeated Name")
                catalog = MapCatalog(db)
                with db.batch():
                    db.conn.execute(
                        """
                        INSERT INTO map_sources(
                            root,source_name,source_version,source_key,map_stem,zone_name,
                            layer,path,mtime_ns,size,indexed_at
                        ) VALUES('Test','Test','','zone.txt','zone','',0,
                                 'mapcatalog://test/zone.txt',0,0,'now')
                        """
                    )
                    source_id = int(db.conn.execute(
                        "SELECT id FROM map_sources WHERE source_name='Test'"
                    ).fetchone()[0])
                    db.conn.execute(
                        """
                        INSERT INTO map_labels(
                            source_id,map_stem,zone_name,layer,source_line,
                            raw_text,clean_text,normalized_text,x,y,z
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            source_id,
                            "zone",
                            "",
                            0,
                            1,
                            "Repeated Name",
                            "Repeated Name",
                            "repeated name",
                            0.0,
                            0.0,
                            0.0,
                        ),
                    )
                    db.set_meta("map_links_dirty", "1")

                result = catalog.reconcile_all()
                self.assertEqual(1, result["linked"])
                self.assertEqual(0, result["ambiguous"])
                row = db.conn.execute(
                    "SELECT linked_entity_id,link_status FROM map_labels"
                ).fetchone()
                self.assertEqual(entity_id, int(row["linked_entity_id"]))
                self.assertEqual("linked", str(row["link_status"]))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
