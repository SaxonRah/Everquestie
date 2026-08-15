from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable

from ..db import Database
from ..mcp_client import MCPError, MCPStdioClient, mcp_status


MCP_SNAPSHOT_TOOL = "save_data_snapshot"
MCP_SNAPSHOT_NAME = ".eq-mcp-snapshot.json"
MCP_DETAIL_SOURCE_URL = "eqclient+mcp://structured-local-details"
MCP_DETAIL_SOURCE_KEY = "structured-local-details-v1"

SYSTEM_KIND_MAP: dict[str, str] = {
    "spells": "spell",
    "zones": "zone",
    "factions": "faction",
    "achievements": "achievement",
    "aaAbilities": "aa",
    "overseerMinions": "overseer_agent",
    "overseerQuests": "overseer_quest",
    "mercenaries": "mercenary",
    "tributes": "tribute",
    "lore": "lore",
    "combatAbilities": "combat_ability",
}


@dataclass(slots=True)
class MCPSnapshotCapture:
    eq_path: Path
    mcp_path: Path
    snapshot: dict[str, Any]
    raw_json: str
    mcp_version: str = ""
    mcp_commit: str = ""


@dataclass(slots=True)
class MCPCompileResult:
    source_page_id: int = 0
    imported_by_kind: dict[str, int] = field(default_factory=dict)
    inventory_by_kind: dict[str, int] = field(default_factory=dict)
    system_counts: dict[str, int] = field(default_factory=dict)
    unnamed_systems: dict[str, int] = field(default_factory=dict)
    snapshot_timestamp: str = ""
    mcp_version: str = ""
    mcp_commit: str = ""
    unchanged: bool = False
    detail_source_page_id: int = 0
    detail_imported_by_kind: dict[str, int] = field(default_factory=dict)
    detail_errors_by_kind: dict[str, int] = field(default_factory=dict)
    details_unchanged: bool = False
    detail_bridge_missing_systems: list[str] = field(default_factory=list)

    @property
    def total_entities(self) -> int:
        return sum(self.inventory_by_kind.values())

    @property
    def written_entities(self) -> int:
        return sum(self.imported_by_kind.values())

    @property
    def total_details(self) -> int:
        return sum(self.detail_imported_by_kind.values())

    def summary_lines(self) -> list[str]:
        state = (
            "unchanged; entity rewrite skipped"
            if self.unchanged
            else f"{self.written_entities} DB rows refreshed"
        )
        lines = [f"MCP inventory entities: {self.total_entities} ({state})"]
        for kind, count in sorted(
            self.inventory_by_kind.items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"  {kind}: {count}")
        if self.unnamed_systems:
            lines.append(
                "Inventory-only systems (count captured, no per-record names in snapshot):"
            )
            for system, count in sorted(
                self.unnamed_systems.items(), key=lambda item: (-item[1], item[0])
            ):
                lines.append(f"  {system}: {count}")
        if self.detail_imported_by_kind:
            detail_state = (
                "unchanged; rich-detail pass skipped"
                if self.details_unchanged
                else "rich local details compiled"
            )
            lines.append(f"MCP detail layer: {detail_state} ({self.total_details} records)")
            for kind, count in sorted(
                self.detail_imported_by_kind.items(), key=lambda item: (-item[1], item[0])
            ):
                lines.append(f"  {kind}: {count}")
        elif self.details_unchanged:
            lines.append("MCP detail layer: unchanged; rich-detail pass skipped")
        if self.detail_bridge_missing_systems:
            lines.append(
                "Detail getters unavailable in this upstream build: "
                + ", ".join(self.detail_bridge_missing_systems)
            )
        if any(self.detail_errors_by_kind.values()):
            lines.append(
                "Detail records with getter errors: "
                + ", ".join(
                    f"{kind}={count}"
                    for kind, count in sorted(self.detail_errors_by_kind.items())
                    if count
                )
            )
        return lines


def _read_mcp_version(repo: Path) -> str:
    try:
        data = json.loads((repo / "package.json").read_text(encoding="utf-8"))
        return str(data.get("version") or "")
    except Exception:
        return ""


def _read_mcp_commit(repo: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=4,
        )
        return completed.stdout.strip()
    except Exception:
        return ""


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
            os.path.abspath(str(right))
        )
    except Exception:
        return str(left) == str(right)


