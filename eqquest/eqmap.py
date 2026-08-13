from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Iterable


_LAYER_SUFFIX = re.compile(r"_(?P<layer>[1-3])$")


def normalize_map_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def is_layer_stem(stem: str) -> bool:
    return _LAYER_SUFFIX.search(stem) is not None


def base_stem(stem: str) -> str:
    return _LAYER_SUFFIX.sub("", stem)


def game_to_map(x: float, y: float, z: float = 0.0) -> tuple[float, float, float]:
    """Convert EverQuest /loc coordinates (X,Y,Z) to native map-file coordinates.

    EQ prints /loc as Y, X, Z. The log parser already normalizes that into X,Y,Z.
    Native map files store the horizontal axes with reversed signs.
    """
    return -float(x), -float(y), float(z)


def map_to_game(x: float, y: float, z: float = 0.0) -> tuple[float, float, float]:
    return -float(x), -float(y), float(z)


@dataclass(slots=True)
class MapLine:
    x0: float
    y0: float
    z0: float
    x1: float
    y1: float
    z1: float
    r: int
    g: int
    b: int
    source_line: int = 0


@dataclass(slots=True)
class MapPoint:
    x: float
    y: float
    z: float
    r: int
    g: int
    b: int
    size: int
    text: str
    source_line: int = 0

    @property
    def display_text(self) -> str:
        return self.text.replace("_", " ")


@dataclass(slots=True)
class MapLayer:
    layer: int
    path: Path
    lines: list[MapLine] = field(default_factory=list)
    points: list[MapPoint] = field(default_factory=list)
    ignored: int = 0

    def bounds(self) -> tuple[float, float, float, float] | None:
        xs: list[float] = []
        ys: list[float] = []
        for line in self.lines:
            xs.extend((line.x0, line.x1))
            ys.extend((line.y0, line.y1))
        for point in self.points:
            xs.append(point.x)
            ys.append(point.y)
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)


@dataclass(slots=True)
class ZoneMap:
    stem: str
    root: Path
    layers: dict[int, MapLayer]

    @property
    def base_path(self) -> Path:
        return self.root / f"{self.stem}.txt"

    def bounds(self, enabled_layers: Iterable[int] | None = None) -> tuple[float, float, float, float] | None:
        wanted = set(enabled_layers) if enabled_layers is not None else set(self.layers)
        bounds = [self.layers[i].bounds() for i in wanted if i in self.layers]
        bounds = [b for b in bounds if b is not None]
        if not bounds:
            return None
        return (
            min(b[0] for b in bounds),
            min(b[1] for b in bounds),
            max(b[2] for b in bounds),
            max(b[3] for b in bounds),
        )


class EQMapParseError(ValueError):
    pass


def _number(value: str) -> float:
    return float(value.strip())


def _color(value: str) -> int:
    return max(0, min(255, int(float(value.strip()))))


def parse_map_file(path: str | Path, *, layer: int | None = None) -> MapLayer:
    path = Path(path)
    if layer is None:
        m = _LAYER_SUFFIX.search(path.stem)
        layer = int(m.group("layer")) if m else 0

    result = MapLayer(layer=layer, path=path)
    text = path.read_text(encoding="utf-8", errors="replace")

    for line_no, raw in enumerate(text.splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        prefix = raw[:1].upper()
        payload = raw[1:].strip()

        try:
            if prefix == "L":
                parts = [part.strip() for part in payload.split(",")]
                if len(parts) < 9:
                    raise EQMapParseError(f"line {line_no}: L record has {len(parts)} fields")
                result.lines.append(MapLine(
                    _number(parts[0]), _number(parts[1]), _number(parts[2]),
                    _number(parts[3]), _number(parts[4]), _number(parts[5]),
                    _color(parts[6]), _color(parts[7]), _color(parts[8]),
                    source_line=line_no,
                ))
            elif prefix == "P":
                parts = [part.strip() for part in payload.split(",", 7)]
                if len(parts) < 8:
                    raise EQMapParseError(f"line {line_no}: P record has {len(parts)} fields")
                result.points.append(MapPoint(
                    _number(parts[0]), _number(parts[1]), _number(parts[2]),
                    _color(parts[3]), _color(parts[4]), _color(parts[5]),
                    max(1, min(3, int(float(parts[6])))),
                    parts[7], source_line=line_no,
                ))
            else:
                result.ignored += 1
        except (ValueError, EQMapParseError):
            result.ignored += 1

    return result


def load_zone_map(path: str | Path) -> ZoneMap:
    path = Path(path)
    stem = base_stem(path.stem)
    root = path.parent
    layers: dict[int, MapLayer] = {}
    for layer in range(4):
        candidate = root / (f"{stem}.txt" if layer == 0 else f"{stem}_{layer}.txt")
        if candidate.exists():
            layers[layer] = parse_map_file(candidate, layer=layer)
    if not layers:
        raise FileNotFoundError(path)
    return ZoneMap(stem=stem, root=root, layers=layers)


def discover_base_maps(root: str | Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        (p for p in root.glob("*.txt") if not is_layer_stem(p.stem)),
        key=lambda p: p.stem.casefold(),
    )


def _zone_words(zone_name: str) -> list[str]:
    stop = {"the", "of", "a", "an"}
    return [
        normalize_map_name(w)
        for w in re.findall(r"[A-Za-z0-9`']+", zone_name)
        if normalize_map_name(w) and normalize_map_name(w) not in stop
    ]


def resolve_map_for_zone(
    zone_name: str,
    root: str | Path,
    *,
    bound_stem: str | None = None,
    hinted_stem: str | None = None,
) -> Path | None:
    """Best-effort map resolver. Explicit bindings always win.

    EverQuest logs expose long zone names while map files are normally named by
    client short names. For unknown short names the UI lets the user bind once and
    persists that choice. This resolver handles the easy/common cases automatically.
    """
    root = Path(root)
    maps = discover_base_maps(root)
    if not maps:
        return None

    by_norm = {normalize_map_name(p.stem): p for p in maps}
    for stem in (bound_stem, hinted_stem):
        if stem:
            candidate = by_norm.get(normalize_map_name(stem))
            if candidate:
                return candidate

    full = normalize_map_name(zone_name)
    if full in by_norm:
        return by_norm[full]

    words = _zone_words(zone_name)
    exact_word_matches = [by_norm[w] for w in words if w in by_norm]
    if len({p for p in exact_word_matches}) == 1:
        return exact_word_matches[0]

    candidates: list[Path] = []
    for norm, path in by_norm.items():
        if len(norm) < 4:
            continue
        if norm in full or full in norm:
            candidates.append(path)
    unique = list(dict.fromkeys(candidates))
    return unique[0] if len(unique) == 1 else None
