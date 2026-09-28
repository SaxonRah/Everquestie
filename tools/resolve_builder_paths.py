from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.settings import SettingsFile


DEFAULT_EQ_INSTALL = Path(
    r"C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest"
)
DEFAULT_ALLAKHAZAM_PROJECT = Path(r"C:\AllakhazamEverquest\EQ_Allakhazam_DB")


def _path(value: str | Path) -> Path:
    return Path(value).expanduser()


def _allakhazam_paths(configured: str | Path) -> tuple[Path, Path]:
    selected = _path(configured)
    child = selected / "everquest.allakhazam.com"

    # The UI historically allowed selecting either the HTTrack project folder or
    # the actual mirrored hostname folder. The builder needs both.
    if selected.name.casefold() == "everquest.allakhazam.com":
        return selected.parent, selected
    if child.is_dir():
        return selected, child
    return selected.parent, selected


def _map_pack_paths(map_root: str | Path | None, eq_install: Path) -> tuple[Path, Path]:
    if map_root:
        selected = _path(map_root)
        name = selected.name.casefold()
        if name in {"good's maps", "goods maps", "good maps"}:
            return selected, selected.parent / "Brewall"
        if name == "brewall":
            return selected.parent / "Good's Maps", selected
        return selected / "Good's Maps", selected / "Brewall"

    maps = eq_install / "maps"
    return maps / "Good's Maps", maps / "Brewall"


def resolve_builder_paths(
    *,
    project_root: str | Path,
    settings_path: str | Path | None = None,
) -> dict[str, str]:
    project = _path(project_root).resolve()
    settings = SettingsFile(settings_path)

    eq_install = _path(
        settings.get_path("everquest_install") or DEFAULT_EQ_INSTALL
    )
    mcp_repository = _path(
        settings.get_path("mcp_repository")
        or (project / "third_party" / "everquest1-mcp")
    )

    allakhazam_selected = settings.get_path("allakhazam_db_mirror")
    if allakhazam_selected:
        allakhazam_project, allakhazam_mirror = _allakhazam_paths(
            allakhazam_selected
        )
    else:
        allakhazam_project = DEFAULT_ALLAKHAZAM_PROJECT
        allakhazam_mirror = (
            DEFAULT_ALLAKHAZAM_PROJECT / "everquest.allakhazam.com"
        )

    goods_maps, brewall_maps = _map_pack_paths(
        settings.get_path("map_root") or None,
        eq_install,
    )

    return {
        "settings_path": str(settings.path.resolve()),
        "eq_install": str(eq_install.resolve()),
        "allakhazam_project": str(allakhazam_project.resolve()),
        "allakhazam_mirror": str(allakhazam_mirror.resolve()),
        "mcp_repository": str(mcp_repository.resolve()),
        "goods_maps": str(goods_maps.resolve()),
        "brewall_maps": str(brewall_maps.resolve()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve full-build source paths from EverQuestie's settings.ini."
        )
    )
    parser.add_argument(
        "--project-root",
        default=str(REPO_ROOT),
        help="EverQuestie repository root.",
    )
    parser.add_argument(
        "--settings",
        help=(
            "Optional settings.ini override. Defaults to "
            "%USERPROFILE%/.eqquest/settings.ini."
        ),
    )
    args = parser.parse_args(argv)

    print(
        json.dumps(
            resolve_builder_paths(
                project_root=args.project_root,
                settings_path=args.settings,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
