from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.target_personal_sightings import (
    target_personal_sighting_text,
    target_personal_sightings,
)


class TargetPersonalSightingsTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _npc(self, name: str = "a cave rat", external_id: str = "npc:rat") -> int:
        return self.db.upsert_entity(kind="npc", name=name, external_id=external_id)

    def _zone(
        self,
        name: str,
        external_id: str,
        *,
        namespace: str = "eqclient:zone",
    ) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=external_id,
            external_namespace=namespace,
        )

    def _event(
        self,
        kind: str,
        *,
        zone: str = "",
        actor: str = "",
        target: str = "",
        item: str = "",
    ) -> None:
        self.db.conn.execute(
            """
            INSERT INTO observed_events(kind,zone,actor,target,item,fields_json,raw)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                kind,
                zone or None,
                actor or None,
                target or None,
                item or None,
                "{}",
                f"{kind} {zone} {actor} {target} {item}",
            ),
        )
        self.db.conn.commit()

    def test_exact_logged_zone_context_resolves_to_canonical_destination(self):
        npc = self._npc()
        zone_id = self._zone("Blightfire Moors", "202")
        self._event("zone", zone="Blightfire Moors")
        self._event("target_npc", target="a cave rat")
        self._event("kill", actor="a cave rat")
        self._event("loot", actor="a cave rat", item="Cave Rat Tail")

        rows = target_personal_sightings(self.db, npc)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row.actionable)
        self.assertEqual(row.canonical_zone_entity_id, zone_id)
        self.assertEqual(row.canonical_zone_name, "Blightfire Moors")
        self.assertEqual(row.total_count, 3)
        self.assertEqual(
            [(action.label, action.count) for action in row.actions],
            [("Observed slain", 1), ("Targeted", 1), ("Explicit corpse loot", 1)],
        )
        self.assertIn("Targeted x1", row.action_summary)

    def test_welcome_resets_zone_context_before_later_observation(self):
        npc = self._npc()
        self._zone("Old Zone", "700")
        self._event("zone", zone="Old Zone")
        self._event("target_npc", target="a cave rat")
        self._event("welcome")
        self._event("kill", actor="a cave rat")

        rows = target_personal_sightings(self.db, npc)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.observed_zone_name, "Old Zone")
        self.assertEqual(row.total_count, 1)
        self.assertEqual([(a.label, a.count) for a in row.actions], [("Targeted", 1)])

    def test_multiple_zone_contexts_preserve_action_counts_and_rank_by_total(self):
        npc = self._npc()
        self._zone("Busy Zone", "701")
        self._zone("Quiet Zone", "702")
        self._event("zone", zone="Quiet Zone")
        self._event("consider", target="a cave rat")
        self._event("zone", zone="Busy Zone")
        self._event("target_npc", target="a cave rat")
        self._event("kill", actor="a cave rat")
        self._event("kill", actor="a cave rat")

        rows = target_personal_sightings(self.db, npc)

        self.assertEqual([row.observed_zone_name for row in rows], ["Busy Zone", "Quiet Zone"])
        self.assertEqual([row.total_count for row in rows], [3, 1])

    def test_ambiguous_logged_zone_stays_visible_but_non_actionable(self):
        npc = self._npc()
        self._zone("Shared Zone", "provider:a", namespace="allakhazam:zone")
        self._zone("Shared Zone", "provider:b", namespace="map:zone")
        self._event("zone", zone="Shared Zone")
        self._event("target_npc", target="a cave rat")

        row = target_personal_sightings(self.db, npc)[0]

        self.assertFalse(row.actionable)
        self.assertEqual(row.resolution_status, "ambiguous")
        self.assertIsNone(row.canonical_zone_entity_id)
        self.assertEqual(row.identity_label, "ambiguous zone: Shared Zone")

    def test_unresolved_logged_zone_stays_visible_but_non_actionable(self):
        npc = self._npc()
        self._event("zone", zone="Totally Unknown Zone")
        self._event("target_npc", target="a cave rat")

        row = target_personal_sightings(self.db, npc)[0]

        self.assertFalse(row.actionable)
        self.assertIsNone(row.canonical_zone_entity_id)
        self.assertIn(row.resolution_status, {"missing", "unresolved"})
        self.assertIn("unresolved zone", row.identity_label)

    def test_duplicate_npc_identity_does_not_inherit_shared_name_geography(self):
        npc_a = self._npc("a duplicate rat", "npc:dup:a")
        self._npc("a duplicate rat", "npc:dup:b")
        self._zone("Duplicate Zone", "703")
        self._event("zone", zone="Duplicate Zone")
        self._event("target_npc", target="a duplicate rat")

        self.assertEqual(target_personal_sightings(self.db, npc_a), ())

    def test_detail_text_preserves_personal_history_vs_spawn_boundary(self):
        npc = self._npc()
        self._zone("Blightfire Moors", "202")
        self._event("zone", zone="Blightfire Moors")
        self._event("kill", actor="a cave rat")
        row = target_personal_sightings(self.db, npc)[0]

        text = target_personal_sighting_text("a cave rat", row)

        self.assertIn("personal-history destination", text)
        self.assertIn("not being written into canonical NPC spawn knowledge", text)
        self.assertIn("no exact NPC /loc is inferred", text)

    def test_non_npc_input_is_rejected(self):
        item = self.db.upsert_entity(kind="item", name="Not an NPC", external_id="item:not-npc")
        self.assertEqual(target_personal_sightings(self.db, item), ())


if __name__ == "__main__":
    unittest.main()
