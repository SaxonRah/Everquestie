__version__ = "0.13.0"

from .search_index import install_compact_search_index

# Release finalization already uses the compact FTS builder directly. Keep source /
# developer Database.rebuild_search_index() calls on that exact same implementation so
# manual rebuilds and MCP compiles cannot produce a different search corpus.
install_compact_search_index()