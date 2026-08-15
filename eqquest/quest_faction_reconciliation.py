from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from typing import Any

from .db import Database, normalize_name


DERIVED_FROM = "quest_faction_reconciliation"
RELATION_FIELDS = (
    ("factions_raised", "raises_faction", "Factions Raised"),
    ("factions_lowered", "lowers_faction", "Factions Lowered"),
)


@dataclass(frozen=True, slots=True)
class QuestFactionReconciliationStats:
    quests_scanned: int
    faction_names: int
    linked: int
    ambiguous: int
    unresolved: int
    stale_removed: int

    def as_dict(self) -> dict[str, int]:
        return {
            "quests_scanned": self.quests_scanned,
            "faction_names": self.faction_names,
            "linked": self.linked,
            "ambiguous": self.ambiguous,
            "unresolved": self.unresolved,
            "stale_removed": self.stale_removed,
        }


class QuestFactionReconciliationCatalog:
    """Compile structured quest faction names into canonical client faction edges.

    Allakhazam quest extraction already stores the explicit `Factions Raised` and
    `Factions Lowered` table values in quest ``data_json``. Those names become graph
    relationships only when exactly one installed-client-backed faction has the same
    normalized canonical name.

    This is builder-only reconciliation. It never fuzzy-matches, creates a faction from
    provider text, rewrites the raw quest metadata, or runs in packaged runtime.
    """

    def __init__(self, db: Database):
        self.db = db

    def _require_builder(self) -> None:
        if not getattr(self.db, "knowledge_writable", True):
            raise RuntimeError("quest faction reconciliation is builder-only")

    @staticmethod
    def _json_dict(raw: Any) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _structured_names(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            values = (value,)
        elif isinstance(value, (list, tuple, set)):
            values = tuple(value)
        else:
            return ()
        cleaned = []
        for raw in values:
            name = " ".join(str(raw or "").split()).strip()
            if name:
                cleaned.append(name)
        return tuple(dict.fromkeys(cleaned))

    def _remove_owned_edges(self) -> int:
        rows = self.db.conn.execute(
            """
            SELECT id,data_json
            FROM entity_relationships
            WHERE relation IN ('raises_faction','lowers_faction')
            ORDER BY id
            """
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

    def _client_faction_targets(self) -> dict[str, tuple[int, ...]]:
        rows = self.db.conn.execute(
            """
            SELECT DISTINCT e.id,e.normalized_name
            FROM entities e
            JOIN entity_external_ids x ON x.entity_id=e.id
            WHERE e.kind='faction' AND x.namespace='eqclient:faction'
            ORDER BY e.normalized_name,e.id
            """
        ).fetchall()
        grouped: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            grouped[str(row["normalized_name"] or "")].append(int(row["id"]))
        return {key: tuple(dict.fromkeys(values)) for key, values in grouped.items() if key}

    def reconcile(self) -> QuestFactionReconciliationStats:
        self._require_builder()
        targets = self._client_faction_targets()
        quests = self.db.conn.execute(
            """
            SELECT q.id,q.name,q.data_json,q.source_page_id,
                   sp.source_name,sp.source_kind,sp.source_key,sp.source_version
            FROM entities q
            JOIN source_pages sp ON sp.id=q.source_page_id
            WHERE q.kind='quest' AND lower(sp.source_name)='allakhazam'
            ORDER BY q.id
            """
        ).fetchall()

        counts = {
            "faction_names": 0,
            "linked": 0,
            "ambiguous": 0,
            "unresolved": 0,
        }
        with self.db.batch():
            stale_removed = self._remove_owned_edges()
            for quest in quests:
                data = self._json_dict(quest["data_json"])
                for data_key, relation, source_field in RELATION_FIELDS:
                    for raw_name in self._structured_names(data.get(data_key)):
                        counts["faction_names"] += 1
                        candidates = targets.get(normalize_name(raw_name), ())
                        if len(candidates) == 0:
                            counts["unresolved"] += 1
                            continue
                        if len(candidates) != 1:
                            counts["ambiguous"] += 1
                            continue
                        faction_id = int(candidates[0])
                        self.db.upsert_relationship(
                            int(quest["id"]),
                            faction_id,
                            relation,
                            source_page_id=int(quest["source_page_id"]),
                            evidence=f"{source_field}: {raw_name}",
                            data={
                                "confidence": "structured",
                                "derived_from": DERIVED_FROM,
                                "source_field": source_field,
                                "raw_name": raw_name,
                                "identity_policy": "exact_unique_eqclient_faction_name",
                            },
                        )
                        counts["linked"] += 1

        return QuestFactionReconciliationStats(
            quests_scanned=len(quests),
            faction_names=counts["faction_names"],
            linked=counts["linked"],
            ambiguous=counts["ambiguous"],
            unresolved=counts["unresolved"],
            stale_removed=stale_removed,
        )
