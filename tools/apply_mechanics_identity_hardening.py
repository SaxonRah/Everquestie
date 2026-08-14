from __future__ import annotations

from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return
        raise RuntimeError(f"Expected patch anchor not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_mechanics() -> None:
    path = ROOT / "eqquest" / "mechanics.py"
    anchor = '''def _source_label(row) -> str:\n    if row is None:\n        return ""\n    return str(row["source_name"] or row["local_path"] or row["url"] or "")\n\n\n'''
    helpers = anchor + '''SPELL_ID_NAMESPACES = ("eqclient:spell", "everquest:spell", "spell")\n\n\ndef _has_eqclient_provenance(db: Database, entity_id: int) -> bool:\n    """Return whether an entity has evidence tying its identity to installed-client data."""\n    row = db.entity(entity_id)\n    if row is not None and str(row["source_url"] or "").casefold().startswith("eqclient://"):\n        return True\n    for source in db.sources_for_entity(entity_id):\n        if str(source["url"] or "").casefold().startswith("eqclient://"):\n            return True\n        if str(source["source_name"] or "").casefold() == "everquest client":\n            return True\n    return False\n\n\ndef spell_id_for_entity(db: Database, entity_id: int) -> int | None:\n    """Resolve the installed-client spell ID without trusting another source's numeric ID."""\n    allowed = set(SPELL_ID_NAMESPACES)\n    for ext in db.external_ids_for_entity(entity_id):\n        if str(ext["namespace"] or "").casefold() not in allowed:\n            continue\n        try:\n            return int(str(ext["external_id"]))\n        except (TypeError, ValueError):\n            continue\n\n    # Compatibility for databases produced before namespaced EQ-client IDs existed.\n    # The legacy field is accepted only when the entity itself has EQ-client provenance.\n    row = db.entity(entity_id)\n    if row is not None and _has_eqclient_provenance(db, entity_id):\n        try:\n            return int(str(row["external_id"] or ""))\n        except (TypeError, ValueError):\n            pass\n    return None\n\n\ndef spell_entity_for_client_id(db: Database, spell_id: int):\n    """Resolve a spell entity by EQ-client identity, with a provenance-gated legacy fallback."""\n    external_id = str(int(spell_id))\n    for namespace in SPELL_ID_NAMESPACES:\n        row = db.entity_by_namespaced_external_id(namespace, external_id)\n        if row is not None and str(row["kind"]) == "spell":\n            return row\n\n    # Old client imports may only have populated entities.external_id. Never use that\n    # field as a generic cross-source ID: Allakhazam and other providers have their own\n    # numeric namespaces and can legitimately collide with an EQ spell ID.\n    rows = db.conn.execute(\n        "SELECT id FROM entities WHERE kind='spell' AND external_id=? ORDER BY id",\n        (external_id,),\n    ).fetchall()\n    for candidate in rows:\n        entity_id = int(candidate["id"])\n        if _has_eqclient_provenance(db, entity_id):\n            return db.entity(entity_id)\n    return None\n\n\ndef spell_name_for_client_id(db: Database, spell_id: int) -> str:\n    row = spell_entity_for_client_id(db, spell_id)\n    return str(row["name"]) if row is not None else f"spell ID {int(spell_id)}"\n\n\n'''
    replace_once(path, anchor, helpers)

    old_method = '''    def _spell_id_for_entity(self, entity_id: int) -> int | None:\n        row = self.db.entity(entity_id)\n        if row is None:\n            return None\n        for ext in self.db.external_ids_for_entity(entity_id):\n            if str(ext["namespace"]).casefold() in {"eqclient:spell", "everquest:spell", "spell"}:\n                try:\n                    return int(ext["external_id"])\n                except Exception:\n                    pass\n        try:\n            return int(str(row["external_id"] or ""))\n        except Exception:\n            return None\n'''
    new_method = '''    def _spell_id_for_entity(self, entity_id: int) -> int | None:\n        return spell_id_for_entity(self.db, entity_id)\n'''
    replace_once(path, old_method, new_method)

    old_peer = '''                name_row = self.db.conn.execute(\n                    "SELECT name FROM entities WHERE kind='spell' AND external_id=? ORDER BY id LIMIT 1",\n                    (str(peer_id),),\n                ).fetchone()\n                name = str(name_row["name"]) if name_row else f"spell ID {peer_id}"\n'''
    new_peer = '''                name = spell_name_for_client_id(self.db, peer_id)\n'''
    replace_once(path, old_peer, new_peer)


def write_tests() -> None:
    path = ROOT / "tests" / "test_mechanics_identity.py"
    path.write_text(textwrap.dedent('''\\
        import tempfile
        import unittest
        from pathlib import Path

        from eqquest.db import Database
        from eqquest.mechanics import (
            spell_entity_for_client_id,
            spell_id_for_entity,
            spell_name_for_client_id,
        )


        class MechanicsSpellIdentityTests(unittest.TestCase):
            def setUp(self):
                self.tmp = tempfile.TemporaryDirectory()
                self.db = Database(Path(self.tmp.name) / "knowledge.sqlite3")

            def tearDown(self):
                self.db.close()
                self.tmp.cleanup()

            def _source(self, *, url: str, name: str, kind: str, key: str) -> int:
                return self.db.upsert_source_page(
                    url=url,
                    title=key,
                    entity_type="spell",
                    sha256=key,
                    plain_text="",
                    raw_html="",
                    source_name=name,
                    source_kind=kind,
                    source_key=key,
                )

            def test_namespaced_client_id_wins_over_legacy_provider_id(self):
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

            def test_legacy_eqclient_external_id_is_supported_when_provenance_is_client(self):
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


        if __name__ == "__main__":
            unittest.main()
        '''), encoding="utf-8")


def main() -> None:
    patch_mechanics()
    write_tests()
    print("mechanics identity hardening applied")


if __name__ == "__main__":
    main()
