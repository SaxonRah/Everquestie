from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Any


MCP_RELATIVE_PATH = Path("third_party") / "everquest1-mcp"
MCP_LOCK_RELATIVE_PATH = Path("third_party") / "everquest1-mcp.lock.json"
MCP_EXPECTED_REMOTE = "https://github.com/ArtSabintsev/everquest1-mcp.git"


@dataclass(frozen=True, slots=True)
class MCPSourceProvenance:
    snapshot_path: str
    snapshot_mcp_commit: str
    snapshot_mcp_version: str
    snapshot_inventory_source_version: str
    snapshot_detail_source_version: str
    project_root: str
    repository_lock_path: str
    repository_lock_present: bool
    repository_lock_valid: bool
    repository_lock_error: str
    repository_lock_commit: str
    repository_lock_remote: str
    repository_lock_version: str
    snapshot_matches_repository_lock: bool | None
    local_matches_repository_lock: bool | None
    local_version_matches_repository_lock: bool | None
    repository_lock_remote_is_approved: bool | None
    parent_is_git_checkout: bool
    parent_gitlink_present: bool
    parent_gitlink_commit: str
    local_mcp_path: str
    local_mcp_present: bool
    local_mcp_is_git_checkout: bool
    local_mcp_commit: str
    local_mcp_remote: str
    local_mcp_version: str
    local_matches_snapshot: bool | None
    gitlink_matches_snapshot: bool | None
    local_matches_gitlink: bool | None
    expected_remote_matches_local: bool | None
    reproducible_lock_state: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run_git(args: list[str], cwd: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _read_snapshot_metadata(snapshot: Path) -> tuple[str, str, str, str]:
    if not snapshot.is_file():
        raise FileNotFoundError(snapshot)
    conn = sqlite3.connect(snapshot.as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        meta = {
            str(row["key"]): str(row["value"] or "")
            for row in conn.execute(
                "SELECT key, value FROM app_meta WHERE key IN ('eq_mcp_commit', 'eq_mcp_version')"
            )
        }
        source_versions: dict[str, str] = {}
        for row in conn.execute(
            """
            SELECT source_kind, source_version
            FROM source_pages
            WHERE source_kind IN ('mcp_local_snapshot', 'mcp_local_details')
            ORDER BY id
            """
        ):
            source_versions[str(row["source_kind"])] = str(row["source_version"] or "")
        return (
            meta.get("eq_mcp_commit", ""),
            meta.get("eq_mcp_version", ""),
            source_versions.get("mcp_local_snapshot", ""),
            source_versions.get("mcp_local_details", ""),
        )
    finally:
        conn.close()


def _package_version(mcp_path: Path) -> str:
    package = mcp_path / "package.json"
    if not package.is_file():
        return ""
    try:
        payload = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("version") or "").strip()


def _normalize_remote(value: str) -> str:
    value = str(value or "").strip()
    if value.endswith("/"):
        value = value[:-1]
    if value.endswith(".git"):
        value = value[:-4]
    return value.casefold()


def _compare(left: str, right: str) -> bool | None:
    if not left or not right:
        return None
    return left.casefold() == right.casefold()


def _read_repository_lock(
    project: Path,
) -> tuple[str, bool, bool, str, str, str, str]:
    lock_path = (project / MCP_LOCK_RELATIVE_PATH).resolve()
    if not lock_path.is_file():
        return str(lock_path), False, False, "lock file is missing", "", "", ""
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return str(lock_path), True, False, f"invalid JSON: {exc}", "", "", ""
    if not isinstance(payload, dict):
        return str(lock_path), True, False, "lock root must be a JSON object", "", "", ""

    schema_version = payload.get("schema_version")
    repository = str(payload.get("repository") or "").strip()
    commit = str(payload.get("commit") or "").strip().casefold()
    package_version = str(payload.get("package_version") or "").strip()
    errors: list[str] = []
    if schema_version != 1:
        errors.append("schema_version must be 1")
    if not repository:
        errors.append("repository is missing")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        errors.append("commit must be a full 40-character Git SHA")
    if not package_version:
        errors.append("package_version is missing")
    return (
        str(lock_path),
        True,
        not errors,
        "; ".join(errors),
        commit,
        repository,
        package_version,
    )


def audit_mcp_source_provenance(
    snapshot_path: str | Path,
    *,
    project_root: str | Path,
    mcp_path: str | Path | None = None,
) -> MCPSourceProvenance:
    snapshot = Path(snapshot_path).expanduser().resolve()
    project = Path(project_root).expanduser().resolve()
    local = (
        Path(mcp_path).expanduser().resolve()
        if mcp_path is not None
        else (project / MCP_RELATIVE_PATH).resolve()
    )

    snapshot_commit, snapshot_version, inventory_version, detail_version = (
        _read_snapshot_metadata(snapshot)
    )
    (
        lock_path,
        lock_present,
        lock_valid,
        lock_error,
        lock_commit,
        lock_remote,
        lock_version,
    ) = _read_repository_lock(project)

    parent_is_git = bool(_run_git(["rev-parse", "--is-inside-work-tree"], project))
    gitlink_commit = ""
    gitlink_present = False
    if parent_is_git:
        tree_line = _run_git(["ls-tree", "HEAD", "--", MCP_RELATIVE_PATH.as_posix()], project)
        if tree_line:
            # Legacy diagnostic only. Repository-owned lock files are the canonical
            # dependency contract; a 160000 gitlink is no longer required.
            prefix = tree_line.split("\t", 1)[0].split()
            if len(prefix) >= 3 and prefix[0] == "160000" and prefix[1] == "commit":
                gitlink_present = True
                gitlink_commit = prefix[2]

    local_present = (local / "package.json").is_file()
    local_is_git = False
    local_commit = ""
    local_remote = ""
    if local_present:
        local_is_git = bool(_run_git(["rev-parse", "--is-inside-work-tree"], local))
        if local_is_git:
            local_commit = _run_git(["rev-parse", "HEAD"], local)
            local_remote = _run_git(["remote", "get-url", "origin"], local)
    local_version = _package_version(local) if local_present else ""

    local_matches_snapshot = _compare(local_commit, snapshot_commit)
    gitlink_matches_snapshot = _compare(gitlink_commit, snapshot_commit)
    local_matches_gitlink = _compare(local_commit, gitlink_commit)
    remote_match = (
        _normalize_remote(local_remote) == _normalize_remote(MCP_EXPECTED_REMOTE)
        if local_remote
        else None
    )
    snapshot_matches_lock = _compare(snapshot_commit, lock_commit) if lock_valid else None
    local_matches_lock = _compare(local_commit, lock_commit) if lock_valid else None
    local_version_matches_lock = _compare(local_version, lock_version) if lock_valid else None
    lock_remote_approved = (
        _normalize_remote(lock_remote) == _normalize_remote(MCP_EXPECTED_REMOTE)
        if lock_valid and lock_remote
        else None
    )

    if lock_present and not lock_valid:
        lock_state = "repository_lock_invalid"
    elif lock_valid and lock_remote_approved is False:
        lock_state = "repository_lock_remote_unapproved"
    elif lock_valid and snapshot_matches_lock is False:
        lock_state = "repository_lock_differs_from_snapshot"
    elif lock_valid and local_matches_lock is False:
        lock_state = "local_checkout_differs_from_repository_lock"
    elif lock_valid and local_version_matches_lock is False:
        lock_state = "local_version_differs_from_repository_lock"
    elif (
        lock_valid
        and snapshot_matches_lock is True
        and local_matches_lock is True
        and local_version_matches_lock is True
        and remote_match is True
    ):
        lock_state = "reproducibly_locked"
    elif lock_valid and snapshot_matches_lock is True:
        lock_state = "snapshot_matches_repository_lock_local_unavailable"
    elif lock_valid:
        lock_state = "repository_lock_present_snapshot_unknown"
    elif gitlink_present and snapshot_commit and gitlink_matches_snapshot is True:
        lock_state = "snapshot_matches_parent_gitlink"
    elif gitlink_present:
        lock_state = "parent_gitlink_present_but_differs_or_snapshot_unknown"
    elif snapshot_commit:
        lock_state = "snapshot_records_commit_but_parent_has_no_gitlink"
    else:
        lock_state = "no_reproducible_mcp_commit_recorded"

    return MCPSourceProvenance(
        snapshot_path=str(snapshot),
        snapshot_mcp_commit=snapshot_commit,
        snapshot_mcp_version=snapshot_version,
        snapshot_inventory_source_version=inventory_version,
        snapshot_detail_source_version=detail_version,
        project_root=str(project),
        repository_lock_path=lock_path,
        repository_lock_present=lock_present,
        repository_lock_valid=lock_valid,
        repository_lock_error=lock_error,
        repository_lock_commit=lock_commit,
        repository_lock_remote=lock_remote,
        repository_lock_version=lock_version,
        snapshot_matches_repository_lock=snapshot_matches_lock,
        local_matches_repository_lock=local_matches_lock,
        local_version_matches_repository_lock=local_version_matches_lock,
        repository_lock_remote_is_approved=lock_remote_approved,
        parent_is_git_checkout=parent_is_git,
        parent_gitlink_present=gitlink_present,
        parent_gitlink_commit=gitlink_commit,
        local_mcp_path=str(local),
        local_mcp_present=local_present,
        local_mcp_is_git_checkout=local_is_git,
        local_mcp_commit=local_commit,
        local_mcp_remote=local_remote,
        local_mcp_version=local_version,
        local_matches_snapshot=local_matches_snapshot,
        gitlink_matches_snapshot=gitlink_matches_snapshot,
        local_matches_gitlink=local_matches_gitlink,
        expected_remote_matches_local=remote_match,
        reproducible_lock_state=lock_state,
    )


def mcp_source_provenance_text(report: MCPSourceProvenance) -> str:
    def yn(value: bool | None) -> str:
        if value is None:
            return "unknown"
        return "yes" if value else "NO"

    lines = [
        "EverQuestie MCP source provenance audit",
        "",
        f"Snapshot: {report.snapshot_path}",
        f"  producer commit: {report.snapshot_mcp_commit or 'not recorded'}",
        f"  MCP version: {report.snapshot_mcp_version or 'not recorded'}",
        f"  inventory source version: {report.snapshot_inventory_source_version or 'not recorded'}",
        f"  detail source version: {report.snapshot_detail_source_version or 'not recorded'}",
        "",
        f"Repository MCP lock: {report.repository_lock_path}",
        f"  present: {yn(report.repository_lock_present)}",
        f"  valid: {yn(report.repository_lock_valid)}",
        f"  commit: {report.repository_lock_commit or 'not recorded'}",
        f"  package version: {report.repository_lock_version or 'not recorded'}",
        f"  repository: {report.repository_lock_remote or 'not recorded'}",
        f"  approved upstream: {yn(report.repository_lock_remote_is_approved)}",
    ]
    if report.repository_lock_error:
        lines.append(f"  error: {report.repository_lock_error}")
    lines.extend(
        [
            "",
            f"Project: {report.project_root}",
            f"  Git checkout: {yn(report.parent_is_git_checkout)}",
            f"  legacy MCP gitlink present: {yn(report.parent_gitlink_present)}",
            f"  legacy MCP gitlink commit: {report.parent_gitlink_commit or 'none'}",
            "",
            f"Local MCP: {report.local_mcp_path}",
            f"  checkout present: {yn(report.local_mcp_present)}",
            f"  Git checkout: {yn(report.local_mcp_is_git_checkout)}",
            f"  HEAD: {report.local_mcp_commit or 'not available'}",
            f"  package version: {report.local_mcp_version or 'not available'}",
            f"  origin: {report.local_mcp_remote or 'not available'}",
            "",
            f"Snapshot producer matches repository lock: {yn(report.snapshot_matches_repository_lock)}",
            f"Local HEAD matches repository lock: {yn(report.local_matches_repository_lock)}",
            f"Local package version matches repository lock: {yn(report.local_version_matches_repository_lock)}",
            f"Local HEAD matches snapshot producer: {yn(report.local_matches_snapshot)}",
            f"Legacy parent gitlink matches snapshot producer: {yn(report.gitlink_matches_snapshot)}",
            f"Local origin matches approved upstream: {yn(report.expected_remote_matches_local)}",
            f"Reproducible lock state: {report.reproducible_lock_state}",
            "",
            "Boundary: this audit is read-only. It does not fetch, checkout, update, build, or modify MCP/source knowledge.",
        ]
    )
    return "\n".join(lines)
