from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.target_intelligence import current_target_intelligence


class TargetIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _page(self, key: str, title: str, entity_type: str = "npc") -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/{key}",
            title=title,
            entity_type=entity_type,
            sha256=f"sha-{key}",
            plain_text=title,
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=key,
            source_version="target-test",
        )

    def _event(self, kind: str, *, target: str = "") -> int:
        cursor = self.db.conn.execute(
            """
            INSERT INTO observed_events(kind,target,fields_json,raw)
            VALUES(?,?,?,?)
            """,
            (kind, target or None, "{}", f"[{kind}] {target}"),
        )
        self.db.conn.commit()
        return int(cursor.lastrowid)

    def test_exact_npc_target_resolves_without_fuzzy_matching(self):
        npc = self.db.upsert_entity(
            kind="npc",
            name="a moss snake",
            external_id="npc:1001",
            level_min=1,
            level_max=2,
        )
        self._event("target_npc", target="a moss snake")

        result = current_target_intelligence(self.db)

        self.assertTrue(result.resolved)
        self.assertEqual(result.entity_id, npc)
        self.assertEqual(result.canonical_name, "a moss snake")
        self.assertEqual(result.resolution_kind, "exact")
        self.assertEqual((result.level_min, result.level_max), (1, 2))

    def test_exact_alias_can_resolve_one_canonical_npc(self):
        npc = self.db.upsert_entity(
            kind="npc",
            name="Guard Bristle",
            external_id="npc:1002",
        )
        self.db.add_alias(npc, "Bristle", alias_type="source")
        self._event("consider", target="Bristle")

        result = current_target_intelligence(self.db)

        self.assertTrue(result.resolved)
        self.assertEqual(result.entity_id, npc)
        self.assertEqual(result.resolution_kind, "alias")
        self.assertEqual(result.observed_event_kind, "consider")

    def test_duplicate_exact_names_fail_closed(self):
        self.db.upsert_entity(kind="npc", name="Scout", external_id="npc:2001")
        self.db.upsert_entity(kind="npc", name="Scout", external_id="npc:2002")
        self._event("target_npc", target="Scout")

        result = current_target_intelligence(self.db)

        self.assertEqual(result.status, "ambiguous")
        self.assertFalse(result.resolved)
        self.assertIsNone(result.entity_id)

    def test_zone_and_player_target_clear_older_npc_context(self):
        self.db.upsert_entity(kind="npc", name="Orc Pawn", external_id="npc:3001")
        self._event("target_npc", target="Orc Pawn")
        self._event("zone")

        zoned = current_target_intelligence(self.db)
        self.assertEqual(zoned.status, "cleared")
        self.assertEqual(zoned.observed_event_kind, "zone")

        self._event("target_npc", target="Orc Pawn")
        self._event("target_player", target="AnotherPlayer")
        player = current_target_intelligence(self.db)
        self.assertEqual(player.status, "cleared")
        self.assertEqual(player.observed_event_kind, "target_player")

    def test_session_boundary_hides_stale_target(self):
        self.db.upsert_entity(kind="npc", name="Old Target", external_id="npc:4001")
        event_id = self._event("target_npc", target="Old Target")

        result = current_target_intelligence(self.db, after_event_id=event_id)

        self.assertEqual(result.status, "none")
        self.assertFalse(result.resolved)

    def test_relationship_counts_distinct_related_entities_not_provenance_rows(self):
        npc_page = self._page("npc/5001", "Named Target")
        quest_page_a = self._page("quest/5002-a", "A Hunter's Task", "quest")
        quest_page_b = self._page("quest/5002-b", "A Hunter's Task evidence", "quest")
        npc = self.db.upsert_entity(
            kind="npc",
            name="Named Target",
            external_id="npc:5001",
            source_page_id=npc_page,
        )
        quest = self.db.upsert_entity(
            kind="quest",
            name="A Hunter's Task",
            external_id="quest:5002",
            source_page_id=quest_page_a,
        )
        unprovenanced = self.db.upsert_entity(
            kind="quest",
            name="Unprovenanced Task",
            external_id="quest:5003",
        )
        self.db.upsert_relationship(
            quest,
            npc,
            "objective_kill",
            source_page_id=quest_page_a,
            evidence="Kill Named Target.",
        )
        self.db.upsert_relationship(
            quest,
            npc,
            "objective_kill",
            source_page_id=quest_page_b,
            evidence="Named Target is a kill objective.",
        )
        self.db.upsert_relationship(
            unprovenanced,
            npc,
            "objective_kill",
            source_page_id=None,
            evidence="Not source backed.",
        )
        self._event("target_npc", target="Named Target")

        result = current_target_intelligence(self.db)
        rows = [row for row in result.relationships if row.other_kind == "quest"]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].label, "Kill target for quest")
        self.assertEqual(rows[0].count, 1)
        self.assertEqual(rows[0].examples, ("A Hunter's Task",))

    def test_known_location_uses_canonical_gameplay_zone_projection(self):
        page = self._page("npc/6001", "Cave Rat")
        zone = self.db.upsert_entity(
            kind="zone",
            name="The Warrens",
            external_id="101",
            external_namespace="eqclient:zone",
        )
        npc = self.db.upsert_entity(
            kind="npc",
            name="Cave Rat",
            external_id="npc:6001",
            source_page_id=page,
        )
        self.db.add_location(
            npc,
            zone_entity_id=zone,
            y=10.0,
            x=20.0,
            z=3.0,
            label="known spawn",
            source_page_id=page,
            evidence="Cave Rat at 10, 20, 3",
        )
        self._event("target_npc", target="Cave Rat")

        result = current_target_intelligence(self.db)

        self.assertTrue(result.resolved)
        self.assertIn("The Warrens", result.known_zones)


if __name__ == "__main__":
    unittest.main()
