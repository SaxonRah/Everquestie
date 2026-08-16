from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3
import subprocess
from typing import Any

from .mcp_source_lock import (
    MCP_EXPECTED_REMOTE,
    MCP_RELATIVE_PATH,
    inspect_local_mcp_source_lock,
    normalize_git_remote,
    read_mcp_source_lock,
)


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


def _compare(left: str, right: str) -> bool | None:
    if not left or not right:
        return None
    return left.casefold() == right.casefold()


def audit_mcp_source_provenance(
    snapshot_path: str | Path,
    *,
    project_root: str | Path,
    mcp_path: str | Path | None = None,
) -> MCPSourceProvenance:
    snapshot = Path(snapshot_path).expanduser().resolve()
    project = Path(project_root).expanduser().resolve()
    snapshot_commit, snapshot_version, inventory_version, detail_version = (
        _read_snapshot_metadata(snapshot)
    )

    lock_read = read_mcp_source_lock(project)
    lock = lock_read.lock
    local_status = inspect_local_mcp_source_lock(project, mcp_path=mcp_path)

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

    lock_commit = lock.commit if lock is not None else ""
    lock_remote = lock.repository if lock is not None else ""
    lock_version = lock.package_version if lock is not None else ""
    snapshot_matches_lock = _compare(snapshot_commit, lock_commit)
    local_matches_lock = local_status.commit_matches_lock
    local_version_matches_lock = local_status.package_version_matches_lock
    lock_remote_approved = (
        normalize_git_remote(lock_remote) == normalize_git_remote(MCP_EXPECTED_REMOTE)
        if lock_remote
        else None
    )

    local_commit = local_status.commit
    local_remote = local_status.remote
    local_version = local_status.package_version
    local_matches_snapshot = _compare(local_commit, snapshot_commit)
    gitlink_matches_snapshot = _compare(gitlink_commit, snapshot_commit)
    local_matches_gitlink = _compare(local_commit, gitlink_commit)
    remote_match = (
        normalize_git_remote(local_remote) == normalize_git_remote(MCP_EXPECTED_REMOTE)
        if local_remote
        else None
    )

    if lock_read.present and not lock_read.valid:
        lock_state = "repository_lock_invalid"
    elif lock is not None and snapshot_matches_lock is False:
        lock_state = "repository_lock_differs_from_snapshot"
    elif lock is not None and local_matches_lock is False:
        lock_state = "local_checkout_differs_from_repository_lock"
    elif lock is not None and local_version_matches_lock is False:
        lock_state = "local_version_differs_from_repository_lock"
    elif (
        lock is not None
        and snapshot_matches_lock is True
        and local_status.ok
        and remote_match is True
    ):
        lock_state = "reproducibly_locked"
    elif lock is not None and snapshot_matches_lock is True:
        lock_state = "snapshot_matches_repository_lock_local_unavailable"
    elif lock is not None:
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
        repository_lock_path=str(lock_read.path),
        repository_lock_present=lock_read.present,
        repository_lock_valid=lock_read.valid,
        repository_lock_error=lock_read.error,
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
        local_mcp_path=str(local_status.mcp_path),
        local_mcp_present=local_status.checkout_present,
        local_mcp_is_git_checkout=local_status.git_checkout,
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
