from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from typing import Any


MCP_REPO_URL = "https://github.com/ArtSabintsev/everquest1-mcp.git"
MCP_LOCAL_SEARCH_TOOL = "search_all_local_data"


ONLINE_TOOLS: dict[str, str] = {
    "All online sources": "search_all",
    "Quest guides (all sources)": "search_quests",
    "Tradeskills (all sources)": "search_tradeskills",
    "Allakhazam — general": "search_eq",
    "Allakhazam — spells": "search_spells",
    "Allakhazam — items": "search_items",
    "Allakhazam — NPCs": "search_npcs",
    "Allakhazam — zones": "search_zones",
    "Almar's Guides": "search_almars",
    "EQResource": "search_eqresource",
    "Fanra's Wiki": "search_fanra",
    "EQ Traders": "search_eqtraders",
    "Lucy": "search_lucy",
    "RaidLoot": "search_raidloot",
    "EQInterface": "search_ui",
}


class MCPError(RuntimeError):
    pass


@dataclass(slots=True)
class MCPStatus:
    path: Path
    repo_present: bool
    built: bool
    node: str | None

    @property
    def ready(self) -> bool:
        return self.repo_present and self.built and bool(self.node)

    def summary(self) -> str:
        if not self.repo_present:
            return f"MCP repository not installed: {self.path}"
        if not self.node:
            return "Node.js was not found on PATH."
        if not self.built:
            return f"MCP repository present but not built (missing {self.path / 'dist' / 'index.js'})."
        return f"Ready: {self.path}"


def default_mcp_path(project_root: str | Path | None = None) -> Path:
    override = os.environ.get("EVERQUEST1_MCP_PATH")
    if override:
        return Path(override).expanduser()
    if project_root is None:
        project_root = Path(__file__).resolve().parents[1]
    return Path(project_root) / "third_party" / "everquest1-mcp"


def mcp_status(path: str | Path | None = None) -> MCPStatus:
    root = Path(path) if path else default_mcp_path()
    return MCPStatus(
        path=root,
        repo_present=(root / "package.json").is_file(),
        built=(root / "dist" / "index.js").is_file(),
        node=shutil.which("node"),
    )


def build_query_arguments(input_schema: dict[str, Any] | None, query_text: str) -> dict[str, Any]:
    """Map a human search string onto a discovered MCP tool schema.

    The upstream search tools conventionally use ``query``.  Schema introspection
    keeps EverQuestie resilient if a source instead calls the field name/term/search.
    """
    schema = input_schema or {}
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    preferred = ("query", "name", "term", "search", "text")
    for key in preferred:
        spec = props.get(key)
        if spec and spec.get("type", "string") == "string":
            return {key: query_text}
    for key in required:
        spec = props.get(key, {})
        if spec.get("type", "string") == "string":
            return {key: query_text}
    for key, spec in props.items():
        if spec.get("type", "string") == "string":
            return {key: query_text}
    if not props:
        return {"query": query_text}
    raise MCPError("Could not map the search text onto this tool's input schema.")


def content_to_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in result.get("content") or []:
        if isinstance(item, dict):
            if item.get("type") == "text" and item.get("text") is not None:
                parts.append(str(item["text"]))
            else:
                parts.append(json.dumps(item, ensure_ascii=False, indent=2))
        else:
            parts.append(str(item))
    if not parts:
        return json.dumps(result, ensure_ascii=False, indent=2)
    return "\n\n".join(parts)


class MCPStdioClient:
    """Small synchronous MCP stdio client used only after explicit user action."""

    def __init__(self, repo_path: str | Path, *, eq_game_path: str | Path | None = None, timeout: float = 25.0):
        self.repo_path = Path(repo_path)
        self.eq_game_path = Path(eq_game_path) if eq_game_path else None
        self.timeout = timeout
        self.proc: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=40)
        self._next_id = 1

    def __enter__(self) -> "MCPStdioClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        status = mcp_status(self.repo_path)
        if not status.ready:
            raise MCPError(status.summary())
        env = os.environ.copy()
        if self.eq_game_path:
            env["EQ_GAME_PATH"] = str(self.eq_game_path)
        self.proc = subprocess.Popen(
            [status.node or "node", str(self.repo_path / "dist" / "index.js")],
            cwd=str(self.repo_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        threading.Thread(target=self._stdout_reader, daemon=True).start()
        threading.Thread(target=self._stderr_reader, daemon=True).start()
        self._initialize()

    def _stdout_reader(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict):
                self._messages.put(msg)

    def _stderr_reader(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip())

    def _send(self, payload: dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin:
            raise MCPError("MCP process is not running.")
        self.proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        deferred: list[dict[str, Any]] = []
        try:
            while time.monotonic() < deadline:
                if self.proc and self.proc.poll() is not None:
                    tail = "\n".join(self._stderr)
                    raise MCPError(f"MCP server exited with code {self.proc.returncode}.\n{tail}")
                try:
                    msg = self._messages.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
                except queue.Empty:
                    continue
                if msg.get("id") == request_id:
                    if "error" in msg:
                        raise MCPError(json.dumps(msg["error"], ensure_ascii=False))
                    return msg.get("result") or {}
                deferred.append(msg)
        finally:
            for msg in deferred:
                self._messages.put(msg)
        tail = "\n".join(self._stderr)
        raise MCPError(f"Timed out waiting for MCP method {method}.\n{tail}")

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "EverQuestie", "version": "0.13.0"},
            },
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list")
        return list(result.get("tools") or [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def search(self, tool_name: str, query_text: str) -> str:
        tools = self.list_tools()
        tool = next((t for t in tools if t.get("name") == tool_name), None)
        if tool is None:
            raise MCPError(f"The installed everquest1-mcp does not expose tool '{tool_name}'.")
        arguments = build_query_arguments(tool.get("inputSchema"), query_text)
        return content_to_text(self.call_tool(tool_name, arguments))

    def close(self) -> None:
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
