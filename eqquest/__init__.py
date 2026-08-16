__version__ = "0.13.0"

# Map-label reconciliation is builder-owned but the same MapCatalog class is also
# imported by runtime read paths. Install the set-based implementation at package
# import so every caller gets identical conservative semantics without the historic
# per-label SQLite query loop.
from .map_reconcile_acceleration import install_map_reconcile_acceleration

install_map_reconcile_acceleration()
