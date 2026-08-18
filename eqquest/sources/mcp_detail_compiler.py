from __future__ import annotations

from typing import Callable

from . import mcp_snapshot as core
from .mcp_detail_records import import_details as import_detail_records


class MCPDetailRecordCompiler(core.MCPLocalSnapshotCompiler):
    """MCP snapshot compiler with source-granular rich-detail retention."""

    def import_details(
        self,
        capture: core.MCPSnapshotCapture,
        result: core.MCPCompileResult,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        import_detail_records(self, capture, result, progress=progress)
