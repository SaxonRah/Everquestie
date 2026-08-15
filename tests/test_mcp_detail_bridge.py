from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the bridge contract test")
class MCPDetailBridgeContractTests(unittest.TestCase):
    def test_bridge_emits_raw_structured_local_record(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        bridge = repo_root / "tools" / "mcp_local_detail_bridge.mjs"
        self.assertTrue(bridge.is_file())

        with tempfile.TemporaryDirectory() as td:
            mcp = Path(td) / "everquest1-mcp"
            source_dir = mcp / "dist" / "sources"
            source_dir.mkdir(parents=True)
            (mcp / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            (source_dir / "index.js").write_text(
                "export async function getLocalSpell(id) {\n"
                "  return {id, name: 'Bridge Fire', mana: 222, effects: [{slot: 1, description: 'Burn'}]};\n"
                "}\n",
                encoding="utf-8",
            )
            snapshot = {
                "eqPath": str(Path(td) / "EverQuest"),
                "systems": {"spells": {"count": 1, "names": {"77": "Bridge Fire"}}},
            }

            completed = subprocess.run(
                [shutil.which("node") or "node", str(bridge), str(mcp), "-"],
                input=json.dumps(snapshot),
                text=True,
                capture_output=True,
                check=True,
                timeout=20,
            )

        messages = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        record = next(message for message in messages if message.get("type") == "record")
        self.assertEqual("spells", record["system"])
        self.assertEqual("spell", record["kind"])
        self.assertEqual("77", record["external_id"])
        self.assertEqual(222, record["record"]["mana"])
        self.assertEqual("Burn", record["record"]["effects"][0]["description"])


if __name__ == "__main__":
    unittest.main()
