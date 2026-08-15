from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from typing import Any

from .db import Database, normalize_name


DERIVED_FROM = "npc_expansion_reconciliation"
RELATION = "introduced_in_expansion"


@dataclass(frozen=True, slots=True)
class NPCExpansionReconciliationStats:
    npcs_scanned: int
    expansion_names: int
    linked: int
    ambiguous: int
    unresolved: int
    stale_removed: int

    def as_dict(self) -> dict[str, int]:
        return {
            "npcs_scanned": self.npcs_scanned,
            "expansion_names": self.expansion_names,
            "linked": self.linked,
            "ambiguous": self.ambiguous,
            "unresolved": self.unresolved,
            "stale_removed": self.stale_removed,
        }


class NPCExpansionReconciliationCatalog:
    """Compile structured Allakhazam NPC expansion text into client expansion edges.

    Allakhazam's NPC parser records the explicit page-level ``Expansion`` field in
    ``data_json['expansion']``. The installed EverQuest client's ``dbstr_us.txt``
    independently supplies authoritative ``eqclient:expansion`` identities.

    A graph edge is created only for one exact normalized client-backed expansion name.
    Provider-only duplicate names are ignored as identity candidates; multiple client
    identities remain ambiguous; missing names remain raw NPC metadata.
    """

    def __init__(self, db: Database):
        self.db = db

    def _require_builder(self) -> None:
        if not getattr(self.db, "knowledge_writable", True):
            raise RuntimeError("NPC expansion reconciliation is builder-only")

    @staticmethod
    def _json_dict(raw: Any) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _clean_name(value: Any) -> str:
        if isinstance(value, (dict, list, tuple, set)):
            return ""
        return " ".join(str(value or "").split()).strip()

    def _remove_owned_edges(self) -> int:
        rows = self.db.conn.execute(
            "SELECT id,data_json FROM entity_relationships WHERE relation=? ORDER BY id",
            (RELATION,),
        ).fetchall()
        owned: list[int] = []
        for row in rows:
            data = self._json_dict(row["data_json"])
            if str(data.get("derived_from") or "") == DERIVED_FROM:
                owned.append(int(row["id"]))
        for relationship_id in owned:
            self.db.conn.execute(
                "DELETE FROM entity_relationships WHERE id=?",
                (relationship_id,),
            )
        return len(owned)

    def _client_expansion_targets(self) -> dict[str, tuple[int, ...]]:
        rows = self.db.conn.execute(
            """
            SELECT DISTINCT e.id,e.normalized_name
            FROM entities e
            JOIN entity_external_ids x ON x.entity_id=e.id
            WHERE e.kind='expansion' AND x.namespace='eqclient:expansion'
            ORDER BY e.normalized_name,e.id
            """
        ).fetchall()
        grouped: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            key = str(row["normalized_name"] or "")
            if key:
                grouped[key].append(int(row["id"]))
        return {key: tuple(dict.fromkeys(values)) for key, values in grouped.items()}

    def reconcile(self) -> NPCExpansionReconciliationStats:
        self._require_builder()
        targets = self._client_expansion_targets()
        npcs = self.db.conn.execute(
            """
            SELECT n.id,n.name,n.data_json,n.source_page_id,
                   sp.source_name,sp.source_kind,sp.source_key,sp.source_version
            FROM entities n
            JOIN source_pages sp ON sp.id=n.source_page_id
            WHERE n.kind='npc' AND lower(sp.source_name)='allakhazam'
            ORDER BY n.id
            """
        ).fetchall()

        counts = {"expansion_names": 0, "linked": 0, "ambiguous": 0, "unresolved": 0}
        with self.db.batch():
            stale_removed = self._remove_owned_edges()
            for npc in npcs:
                data = self._json_dict(npc["data_json"])
                raw_name = self._clean_name(data.get("expansion"))
                if not raw_name:
                    continue
                counts["expansion_names"] += 1
                candidates = targets.get(normalize_name(raw_name), ())
                if len(candidates) == 0:
                    counts["unresolved"] += 1
                    continue
                if len(candidates) != 1:
                    counts["ambiguous"] += 1
                    continue

                self.db.upsert_relationship(
                    int(npc["id"]),
                    int(candidates[0]),
                    RELATION,
                    source_page_id=int(npc["source_page_id"]),
                    evidence=f"Expansion: {raw_name}",
                    data={
                        "confidence": "structured",
                        "derived_from": DERIVED_FROM,
                        "source_field": "Expansion",
                        "raw_name": raw_name,
                        "identity_policy": "exact_unique_eqclient_expansion_name",
                    },
                )
                counts["linked"] += 1

        return NPCExpansionReconciliationStats(
            npcs_scanned=len(npcs),
            expansion_names=counts["expansion_names"],
            linked=counts["linked"],
            ambiguous=counts["ambiguous"],
            unresolved=counts["unresolved"],
            stale_removed=stale_removed,
        )
