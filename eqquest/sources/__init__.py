"""EverQuestie knowledge-source adapters.

Runtime gameplay never requires network access. Source adapters either read local
files/mirrors or are invoked explicitly by builder/developer workflows.
"""

from .eqclient import EQClientImportResult
from .eqclient_compiled import EQClientImporter
from .mcp_snapshot import MCPCompileResult, MCPLocalSnapshotCompiler
from .mcp_detail_records import install_mcp_detail_record_storage

install_mcp_detail_record_storage()

__all__ = ["EQClientImportResult", "EQClientImporter", "MCPCompileResult", "MCPLocalSnapshotCompiler"]
