from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.knowledge_build import ProviderInvocation, build_working_knowledge_db


class AllakhazamSpellProviderCountTests(unittest.TestCase):
    def test_provider_reports_structured_spell_page_count(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            mirror = root / "mirror"
            mirror.mkdir()
            (mirror / "spell111.html").write_text(
                """
                <html>
                  <head>
                    <title>Malaisement :: Spells :: EverQuest :: ZAM</title>
                    <link rel="canonical" href="https://everquest.allakhazam.com/db/spell.html?spell=111">
                  </head>
                  <body>
                    <h1>Malaisement</h1>
                    <section>
                      <h3>Quick Facts</h3>
                      <div><b>Expansion:</b><img alt="Original" src="/images/expansion.gif"></div>
                    </section>
                  </body>
                </html>
                """,
                encoding="utf-8",
            )

            report = build_working_knowledge_db(
                root / "working.sqlite3",
                [ProviderInvocation("allakhazam-mirror", {"path": str(mirror)})],
            )

            counts = report.providers[0].counts
            self.assertEqual(counts["pages_changed"], 1)
            self.assertEqual(counts["spells"], 1)
            self.assertEqual(counts["quests"], 0)
            self.assertEqual(counts["npcs"], 0)
            self.assertEqual(counts["items"], 0)
            self.assertEqual(counts["zones"], 0)


if __name__ == "__main__":
    unittest.main()
