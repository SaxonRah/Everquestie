__version__ = "0.13.0"

# Map-label reconciliation is builder-owned but the same MapCatalog class is also
# imported by runtime read paths. Install the set-based implementation at package
# import so every caller gets identical conservative semantics without the historic
# per-label SQLite query loop.
from .map_reconcile_acceleration import install_map_reconcile_acceleration
from .search_index import install_compact_search_index

install_map_reconcile_acceleration()

# Release finalization already uses the compact FTS builder directly. Keep source /
# developer Database.rebuild_search_index() calls on that exact same implementation so
# manual rebuilds and MCP compiles cannot produce a different search corpus.
install_compact_search_index()
