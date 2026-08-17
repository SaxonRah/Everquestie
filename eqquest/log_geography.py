from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LogGeography:
    zone: str | None = None
    location: tuple[float, float, float] | None = None


def _clean_zone(value: str | None) -> str | None:
    cleaned = " ".join(str(value or "").split()).strip()
    return cleaned or None


def recover_log_geography(log_path: str | Path, parser) -> LogGeography | None:
    """Recover only geography proven by ordered EverQuest log boundaries.

    Explicit ``You have entered ...`` establishes a zone and invalidates any older
    ``/loc``. ``Welcome to EverQuest!`` is a hard loss-of-geography boundary: both zone
    and location become unknown until a later explicit zone entry. A ``/loc`` observed
    while the zone is unknown is intentionally not projected into any map.

    ``None`` means the file could not be read. A ``LogGeography`` whose fields are both
    ``None`` means the file was read successfully but its latest boundary does not prove
    current geography.
    """
    zone: str | None = None
    location: tuple[float, float, float] | None = None
    try:
        with Path(log_path).open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if (
                    "You have entered " not in line
                    and "Welcome to EverQuest!" not in line
                    and "Your Location is " not in line
                ):
                    continue
                event = parser.parse_line(line)
                if event is None:
                    continue
                kind = str(event.kind or "").casefold()
                if kind == "welcome":
                    zone = None
                    location = None
                elif kind == "zone" and event.zone:
                    zone = _clean_zone(event.zone)
                    location = None
                elif kind == "loc" and zone:
                    location = (
                        float(event.fields["x"]),
                        float(event.fields["y"]),
                        float(event.fields["z"]),
                    )
    except (OSError, PermissionError):
        return None
    return LogGeography(zone=zone, location=location)
