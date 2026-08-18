"""EverQuestie knowledge-source adapters.

Runtime gameplay never requires network access. Source adapters either read local
files/mirrors or are invoked explicitly by builder/developer workflows.
"""

from .eqclient import EQClientImportResult
from .eqclient_compiled import EQClientImporter
from .mcp_detail_compiler import MCPDetailRecordCompiler
from .mcp_snapshot import MCPCompileResult

# Preserve the historical public compiler name while making rich-detail ownership
# explicit. Importing this package must not monkey-patch the core snapshot compiler.
MCPLocalSnapshotCompiler = MCPDetailRecordCompiler

__all__ = [
    "EQClientImportResult",
    "EQClientImporter",
    "MCPCompileResult",
    "MCPDetailRecordCompiler",
    "MCPLocalSnapshotCompiler",
]
