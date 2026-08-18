from __future__ import annotations

from .db import Database


def rebuild_compact_search_index(db: Database) -> int:
    """Compatibility entry point for the native compact Database FTS rebuild."""
    return db.rebuild_search_index()
