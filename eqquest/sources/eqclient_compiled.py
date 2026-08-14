from __future__ import annotations

from pathlib import Path

from ..mechanics_catalog import MechanicsCatalog, MechanicsCoverage
from .eqclient import EQClientImportResult, EQClientImporter as RawEQClientImporter


class EQClientImporter(RawEQClientImporter):
    """EQ-client importer that immediately refreshes derived canonical mechanics.

    The raw installed-client tables are authoritative numeric support data.  EverQuestie
    also owns a deterministic class/skill vocabulary that turns those numeric IDs into
    canonical entities and ``can_train_skill`` relationships.  Release finalization has
    always compiled that layer; builder/source-checkout imports must do the same so the
    live writable DB and the eventual immutable snapshot expose identical mechanics.
    """

    last_mechanics_coverage: MechanicsCoverage | None = None

    def import_installation(self, eq_path: str | Path) -> EQClientImportResult:
        result = super().import_installation(eq_path)
        with self.db.batch():
            self.last_mechanics_coverage = MechanicsCatalog(self.db).reconcile()
        return result
