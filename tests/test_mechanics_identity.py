import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from eqquest.mechanics import (
    skill_entity_for_client_id,
    skill_id_for_entity,
    skill_name_for_client_id,
    spell_entity_for_client_id,
    spell_id_for_entity,
    spell_name_for_client_id,
)


class MechanicsIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "knowledge.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _source(
        self,
        *,
        url: str,
        name: str,
        kind: str,
        key: str,
        entity_type: str = "spell",
    ) -> int:
        return self.db.upsert_source_page(
            url=url,
            title=key,
            entity_type=entity_type,
            sha256=key,
            plain_text="",
            raw_html="",
            source_name=name,
            source_kind=kind,
            source_key=key,
        )

    def test_namespaced_client_spell_id_wins_over_legacy_provider_id(self):
        allakhazam = self._source(
            url="https://everquest.allakhazam.com/db/spell.html?spell=999",
            name="Allakhazam",
            kind="builder_mirror",
            key="spell:999",
        )
        entity_id = self.db.upsert_entity(
            kind="spell",
            name="Canonical Test Spell",
            source_page_id=allakhazam,
            source_url="https://everquest.allakhazam.com/db/spell.html?spell=999",
            external_id="999",
            external_namespace="allakhazam:spell",
        )
        client = self._source(
            url="eqclient://dbstr_us.txt#6:42",
            name="EverQuest Client",
            kind="local_game_files",
            key="dbstr_us.txt:6:42",
        )
        self.db.link_entity_source(entity_id, client, role="identity")
        self.db.add_external_id(entity_id, "eqclient:spell", "42", source_page_id=client)

        self.assertEqual(spell_id_for_entity(self.db, entity_id), 42)
        resolved = spell_entity_for_client_id(self.db, 42)
        self.assertIsNotNone(resolved)
        self.assertEqual(int(resolved["id"]), entity_id)
        self.assertEqual(spell_name_for_client_id(self.db, 42), "Canonical Test Spell")

    def test_allakhazam_only_legacy_collision_is_not_a_client_spell(self):
        source = self._source(
            url="https://everquest.allakhazam.com/db/spell.html?spell=77",
            name="Allakhazam",
            kind="builder_mirror",
            key="spell:77",
        )
        entity_id = self.db.upsert_entity(
            kind="spell",
            name="Wrong Namespace Spell",
            source_page_id=source,
            source_url="https://everquest.allakhazam.com/db/spell.html?spell=77",
            external_id="77",
            external_namespace="allakhazam:spell",
        )

        self.assertIsNone(spell_id_for_entity(self.db, entity_id))
        self.assertIsNone(spell_entity_for_client_id(self.db, 77))
        self.assertEqual(spell_name_for_client_id(self.db, 77), "spell ID 77")

    def test_legacy_eqclient_spell_external_id_is_supported_with_client_provenance(self):
        client = self._source(
            url="eqclient://legacy-spells.txt",
            name="EverQuest Client",
            kind="local_game_files",
            key="legacy-spells.txt",
        )
        entity_id = self.db.upsert_entity(
            kind="spell",
            name="Legacy Client Spell",
            source_page_id=client,
            source_url="eqclient://legacy-spells.txt",
            external_id="88",
        )

        self.assertEqual(spell_id_for_entity(self.db, entity_id), 88)
        resolved = spell_entity_for_client_id(self.db, 88)
        self.assertIsNotNone(resolved)
        self.assertEqual(int(resolved["id"]), entity_id)
        self.assertEqual(spell_name_for_client_id(self.db, 88), "Legacy Client Spell")

    def test_namespaced_client_skill_id_resolves_canonical_skill_name(self):
        future_provider = self._source(
            url="https://everquest.allakhazam.com/db/skills.html?skill=500",
            name="Allakhazam",
            kind="builder_mirror",
            key="skill:500",
            entity_type="skill",
        )
        entity_id = self.db.upsert_entity(
            kind="skill",
            name="Kick",
            source_page_id=future_provider,
            source_url="https://everquest.allakhazam.com/db/skills.html?skill=500",
            external_id="500",
            external_namespace="allakhazam:skill",
        )
        client = self._source(
            url="eqclient://skills#30",
            name="EverQuest Client",
            kind="local_game_files",
            key="skills:30",
            entity_type="skill",
        )
        self.db.link_entity_source(entity_id, client, role="identity")
        self.db.add_external_id(entity_id, "eqclient:skill", "30", source_page_id=client)

        self.assertEqual(skill_id_for_entity(self.db, entity_id), 30)
        resolved = skill_entity_for_client_id(self.db, 30)
        self.assertIsNotNone(resolved)
        self.assertEqual(int(resolved["id"]), entity_id)
        self.assertEqual(skill_name_for_client_id(self.db, 30), "Kick")

    def test_unrelated_provider_skill_id_collision_is_not_treated_as_client_identity(self):
        source = self._source(
            url="https://everquest.allakhazam.com/db/skills.html?skill=31",
            name="Allakhazam",
            kind="builder_mirror",
            key="skill:31",
            entity_type="skill",
        )
        entity_id = self.db.upsert_entity(
            kind="skill",
            name="Provider Skill With Colliding ID",
            source_page_id=source,
            source_url="https://everquest.allakhazam.com/db/skills.html?skill=31",
            external_id="31",
            external_namespace="allakhazam:skill",
        )

        self.assertIsNone(skill_id_for_entity(self.db, entity_id))
        self.assertIsNone(skill_entity_for_client_id(self.db, 31))
        self.assertEqual(skill_name_for_client_id(self.db, 31), "Skill ID 31")

    def test_legacy_eqclient_skill_external_id_is_supported_with_client_provenance(self):
        client = self._source(
            url="eqclient://legacy-skills.txt",
            name="EverQuest Client",
            kind="local_game_files",
            key="legacy-skills.txt",
            entity_type="skill",
        )
        entity_id = self.db.upsert_entity(
            kind="skill",
            name="Legacy Client Skill",
            source_page_id=client,
            source_url="eqclient://legacy-skills.txt",
            external_id="32",
        )

        self.assertEqual(skill_id_for_entity(self.db, entity_id), 32)
        resolved = skill_entity_for_client_id(self.db, 32)
        self.assertIsNotNone(resolved)
        self.assertEqual(int(resolved["id"]), entity_id)
        self.assertEqual(skill_name_for_client_id(self.db, 32), "Legacy Client Skill")


if __name__ == "__main__":
    unittest.main()
