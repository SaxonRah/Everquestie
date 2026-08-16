from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the bridge contract test")
class MCPDetailBridgeContractTests(unittest.TestCase):
    def _run_bridge(self, module_source: str, snapshot: dict) -> list[dict]:
        repo_root = Path(__file__).resolve().parents[1]
        bridge = repo_root / "tools" / "mcp_local_detail_bridge.mjs"
        self.assertTrue(bridge.is_file())

        with tempfile.TemporaryDirectory() as td:
            mcp = Path(td) / "everquest1-mcp"
            source_dir = mcp / "dist" / "sources"
            source_dir.mkdir(parents=True)
            (mcp / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            (source_dir / "index.js").write_text(module_source, encoding="utf-8")
            snapshot = dict(snapshot)
            snapshot.setdefault("eqPath", str(Path(td) / "EverQuest"))

            completed = subprocess.run(
                [shutil.which("node") or "node", str(bridge), str(mcp), "-"],
                input=json.dumps(snapshot),
                text=True,
                capture_output=True,
                check=True,
                timeout=20,
            )

        return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]

    def test_bridge_emits_raw_structured_local_record(self) -> None:
        messages = self._run_bridge(
            "export async function getLocalSpell(id) {\n"
            "  return {id, name: 'Bridge Fire', mana: 222, effects: [{slot: 1, description: 'Burn'}]};\n"
            "}\n",
            {"systems": {"spells": {"count": 1, "names": {"77": "Bridge Fire"}}}},
        )

        record = next(message for message in messages if message.get("type") == "record")
        self.assertEqual("spells", record["system"])
        self.assertEqual("spell", record["kind"])
        self.assertEqual("77", record["external_id"])
        self.assertEqual(222, record["record"]["mana"])
        self.assertEqual("Burn", record["record"]["effects"][0]["description"])

    def test_combat_ability_keeps_dbstring_identity_and_enriches_by_exact_spell_name(self) -> None:
        messages = self._run_bridge(
            "export async function getLocalSpellByName(name) {\n"
            "  if (name === 'Exact Discipline') {\n"
            "    return {id: '9001', name: 'Exact Discipline', endurance: 440, recastTime: 12000, classes: {Warrior: 80}};\n"
            "  }\n"
            "  return {id: '9999', name: 'Fuzzy Different Spell', endurance: 1};\n"
            "}\n",
            {
                "systems": {
                    "combatAbilities": {
                        "count": 2,
                        "names": {"700": "Exact Discipline", "701": "No Exact Match"},
                    }
                }
            },
        )

        records = [message for message in messages if message.get("type") == "record"]
        errors = [message for message in messages if message.get("type") == "record_error"]
        self.assertEqual(2, len(records))
        self.assertEqual(0, len(errors))

        exact = next(record for record in records if record["external_id"] == "700")
        payload = exact["record"]
        self.assertEqual("combatAbilities", exact["system"])
        self.assertEqual("combat_ability", exact["kind"])
        self.assertEqual("700", payload["id"])
        self.assertEqual("700", payload["abilityId"])
        self.assertEqual("9001", payload["spellId"])
        self.assertEqual("Exact Discipline", payload["spellName"])
        self.assertEqual(440, payload["endurance"])
        self.assertEqual("exact_case_insensitive_name", payload["identityJoin"]["method"])
        self.assertEqual("9001", payload["identityJoin"]["matchedSpellId"])

        fallback = next(record for record in records if record["external_id"] == "701")
        fallback_payload = fallback["record"]
        self.assertEqual("701", fallback_payload["id"])
        self.assertEqual("701", fallback_payload["abilityId"])
        self.assertIsNone(fallback_payload["spellId"])
        self.assertEqual("no_exact_spell_match", fallback_payload["identityJoin"]["method"])
        self.assertEqual(
            "non_exact_spell_name_match_rejected",
            fallback_payload["identityJoin"]["reason"],
        )
        self.assertEqual("9999", fallback_payload["identityJoin"]["rejectedSpellId"])
        self.assertEqual(
            "Fuzzy Different Spell",
            fallback_payload["identityJoin"]["rejectedSpellName"],
        )


if __name__ == "__main__":
    unittest.main()