def _detail_search_text(value: Any, *, max_chars: int = 12000) -> str:
    """Flatten useful structured fields for FTS without duplicating unbounded JSON."""
    parts: list[str] = []
    chars = 0

    def walk(item: Any, prefix: str = "") -> None:
        nonlocal chars
        if chars >= max_chars:
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).startswith("_"):
                    continue
                walk(child, f"{prefix}.{key}" if prefix else str(key))
            return
        if isinstance(item, (list, tuple)):
            for index, child in enumerate(item[:128]):
                walk(child, f"{prefix}[{index}]" if prefix else str(index))
            return
        if item in (None, ""):
            return
        text = " ".join(str(item).split())
        if not text:
            return
        line = f"{prefix}: {text}" if prefix else text
        if chars + len(line) + 1 > max_chars:
            line = line[: max(0, max_chars - chars - 1)]
        if line:
            parts.append(line)
            chars += len(line) + 1

    walk(value)
    return "\n".join(parts)


class MCPLocalSnapshotCompiler:
    """Compile everquest1-mcp's offline local inventory and rich records into EverQuestie."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def capture(eq_path: str | Path, mcp_path: str | Path) -> MCPSnapshotCapture:
        eq_root = Path(eq_path).expanduser().resolve()
        repo = Path(mcp_path).expanduser().resolve()
        if not eq_root.is_dir():
            raise ValueError(f"EverQuest directory does not exist: {eq_root}")

        status = mcp_status(repo)
        if not status.ready:
            raise MCPError(status.summary())

        snapshot_path = eq_root / MCP_SNAPSHOT_NAME
        previous_bytes: bytes | None = None
        previous_times: tuple[int, int] | None = None
        if snapshot_path.exists():
            previous_bytes = snapshot_path.read_bytes()
            try:
                stat = snapshot_path.stat()
                previous_times = (stat.st_atime_ns, stat.st_mtime_ns)
            except OSError:
                previous_times = None

        raw_json = ""
        snapshot: dict[str, Any]
        try:
            with MCPStdioClient(repo, eq_game_path=eq_root, timeout=180.0) as client:
                tools = client.list_tools()
                if not any(tool.get("name") == MCP_SNAPSHOT_TOOL for tool in tools):
                    raise MCPError(
                        f"The installed everquest1-mcp does not expose '{MCP_SNAPSHOT_TOOL}'. "
                        "Build/update the MCP checkout and try again."
                    )
                client.call_tool(MCP_SNAPSHOT_TOOL, {})

            if not snapshot_path.is_file():
                raise MCPError(
                    f"{MCP_SNAPSHOT_TOOL} completed but {snapshot_path} was not created."
                )
            raw_json = snapshot_path.read_text(encoding="utf-8", errors="strict")
            loaded = json.loads(raw_json)
            if not isinstance(loaded, dict):
                raise MCPError("everquest1-mcp produced an unrecognized snapshot format.")
            snapshot = loaded
        finally:
            try:
                if previous_bytes is None:
                    snapshot_path.unlink(missing_ok=True)
                else:
                    snapshot_path.write_bytes(previous_bytes)
                    if previous_times is not None:
                        os.utime(snapshot_path, ns=previous_times)
            except OSError:
                pass

        if not isinstance(snapshot.get("systems"), dict):
            raise MCPError("everquest1-mcp produced an unrecognized snapshot format.")
        snapshot_eq_path = str(snapshot.get("eqPath") or "")
        if snapshot_eq_path and not _same_path(snapshot_eq_path, eq_root):
            raise MCPError(
                "MCP snapshot came from a different EverQuest installation:\n"
                f"snapshot: {snapshot_eq_path}\nselected: {eq_root}"
            )

        return MCPSnapshotCapture(
            eq_path=eq_root,
            mcp_path=repo,
            snapshot=snapshot,
            raw_json=raw_json,
            mcp_version=_read_mcp_version(repo),
            mcp_commit=_read_mcp_commit(repo),
        )

    def import_capture(self, capture: MCPSnapshotCapture) -> MCPCompileResult:
        snapshot = capture.snapshot
        systems = snapshot.get("systems") or {}
        fingerprint_payload = {
            "version": snapshot.get("version"),
            "files": snapshot.get("files") or {},
            "systems": systems,
        }
        digest = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        result = MCPCompileResult(
            snapshot_timestamp=str(snapshot.get("timestamp") or ""),
            mcp_version=capture.mcp_version,
            mcp_commit=capture.mcp_commit,
        )

        for system_name, payload in systems.items():
            if not isinstance(payload, dict):
                continue
            try:
                count = int(payload.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            result.system_counts[system_name] = count
            names = payload.get("names") or {}
            kind = SYSTEM_KIND_MAP.get(system_name)
            if kind and isinstance(names, dict) and names:
                result.inventory_by_kind[kind] = result.inventory_by_kind.get(kind, 0) + sum(
                    1 for value in names.values() if str(value or "").strip()
                )
            elif count:
                result.unnamed_systems[system_name] = count

        source_url = "eqclient+mcp://save_data_snapshot"
        previous = self.db.conn.execute(
            "SELECT id, sha256 FROM source_pages WHERE url=?", (source_url,)
        ).fetchone()
        result.unchanged = bool(previous is not None and previous["sha256"] == digest)

        version_parts = [
            part for part in (capture.mcp_version, capture.mcp_commit[:12]) if part
        ]
        source_version = " @ ".join(version_parts)

        with self.db.batch():
            source_id = self.db.upsert_source_page(
                url=source_url,
                title="EverQuest local data inventory via everquest1-mcp",
                entity_type="multi",
                sha256=digest,
                plain_text=capture.raw_json,
                raw_html="",
                source_name="EverQuest Client via everquest1-mcp",
                source_kind="mcp_local_snapshot",
                source_key=MCP_SNAPSHOT_TOOL,
                source_version=source_version,
                local_path=str(capture.eq_path),
                fetched_at=result.snapshot_timestamp or None,
            )
            result.source_page_id = source_id

            if not result.unchanged:
                for system_name, payload in systems.items():
                    if not isinstance(payload, dict):
                        continue
                    names = payload.get("names") or {}
                    kind = SYSTEM_KIND_MAP.get(system_name)
                    if not kind or not isinstance(names, dict):
                        continue
                    imported = 0
                    for external_id, raw_name in names.items():
                        name = " ".join(str(raw_name or "").split()).strip()
                        if not name:
                            continue
                        entity_id = self.db.upsert_entity(
                            kind=kind,
                            name=name,
                            source_page_id=source_id,
                            source_url=source_url,
                            external_id=str(external_id),
                            external_namespace=f"eqclient:{kind}",
                            merge_by_name=(kind == "zone"),
                            notes=(
                                "Identity imported from the installed EverQuest client "
                                "through everquest1-mcp's offline local-data parser."
                            ),
                            data={
                                "mcp_system": system_name,
                                "snapshot_timestamp": result.snapshot_timestamp,
                                "authoritative_identity_source": "EverQuest Client",
                            },
                        )
                        self.db.add_external_id(
                            entity_id,
                            f"eqmcp:{system_name}",
                            str(external_id),
                            source_page_id=source_id,
                        )
                        imported += 1
                    result.imported_by_kind[kind] = (
                        result.imported_by_kind.get(kind, 0) + imported
                    )

            self.db.set_meta("eq_mcp_last_compile", result.snapshot_timestamp)
            self.db.set_meta("eq_mcp_version", capture.mcp_version)
            self.db.set_meta("eq_mcp_commit", capture.mcp_commit)
            self.db.set_meta(
                "eq_mcp_system_counts",
                json.dumps(result.system_counts, sort_keys=True),
            )
            self.db.set_meta("eq_game_path", str(capture.eq_path))

        return result

    def _detail_entity_id(self, system: str, external_id: str) -> int | None:
        row = self.db.conn.execute(
            """
            SELECT e.id
            FROM entity_external_ids x
            JOIN entities e ON e.id=x.entity_id
            WHERE x.namespace=? AND x.external_id=?
            """,
            (f"eqmcp:{system}", str(external_id)),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    def import_details(
        self,
        capture: MCPSnapshotCapture,
        result: MCPCompileResult,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        """Compile complete structured local records through everquest1-mcp's parsers."""
        bridge = Path(__file__).resolve().parents[2] / "tools" / "mcp_local_detail_bridge.mjs"
        if not bridge.is_file():
            result.detail_bridge_missing_systems = list(SYSTEM_KIND_MAP)
            raise MCPError(
                f"Rich-detail compiler is required but missing: {bridge}. "
                "Use --skip-mcp-details only for an intentional inventory-only build."
            )

        bridge_hash = hashlib.sha256(bridge.read_bytes()).hexdigest()
        detail_digest = hashlib.sha256(
            (
                hashlib.sha256(capture.raw_json.encode("utf-8")).hexdigest()
                + "|"
                + capture.mcp_commit
                + "|"
                + bridge_hash
            ).encode("utf-8")
        ).hexdigest()

        previous = self.db.conn.execute(
            "SELECT id, sha256 FROM source_pages WHERE url=?",
            (MCP_DETAIL_SOURCE_URL,),
        ).fetchone()
        if previous is not None and str(previous["sha256"]) == detail_digest:
            source_id = int(previous["id"])
            rows = self.db.conn.execute(
                """
                SELECT e.kind, COUNT(*) AS n
                FROM entity_details d
                JOIN entities e ON e.id=d.entity_id
                WHERE d.source_page_id=?
                GROUP BY e.kind
                """,
                (source_id,),
            ).fetchall()
            if rows:
                result.detail_source_page_id = source_id
                result.details_unchanged = True
                result.detail_imported_by_kind = {
                    str(row["kind"]): int(row["n"]) for row in rows
                }
                return

        version_parts = [
            part for part in (capture.mcp_version, capture.mcp_commit[:12]) if part
        ]
        source_version = " @ ".join(version_parts)
        manifest = {
            "snapshot_timestamp": result.snapshot_timestamp,
            "mcp_version": capture.mcp_version,
            "mcp_commit": capture.mcp_commit,
            "bridge_sha256": bridge_hash,
            "systems": sorted(SYSTEM_KIND_MAP),
        }

        status = mcp_status(capture.mcp_path)
        if not status.ready:
            raise MCPError(status.summary())
        env = os.environ.copy()
        env["EQ_GAME_PATH"] = str(capture.eq_path)
        proc = subprocess.Popen(
            [status.node or "node", str(bridge), str(capture.mcp_path), "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            bufsize=1,
        )
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps(capture.snapshot, ensure_ascii=False))
        proc.stdin.close()

        with self.db.batch():
            detail_source_id = self.db.upsert_source_page(
                url=MCP_DETAIL_SOURCE_URL,
                title="EverQuest structured local records via everquest1-mcp",
                entity_type="multi",
                sha256=detail_digest,
                plain_text=json.dumps(manifest, ensure_ascii=False, indent=2),
                raw_html="",
                source_name="EverQuest Client via everquest1-mcp",
                source_kind="mcp_local_details",
                source_key=MCP_DETAIL_SOURCE_KEY,
                source_version=source_version,
                local_path=str(capture.eq_path),
                fetched_at=result.snapshot_timestamp or None,
            )
            result.detail_source_page_id = detail_source_id

            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = str(message.get("type") or "")
                system = str(message.get("system") or "")
                kind = str(message.get("kind") or SYSTEM_KIND_MAP.get(system) or "unknown")

                if msg_type == "system_start":
                    if progress:
                        progress(
                            f"MCP rich details: {kind} "
                            f"({int(message.get('total') or 0):,} records)…"
                        )
                    continue
                if msg_type == "system_done":
                    if progress:
                        progress(
                            f"MCP rich details: {kind} complete "
                            f"({int(message.get('imported') or 0):,} imported, "
                            f"{int(message.get('errors') or 0):,} getter errors)"
                        )
                    continue
                if msg_type == "system_missing":
                    if system and system not in result.detail_bridge_missing_systems:
                        result.detail_bridge_missing_systems.append(system)
                    continue
                if msg_type == "record_error":
                    result.detail_errors_by_kind[kind] = (
                        result.detail_errors_by_kind.get(kind, 0) + 1
                    )
                    continue
                if msg_type != "record":
                    continue

                expected_kind = SYSTEM_KIND_MAP.get(system)
                external_id = str(message.get("external_id") or "")
                record = message.get("record")
                if not expected_kind or kind != expected_kind or not external_id:
                    result.detail_errors_by_kind[kind] = (
                        result.detail_errors_by_kind.get(kind, 0) + 1
                    )
                    continue

                entity_id = self._detail_entity_id(system, external_id)
                if entity_id is None:
                    result.detail_errors_by_kind[kind] = (
                        result.detail_errors_by_kind.get(kind, 0) + 1
                    )
                    continue

                self.db.upsert_entity_detail(
                    entity_id,
                    source_page_id=detail_source_id,
                    detail_format="mcp-json",
                    detail_text=_detail_search_text(record),
                    detail_json=record,
                )
                result.detail_imported_by_kind[kind] = (
                    result.detail_imported_by_kind.get(kind, 0) + 1
                )

            return_code = proc.wait()
            if return_code != 0:
                stderr = proc.stderr.read().strip() if proc.stderr is not None else ""
                raise MCPError(
                    "Rich-detail compiler failed"
                    + (f":\n{stderr}" if stderr else f" with exit code {return_code}.")
                )

            self.db.set_meta("eq_mcp_detail_last_compile", result.snapshot_timestamp)
            self.db.set_meta(
                "eq_mcp_detail_counts",
                json.dumps(result.detail_imported_by_kind, sort_keys=True),
            )
            self.db.set_meta(
                "eq_mcp_detail_errors",
                json.dumps(result.detail_errors_by_kind, sort_keys=True),
            )
            self.db.set_meta(
                "eq_mcp_detail_missing_systems",
                json.dumps(sorted(result.detail_bridge_missing_systems)),
            )

        if progress:
            progress(f"MCP rich details compiled: {result.total_details:,} records.")

    def compile_installation(
        self,
        eq_path: str | Path,
        mcp_path: str | Path,
        *,
        include_details: bool = True,
        progress: Callable[[str], None] | None = None,
    ) -> MCPCompileResult:
        capture = self.capture(eq_path, mcp_path)
        result = self.import_capture(capture)
        if include_details:
            if progress:
                progress("Compiling rich local records through everquest1-mcp…")
            self.import_details(capture, result, progress=progress)
        return result
