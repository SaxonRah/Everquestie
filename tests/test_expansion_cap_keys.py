from __future__ import annotations

import unittest

from eqquest.world_profiles import (
    expansion_allowed_through,
    reviewed_expansion_key,
)


class CanonicalExpansionCapKeyTests(unittest.TestCase):
    def test_canonical_multiword_keys_are_first_class_inputs(self):
        self.assertEqual(reviewed_expansion_key("planes_of_power"), "planes_of_power")
        self.assertEqual(reviewed_expansion_key("lost_dungeons_of_norrath"), "lost_dungeons_of_norrath")
        self.assertEqual(reviewed_expansion_key("the_serpents_spine"), "the_serpents_spine")

    def test_canonical_key_and_display_label_have_identical_chronology(self):
        for cap in ("planes_of_power", "Planes of Power"):
            with self.subTest(cap=cap):
                self.assertIs(expansion_allowed_through("Velious", cap), True)
                self.assertIs(expansion_allowed_through("Luclin", cap), True)
                self.assertIs(expansion_allowed_through("Planes of Power", cap), True)
                self.assertIs(expansion_allowed_through("Legacy of Ykesha", cap), False)

    def test_unknown_key_is_not_promoted(self):
        self.assertIsNone(reviewed_expansion_key("not_a_real_expansion"))
        self.assertIsNone(expansion_allowed_through("Velious", "not_a_real_expansion"))


if __name__ == "__main__":
    unittest.main()
