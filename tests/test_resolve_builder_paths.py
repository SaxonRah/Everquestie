from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.settings import SettingsFile
from tools.resolve_builder_paths import resolve_builder_paths


class ResolveBuilderPathsTests(unittest.TestCase):
    def _settings(self, root: Path) -> SettingsFile:
        return SettingsFile(root / "settings.ini")

    def test_uses_mirror_folder_selected_in_settings(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            project_root = root / "repo"
            project_root.mkdir()
            eq = root / "eq"
            eq.mkdir()
            mcp = root / "mcp"
            mcp.mkdir()
            project = root / "httrack"
            mirror = project / "everquest.allakhazam.com"
            mirror.mkdir(parents=True)
            maps = root / "maps"
            goods = maps / "Good's Maps"
            brewall = maps / "Brewall"
            goods.mkdir(parents=True)
            brewall.mkdir()

            settings = self._settings(root)
            settings.update_paths(
                {
                    "everquest_install": eq,
                    "allakhazam_db_mirror": mirror,
                    "mcp_repository": mcp,
                    "map_root": maps,
                }
            )
            settings.save()

            resolved = resolve_builder_paths(
                project_root=project_root,
                settings_path=settings.path,
            )

            self.assertEqual(Path(resolved["eq_install"]), eq.resolve())
            self.assertEqual(Path(resolved["allakhazam_project"]), project.resolve())
            self.assertEqual(Path(resolved["allakhazam_mirror"]), mirror.resolve())
            self.assertEqual(Path(resolved["mcp_repository"]), mcp.resolve())
            self.assertEqual(Path(resolved["goods_maps"]), goods.resolve())
            self.assertEqual(Path(resolved["brewall_maps"]), brewall.resolve())

    def test_accepts_httrack_project_folder_selected_in_settings(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            project_root = root / "repo"
            project_root.mkdir()
            project = root / "httrack"
            mirror = project / "everquest.allakhazam.com"
            mirror.mkdir(parents=True)

            settings = self._settings(root)
            settings.set_path("allakhazam_db_mirror", project)
            settings.save()

            resolved = resolve_builder_paths(
                project_root=project_root,
                settings_path=settings.path,
            )

            self.assertEqual(Path(resolved["allakhazam_project"]), project.resolve())
            self.assertEqual(Path(resolved["allakhazam_mirror"]), mirror.resolve())

    def test_map_pack_selection_can_be_one_pack_and_resolves_sibling(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            project_root = root / "repo"
            project_root.mkdir()
            maps = root / "maps"
            goods = maps / "Good's Maps"
            brewall = maps / "Brewall"
            goods.mkdir(parents=True)
            brewall.mkdir()

            settings = self._settings(root)
            settings.set_path("map_root", brewall)
            settings.save()

            resolved = resolve_builder_paths(
                project_root=project_root,
                settings_path=settings.path,
            )

            self.assertEqual(Path(resolved["goods_maps"]), goods.resolve())
            self.assertEqual(Path(resolved["brewall_maps"]), brewall.resolve())


if __name__ == "__main__":
    unittest.main()
