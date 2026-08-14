from __future__ import annotations

from pathlib import Path
import unittest

from eqquest.local_map_variant_ui import local_map_variant_labels


class LocalMapVariantUILabelTests(unittest.TestCase):
    def test_duplicate_filenames_include_pack_folder(self):
        candidates = (
            Path("maps") / "Good's Maps" / "stonehive.txt",
            Path("maps") / "Brewall's Maps" / "stonehive.txt",
        )
        self.assertEqual(
            local_map_variant_labels(candidates),
            (
                "Good's Maps / stonehive.txt",
                "Brewall's Maps / stonehive.txt",
            ),
        )

    def test_unique_filename_stays_compact(self):
        candidates = (
            Path("maps") / "Good's Maps" / "stonehive.txt",
            Path("maps") / "Brewall's Maps" / "blightfire.txt",
        )
        self.assertEqual(
            local_map_variant_labels(candidates),
            ("stonehive.txt", "blightfire.txt"),
        )


if __name__ == "__main__":
    unittest.main()
