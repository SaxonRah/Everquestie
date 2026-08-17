from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
import zipfile


KNOWLEDGE_DB_FILENAME = "everquestie-knowledge.sqlite3"
RELEASE_MANIFEST_FILENAME = "release-manifest.json"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True, slots=True)
class ReleaseArchiveAudit:
    archive: Path
    status: str
    release_version: str
    layout: str
    manifest_member: str
    executable_member: str
    knowledge_member: str
    source_knowledge_verified: bool
    archive_files: int
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "archive": str(self.archive),
            "status": self.status,
            "release_version": self.release_version,
            "layout": self.layout,
            "manifest_member": self.manifest_member,
            "executable_member": self.executable_member,
            "knowledge_member": self.knowledge_member,
            "source_knowledge_verified": self.source_knowledge_verified,
            "archive_files": self.archive_files,
            "errors": list(self.errors),
        }


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            total += len(block)
    return digest.hexdigest(), total


def _sha256_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with zf.open(info, "r") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            total += len(block)
    return digest.hexdigest(), total


def _safe_archive_path(value: str) -> bool:
    if not value or "\x00" in value or "\\" in value:
        return False
    if value.startswith("/") or _DRIVE_PATH_RE.match(value):
        return False
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        return False
    return True


def _manifest_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _manifest_sha(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return text if _SHA256_RE.fullmatch(text) else ""


def audit_release_archive(
    archive_path: str | Path,
    *,
    source_knowledge: str | Path | None = None,
    expected_version: str = "",
    require_source_knowledge: bool = False,
) -> ReleaseArchiveAudit:
    """Validate the final distributable ZIP against its own release manifest.

    This is a post-packaging, read-only gate. It does not extract files to disk, rebuild
    knowledge, run PyInstaller, or mutate the source snapshot. A supplied
    ``source_knowledge`` path anchors the manifest's knowledge hash/size to the exact
    audited snapshot used by the release coordinator.
    """
    archive = Path(archive_path).expanduser().resolve()
    errors: list[str] = []
    release_version = ""
    layout = ""
    manifest_member = ""
    executable_member = ""
    knowledge_member = ""
    source_verified = False
    archive_files = 0

    if not archive.is_file():
        return ReleaseArchiveAudit(
            archive=archive,
            status="error",
            release_version="",
            layout="",
            manifest_member="",
            executable_member="",
            knowledge_member="",
            source_knowledge_verified=False,
            archive_files=0,
            errors=(f"release archive does not exist: {archive}",),
        )

    source_path: Path | None = None
    source_hash = ""
    source_bytes = 0
    if source_knowledge is not None:
        source_path = Path(source_knowledge).expanduser().resolve()
        if not source_path.is_file():
            errors.append(f"source knowledge snapshot does not exist: {source_path}")
        else:
            source_hash, source_bytes = _sha256_file(source_path)
    elif require_source_knowledge:
        errors.append("source knowledge snapshot is required for this release audit")

    try:
        with zipfile.ZipFile(archive, "r") as zf:
            infos = zf.infolist()
            file_infos = [info for info in infos if not info.is_dir()]
            archive_files = len(file_infos)

            normalized_seen: dict[str, str] = {}
            exact_files: dict[str, zipfile.ZipInfo] = {}
            manifest_candidates: list[zipfile.ZipInfo] = []
            for info in infos:
                name = info.filename
                if not _safe_archive_path(name.rstrip("/")):
                    errors.append(f"unsafe or non-portable ZIP member path: {name!r}")
                    continue
                folded = name.rstrip("/").casefold()
                previous = normalized_seen.get(folded)
                if previous is not None:
                    errors.append(
                        f"duplicate/case-colliding ZIP members: {previous!r} and {name!r}"
                    )
                else:
                    normalized_seen[folded] = name
                if info.flag_bits & 0x1:
                    errors.append(f"encrypted ZIP member is not allowed: {name!r}")
                unix_mode = (info.external_attr >> 16) & 0o170000
                if unix_mode == 0o120000:
                    errors.append(f"symbolic-link ZIP member is not allowed: {name!r}")
                if not info.is_dir():
                    exact_files[name] = info
                    if PurePosixPath(name).name.casefold() == RELEASE_MANIFEST_FILENAME:
                        manifest_candidates.append(info)

            if len(manifest_candidates) != 1:
                errors.append(
                    "release archive must contain exactly one release-manifest.json; "
                    f"found {len(manifest_candidates)}"
                )
                manifest_info = None
            else:
                manifest_info = manifest_candidates[0]
                manifest_member = manifest_info.filename

            bad_crc = None
            try:
                bad_crc = zf.testzip()
            except (RuntimeError, zipfile.BadZipFile) as exc:
                errors.append(f"ZIP integrity test failed: {exc}")
            if bad_crc:
                errors.append(f"ZIP CRC check failed for member: {bad_crc!r}")

            manifest: dict[str, Any] = {}
            if manifest_info is not None:
                try:
                    payload = json.loads(zf.read(manifest_info).decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
                    errors.append(f"release manifest is not valid UTF-8 JSON: {exc}")
                else:
                    if not isinstance(payload, dict):
                        errors.append("release manifest root must be a JSON object")
                    else:
                        manifest = payload

            if manifest:
                if str(manifest.get("product") or "") != "EverQuestie":
                    errors.append("release manifest product must be 'EverQuestie'")
                release_version = str(manifest.get("release_version") or "").strip()
                if not release_version:
                    errors.append("release manifest has no release_version")
                wanted_version = str(expected_version or "").strip()
                if wanted_version and release_version != wanted_version:
                    errors.append(
                        f"release version mismatch: manifest={release_version!r}, "
                        f"expected={wanted_version!r}"
                    )

                layout = str(manifest.get("layout") or "").strip()
                if layout not in {"one-folder", "one-file"}:
                    errors.append(f"unsupported release layout: {layout!r}")

                executable = manifest.get("executable")
                if not isinstance(executable, dict):
                    errors.append("release manifest executable field must be an object")
                else:
                    executable_member = str(executable.get("path") or "").strip()
                    expected_hash = _manifest_sha(executable.get("sha256"))
                    expected_bytes = _manifest_int(executable.get("bytes"))
                    if not _safe_archive_path(executable_member):
                        errors.append(
                            f"manifest executable path is unsafe or invalid: {executable_member!r}"
                        )
                    info = exact_files.get(executable_member)
                    if info is None:
                        errors.append(
                            f"manifest executable is missing from archive: {executable_member!r}"
                        )
                    else:
                        actual_hash, actual_bytes = _sha256_member(zf, info)
                        if not expected_hash:
                            errors.append("manifest executable sha256 is invalid")
                        elif actual_hash != expected_hash:
                            errors.append("archived executable sha256 does not match manifest")
                        if expected_bytes is None:
                            errors.append("manifest executable bytes is invalid")
                        elif actual_bytes != expected_bytes:
                            errors.append("archived executable byte count does not match manifest")

                knowledge = manifest.get("knowledge")
                if not isinstance(knowledge, dict):
                    errors.append("release manifest knowledge field must be an object")
                else:
                    filename = str(knowledge.get("filename") or "").strip()
                    if filename != KNOWLEDGE_DB_FILENAME:
                        errors.append(
                            f"manifest knowledge filename must be {KNOWLEDGE_DB_FILENAME!r}"
                        )
                    snapshot_version = str(knowledge.get("snapshot_version") or "").strip()
                    if release_version and snapshot_version != release_version:
                        errors.append(
                            "manifest knowledge snapshot_version does not match release_version"
                        )
                    expected_hash = _manifest_sha(knowledge.get("sha256"))
                    expected_bytes = _manifest_int(knowledge.get("bytes"))
                    if not expected_hash:
                        errors.append("manifest knowledge sha256 is invalid")
                    if expected_bytes is None:
                        errors.append("manifest knowledge bytes is invalid")

                    for flag in (
                        "immutable_runtime",
                        "approved_zone_aliases_compiled",
                        "approved_travel_supplements_compiled",
                        "reviewed_release_inputs_verified",
                        "map_catalog_verified",
                    ):
                        if knowledge.get(flag) is not True:
                            errors.append(f"manifest knowledge {flag} must be true")

                    map_sources = knowledge.get("map_catalog_sources")
                    if map_sources != ["Goods", "Brewall"]:
                        errors.append(
                            "manifest knowledge map_catalog_sources must be exactly "
                            "['Goods', 'Brewall']"
                        )

                    if source_path is not None and source_path.is_file():
                        if expected_hash and source_hash != expected_hash:
                            errors.append(
                                "source knowledge snapshot sha256 does not match release manifest"
                            )
                        elif expected_bytes is not None and source_bytes != expected_bytes:
                            errors.append(
                                "source knowledge snapshot byte count does not match release manifest"
                            )
                        elif expected_hash and expected_bytes is not None:
                            source_verified = True

                    embedded = knowledge.get("embedded")
                    knowledge_path = str(knowledge.get("path") or "").strip()
                    integrity = str(knowledge.get("packaging_integrity") or "").strip()
                    external_sqlite = [
                        info.filename
                        for info in file_infos
                        if PurePosixPath(info.filename).suffix.casefold() == ".sqlite3"
                    ]
                    if layout == "one-folder":
                        if embedded is not False:
                            errors.append("one-folder release knowledge embedded flag must be false")
                        if integrity != "byte-identical-copy":
                            errors.append(
                                "one-folder release packaging_integrity must be 'byte-identical-copy'"
                            )
                        if not _safe_archive_path(knowledge_path):
                            errors.append(
                                f"manifest knowledge path is unsafe or invalid: {knowledge_path!r}"
                            )
                        info = exact_files.get(knowledge_path)
                        if info is None:
                            errors.append(
                                f"manifest knowledge DB is missing from archive: {knowledge_path!r}"
                            )
                        else:
                            knowledge_member = knowledge_path
                            actual_hash, actual_bytes = _sha256_member(zf, info)
                            if expected_hash and actual_hash != expected_hash:
                                errors.append("archived knowledge sha256 does not match manifest")
                            if expected_bytes is not None and actual_bytes != expected_bytes:
                                errors.append(
                                    "archived knowledge byte count does not match manifest"
                                )
                        if external_sqlite != [knowledge_path]:
                            errors.append(
                                "one-folder archive must contain exactly the declared knowledge "
                                f"SQLite DB; found {external_sqlite!r}"
                            )
                    elif layout == "one-file":
                        if embedded is not True:
                            errors.append("one-file release knowledge embedded flag must be true")
                        if integrity != "source-hash-stable-during-embed":
                            errors.append(
                                "one-file release packaging_integrity must be "
                                "'source-hash-stable-during-embed'"
                            )
                        expected_embedded = f"embedded:{KNOWLEDGE_DB_FILENAME}"
                        if knowledge_path != expected_embedded:
                            errors.append(
                                f"one-file manifest knowledge path must be {expected_embedded!r}"
                            )
                        if external_sqlite:
                            errors.append(
                                "one-file archive must not contain an external SQLite DB; "
                                f"found {external_sqlite!r}"
                            )

                if manifest.get("user_state_included") is not False:
                    errors.append("release manifest user_state_included must be false")
                if manifest.get("builder_database_included") is not False:
                    errors.append("release manifest builder_database_included must be false")

    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        errors.append(f"unable to read release ZIP: {exc}")

    return ReleaseArchiveAudit(
        archive=archive,
        status="ok" if not errors else "error",
        release_version=release_version,
        layout=layout,
        manifest_member=manifest_member,
        executable_member=executable_member,
        knowledge_member=knowledge_member,
        source_knowledge_verified=source_verified,
        archive_files=archive_files,
        errors=tuple(errors),
    )
