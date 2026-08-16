from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess


MCP_RELATIVE_PATH = Path("third_party") / "everquest1-mcp"
MCP_LOCK_RELATIVE_PATH = Path("third_party") / "everquest1-mcp.lock.json"
MCP_EXPECTED_REMOTE = "https://github.com/ArtSabintsev/everquest1-mcp.git"


@dataclass(frozen=True, slots=True)
class MCPSourceLock:
    path: Path
    schema_version: int
    name: str
    repository: str
    commit: str
    package_version: str
    provenance: str = ""


@dataclass(frozen=True, slots=True)
class MCPSourceLockRead:
    path: Path
    present: bool
    lock: MCPSourceLock | None
    error: str = ""

    @property
    def valid(self) -> bool:
        return self.lock is not None


@dataclass(frozen=True, slots=True)
class MCPLocalSourceLockStatus:
    lock_read: MCPSourceLockRead
    mcp_path: Path
    checkout_present: bool
    git_checkout: bool
    commit: str
    remote: str
    package_version: str
    commit_matches_lock: bool | None
    remote_matches_lock: bool | None
    package_version_matches_lock: bool | None

    @property
    def ok(self) -> bool:
        return bool(
            self.lock_read.valid
            and self.checkout_present
            and self.git_checkout
            and self.commit_matches_lock is True
            and self.remote_matches_lock is True
            and self.package_version_matches_lock is True
        )

    def failure_reason(self) -> str:
        if not self.lock_read.present:
            return f"MCP source lock is missing: {self.lock_read.path}"
        if not self.lock_read.valid:
            return f"MCP source lock is invalid: {self.lock_read.error}"
        if not self.checkout_present:
            return f"MCP checkout is missing or incomplete: {self.mcp_path}"
        if not self.git_checkout:
            return f"MCP builder source is not a Git checkout: {self.mcp_path}"
        lock = self.lock_read.lock
        assert lock is not None
        if self.remote_matches_lock is False:
            return (
                f"MCP origin '{self.remote or 'not available'}' does not match locked "
                f"repository '{lock.repository}'."
            )
        if self.commit_matches_lock is False:
            return (
                f"MCP HEAD {self.commit or 'not available'} does not match repository lock "
                f"{lock.commit}. Run .\\tools\\setup_mcp_submodule.ps1 to restore the locked builder source."
            )
        if self.package_version_matches_lock is False:
            return (
                f"MCP package version '{self.package_version or 'not available'}' does not match "
                f"repository lock '{lock.package_version}'."
            )
        return "MCP source lock could not be fully verified."


def normalize_git_remote(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.casefold()


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


def _package_version(mcp_path: Path) -> str:
    package = mcp_path / "package.json"
    if not package.is_file():
        return ""
    try:
        payload = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("version") or "").strip()


def read_mcp_source_lock(project_root: str | Path) -> MCPSourceLockRead:
    project = Path(project_root).expanduser().resolve()
    path = (project / MCP_LOCK_RELATIVE_PATH).resolve()
    if not path.is_file():
        return MCPSourceLockRead(path, False, None, "lock file is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return MCPSourceLockRead(path, True, None, f"invalid JSON: {exc}")
    if not isinstance(payload, dict):
        return MCPSourceLockRead(path, True, None, "lock root must be a JSON object")

    try:
        schema_version = int(payload.get("schema_version"))
    except (TypeError, ValueError):
        schema_version = 0
    name = str(payload.get("name") or "").strip()
    repository = str(payload.get("repository") or "").strip()
    commit = str(payload.get("commit") or "").strip().casefold()
    package_version = str(payload.get("package_version") or "").strip()
    provenance = str(payload.get("provenance") or "").strip()

    errors: list[str] = []
    if schema_version != 1:
        errors.append("schema_version must be 1")
    if name != "everquest1-mcp":
        errors.append("name must be 'everquest1-mcp'")
    if not repository:
        errors.append("repository is missing")
    elif normalize_git_remote(repository) != normalize_git_remote(MCP_EXPECTED_REMOTE):
        errors.append("repository is not the approved everquest1-mcp upstream")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        errors.append("commit must be a full 40-character Git SHA")
    if not package_version:
        errors.append("package_version is missing")
    if errors:
        return MCPSourceLockRead(path, True, None, "; ".join(errors))

    return MCPSourceLockRead(
        path,
        True,
        MCPSourceLock(
            path=path,
            schema_version=schema_version,
            name=name,
            repository=repository,
            commit=commit,
            package_version=package_version,
            provenance=provenance,
        ),
        "",
    )


def inspect_local_mcp_source_lock(
    project_root: str | Path,
    *,
    mcp_path: str | Path | None = None,
) -> MCPLocalSourceLockStatus:
    project = Path(project_root).expanduser().resolve()
    local = (
        Path(mcp_path).expanduser().resolve()
        if mcp_path is not None
        else (project / MCP_RELATIVE_PATH).resolve()
    )
    lock_read = read_mcp_source_lock(project)
    lock = lock_read.lock

    checkout_present = (local / "package.json").is_file()
    git_checkout = False
    commit = ""
    remote = ""
    if checkout_present:
        git_checkout = _run_git(["rev-parse", "--is-inside-work-tree"], local) == "true"
        if git_checkout:
            commit = _run_git(["rev-parse", "HEAD"], local).casefold()
            remote = _run_git(["remote", "get-url", "origin"], local)
    package_version = _package_version(local) if checkout_present else ""

    if lock is None:
        commit_match = None
        remote_match = None
        version_match = None
    else:
        commit_match = bool(commit) and commit == lock.commit
        remote_match = bool(remote) and normalize_git_remote(remote) == normalize_git_remote(lock.repository)
        version_match = bool(package_version) and package_version == lock.package_version

    return MCPLocalSourceLockStatus(
        lock_read=lock_read,
        mcp_path=local,
        checkout_present=checkout_present,
        git_checkout=git_checkout,
        commit=commit,
        remote=remote,
        package_version=package_version,
        commit_matches_lock=commit_match,
        remote_matches_lock=remote_match,
        package_version_matches_lock=version_match,
    )


def require_local_mcp_source_lock(
    project_root: str | Path,
    *,
    mcp_path: str | Path | None = None,
) -> MCPLocalSourceLockStatus:
    status = inspect_local_mcp_source_lock(project_root, mcp_path=mcp_path)
    if not status.ok:
        raise ValueError(status.failure_reason())
    return status
