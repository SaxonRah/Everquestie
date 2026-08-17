from __future__ import annotations

import unittest

from eqquest.parser import EQLogParser


class LootParserIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = EQLogParser()

    def _parse(self, body: str):
        event = self.parser.parse_line(f"[Mon Feb 17 09:49:32 2025] {body}")
        self.assertIsNotNone(event)
        return event

    def test_live_corpse_loot_removes_client_article_and_keeps_item_name(self):
        event = self._parse(
            "--You have looted a Discordant Diamond from Xirisst's corpse.--"
        )
        self.assertEqual(event.kind, "loot")
        self.assertEqual(event.item, "Discordant Diamond")
        self.assertEqual(event.actor, "Xirisst")

    def test_client_article_does_not_destroy_canonical_leading_article(self):
        # Real EQ/EQMac-style logs can contain this doubled form: the first
        # article belongs to the client sentence and the second belongs to the
        # item's actual name.  Only one grammatical article may be removed.
        event = self._parse("--You have looted a a Blue throne.--")
        self.assertEqual(event.kind, "loot")
        self.assertEqual(event.item, "a Blue throne")
        self.assertIsNone(event.actor)

    def test_simple_loot_form_preserves_leading_article_verbatim(self):
        event = self._parse("You have looted A Curious Relic.")
        self.assertEqual(event.kind, "loot")
        self.assertEqual(event.item, "A Curious Relic")
        self.assertIsNone(event.actor)

    def test_live_form_without_client_article_does_not_strip_item_text(self):
        event = self._parse("--You have looted A Curious Relic.--")
        self.assertEqual(event.kind, "loot")
        self.assertEqual(event.item, "A Curious Relic")
        self.assertIsNone(event.actor)


if __name__ == "__main__":
    unittest.main()
