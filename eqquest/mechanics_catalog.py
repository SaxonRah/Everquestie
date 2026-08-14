from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .db import Database


MECHANICS_CATALOG_VERSION = "1"
MECHANICS_SOURCE_URL = f"everquestie://reference/eq-mechanics-vocabulary/{MECHANICS_CATALOG_VERSION}"

# Canonical client-table identities. The numeric IDs are the IDs used by the
# installed-client mechanics tables (skillcaps.txt / basedata.txt / ACMitigation.txt).
# Names and common abbreviations are compiled into the shipped EverQuestie knowledge
# snapshot so runtime mechanics never needs MCP or a community site to label them.
EQ_CLASS_VOCABULARY: dict[int, tuple[str, str, tuple[str, ...]]] = {
    1: ("Warrior", "WAR", ()),
    2: ("Cleric", "CLR", ()),
    3: ("Paladin", "PAL", ()),
    4: ("Ranger", "RNG", ()),
    5: ("Shadow Knight", "SHD", ("Shadowknight", "SK")),
    6: ("Druid", "DRU", ()),
    7: ("Monk", "MNK", ()),
    8: ("Bard", "BRD", ()),
    9: ("Rogue", "ROG", ()),
    10: ("Shaman", "SHM", ()),
    11: ("Necromancer", "NEC", ()),
    12: ("Wizard", "WIZ", ()),
    13: ("Magician", "MAG", ("Mage",)),
    14: ("Enchanter", "ENC", ()),
    15: ("Beastlord", "BST", ()),
    16: ("Berserker", "BER", ()),
}

EQ_SKILL_VOCABULARY: dict[int, str] = {
    0: "1H Blunt",
    1: "1H Slashing",
    2: "2H Blunt",
    3: "2H Slashing",
    4: "Abjuration",
    5: "Alteration",
    6: "Apply Poison",
    7: "Archery",
    8: "Backstab",
    9: "Bind Wound",
    10: "Bash",
    11: "Block",
    12: "Brass Instruments",
    13: "Channeling",
    14: "Conjuration",
    15: "Defense",
    16: "Disarm",
    17: "Disarm Traps",
    18: "Divination",
    19: "Dodge",
    20: "Double Attack",
    21: "Dragon Punch",
    22: "Dual Wield",
    23: "Eagle Strike",
    24: "Evocation",
    25: "Feign Death",
    26: "Flying Kick",
    27: "Forage",
    28: "Hand to Hand",
    29: "Hide",
    30: "Kick",
    31: "Meditate",
    32: "Mend",
    33: "Offense",
    34: "Parry",
    35: "Pick Lock",
    36: "1H Piercing",
    37: "Riposte",
    38: "Round Kick",
    39: "Safe Fall",
    40: "Sense Heading",
    41: "Singing",
    42: "Sneak",
    43: "Specialize Abjuration",
    44: "Specialize Alteration",
    45: "Specialize Conjuration",
    46: "Specialize Divination",
    47: "Specialize Evocation",
    48: "Pick Pockets",
    49: "Stringed Instruments",
    50: "Swimming",
    51: "Throwing",
    52: "Tiger Claw",
    53: "Tracking",
    54: "Wind Instruments",
    55: "Fishing",
    56: "Make Poison",
    57: "Tinkering",
    58: "Research",
    59: "Alchemy",
    60: "Baking",
    61: "Tailoring",
    62: "Sense Traps",
    63: "Blacksmithing",
    64: "Fletching",
    65: "Brewing",
    66: "Alcohol Tolerance",
    67: "Begging",
    68: "Jewelry Making",
    69: "Pottery",
    70: "Percussion Instruments",
    71: "Intimidation",
    72: "Berserking",
    73: "Taunt",
    74: "Frenzy",
    75: "Remove Traps",
    76: "Triple Attack",
    77: "2H Piercing",
}


@dataclass(frozen=True, slots=True)
class MechanicsCoverage:
    class_ids_seen: tuple[int, ...]
    class_ids_named: int
    class_ids_unresolved: tuple[int, ...]
    skill_ids_seen: tuple[int, ...]
    skill_ids_named: int
    skill_ids_unresolved: tuple[int, ...]
    class_entities: int
    skill_entities: int
    class_skill_relationships: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "catalog_version": MECHANICS_CATALOG_VERSION,
            "class_ids_seen": list(self.class_ids_seen),
            "class_ids_named": self.class_ids_named,
            "class_ids_unresolved": list(self.class_ids_unresolved),
            "skill_ids_seen": list(self.skill_ids_seen),
            "skill_ids_named": self.skill_ids_named,
            "skill_ids_unresolved": list(self.skill_ids_unresolved),
            "class_entities": self.class_entities,
            "skill_entities": self.skill_entities,
            "class_skill_relationships": self.class_skill_relationships,
        }


class MechanicsCatalog:
    """Canonical identities and relationships for deterministic client mechanics.

    Raw support tables intentionally retain the numeric IDs and values exactly as the
    installed client supplies them. This catalog adds a source-independent semantic
    layer: class/skill entities, aliases, client-table evidence, and class -> skill
    relationships. Future providers can enrich those same entities through normal
    EverQuestie provenance/external-ID APIs without changing runtime mechanics queries.
    """

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _vocabulary_payload() -> str:
        payload = {
            "version": MECHANICS_CATALOG_VERSION,
            "classes": {
                str(class_id): {
                    "name": name,
                    "short": short,
                    "aliases": list(aliases),
                }
                for class_id, (name, short, aliases) in EQ_CLASS_VOCABULARY.items()
            },
            "skills": {str(skill_id): name for skill_id, name in EQ_SKILL_VOCABULARY.items()},
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _vocabulary_source(self) -> int:
        payload = self._vocabulary_payload()
        return self.db.upsert_source_page(
            url=MECHANICS_SOURCE_URL,
            title="EverQuestie canonical EverQuest mechanics vocabulary",
            entity_type="mechanics_vocabulary",
            sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            plain_text=payload,
            raw_html="",
            source_name="EverQuestie built-in EQ reference",
            source_kind="builtin_reference",
            source_key=f"mechanics-vocabulary:{MECHANICS_CATALOG_VERSION}",
            source_version=MECHANICS_CATALOG_VERSION,
        )

    def _upsert_identity(
        self,
        *,
        kind: str,
        external_id: int,
        name: str,
        data: dict[str, Any],
        vocabulary_source_id: int,
    ) -> int:
        namespace = f"eqclient:{kind}"
        existing = self.db.entity_by_namespaced_external_id(namespace, str(external_id))
        if existing is None:
            exact = self.db.conn.execute(
                "SELECT * FROM entities WHERE kind=? AND normalized_name=? ORDER BY id LIMIT 2",
                (kind, " ".join(name.casefold().split())),
            ).fetchall()
            existing = exact[0] if len(exact) == 1 else None

        entity_id = self.db.upsert_entity(
            kind=kind,
            name=name,
            source_page_id=None if existing is not None else vocabulary_source_id,
            source_url=None if existing is not None else MECHANICS_SOURCE_URL,
            external_id=str(external_id),
            external_namespace=namespace,
            merge_by_name=True,
            notes=(
                "Canonical client-table mechanics identity compiled into EverQuestie."
                if existing is None
                else ""
            ),
            data=data,
        )
        self.db.link_entity_source(
            entity_id,
            vocabulary_source_id,
            role="vocabulary",
            confidence=1.0,
        )
        return entity_id

    def _upsert_classes(self, vocabulary_source_id: int) -> dict[int, int]:
        result: dict[int, int] = {}
        for class_id, (name, short, aliases) in EQ_CLASS_VOCABULARY.items():
            entity_id = self._upsert_identity(
                kind="class",
                external_id=class_id,
                name=name,
                data={
                    "eq_class_id": class_id,
                    "short_name": short,
                    "mechanics_catalog_version": MECHANICS_CATALOG_VERSION,
                },
                vocabulary_source_id=vocabulary_source_id,
            )
            self.db.add_alias(
                entity_id,
                short,
                alias_type="class_abbreviation",
                source_page_id=vocabulary_source_id,
            )
            for alias in aliases:
                self.db.add_alias(
                    entity_id,
                    alias,
                    alias_type="class_alias",
                    source_page_id=vocabulary_source_id,
                )
            result[class_id] = entity_id
        return result

    def _upsert_skills(self, vocabulary_source_id: int) -> dict[int, int]:
        result: dict[int, int] = {}
        for skill_id, name in EQ_SKILL_VOCABULARY.items():
            result[skill_id] = self._upsert_identity(
                kind="skill",
                external_id=skill_id,
                name=name,
                data={
                    "eq_skill_id": skill_id,
                    "mechanics_catalog_version": MECHANICS_CATALOG_VERSION,
                },
                vocabulary_source_id=vocabulary_source_id,
            )
        return result

    def _link_client_evidence(
        self,
        class_entities: dict[int, int],
        skill_entities: dict[int, int],
    ) -> None:
        for table in ("skill_caps", "base_stats", "ac_mitigation"):
            rows = self.db.conn.execute(
                f"SELECT DISTINCT class_id,source_page_id FROM {table} "
                "WHERE source_page_id IS NOT NULL"
            ).fetchall()
            for row in rows:
                entity_id = class_entities.get(int(row["class_id"]))
                if entity_id is not None:
                    self.db.link_entity_source(
                        entity_id,
                        int(row["source_page_id"]),
                        role="client_mechanics_evidence",
                        confidence=1.0,
                    )

        rows = self.db.conn.execute(
            "SELECT DISTINCT skill_id,source_page_id FROM skill_caps "
            "WHERE source_page_id IS NOT NULL"
        ).fetchall()
        for row in rows:
            entity_id = skill_entities.get(int(row["skill_id"]))
            if entity_id is not None:
                self.db.link_entity_source(
                    entity_id,
                    int(row["source_page_id"]),
                    role="client_mechanics_evidence",
                    confidence=1.0,
                )

    def _rebuild_class_skill_relationships(
        self,
        class_entities: dict[int, int],
        skill_entities: dict[int, int],
    ) -> None:
        self.db.conn.execute(
            """
            DELETE FROM entity_relationships
            WHERE relation='can_train_skill'
              AND source_page_id IN (
                SELECT id FROM source_pages
                WHERE source_kind='local_game_files'
                  AND lower(source_key) LIKE '%skillcaps.txt'
              )
            """
        )
        rows = self.db.conn.execute(
            """
            SELECT class_id,skill_id,source_page_id,
                   MIN(CASE WHEN cap>0 THEN level END) AS first_level,
                   MAX(cap) AS max_cap,
                   COUNT(*) AS levels_observed
            FROM skill_caps
            WHERE source_page_id IS NOT NULL
            GROUP BY class_id,skill_id,source_page_id
            HAVING MAX(cap)>0
            ORDER BY class_id,skill_id,source_page_id
            """
        ).fetchall()
        for row in rows:
            class_entity = class_entities.get(int(row["class_id"]))
            skill_entity = skill_entities.get(int(row["skill_id"]))
            if class_entity is None or skill_entity is None:
                continue
            self.db.upsert_relationship(
                class_entity,
                skill_entity,
                "can_train_skill",
                quantity=int(row["max_cap"]),
                source_page_id=int(row["source_page_id"]),
                evidence="EverQuest client skillcaps.txt progression",
                data={
                    "first_level": (
                        int(row["first_level"]) if row["first_level"] is not None else None
                    ),
                    "max_cap": int(row["max_cap"]),
                    "levels_observed": int(row["levels_observed"]),
                    "mechanics_catalog_version": MECHANICS_CATALOG_VERSION,
                },
            )

    def coverage(self) -> MechanicsCoverage:
        class_ids = tuple(
            int(row[0])
            for row in self.db.conn.execute(
                """
                SELECT DISTINCT class_id FROM (
                    SELECT class_id FROM skill_caps
                    UNION ALL SELECT class_id FROM base_stats
                    UNION ALL SELECT class_id FROM ac_mitigation
                ) ORDER BY class_id
                """
            ).fetchall()
        )
        skill_ids = tuple(
            int(row[0])
            for row in self.db.conn.execute(
                "SELECT DISTINCT skill_id FROM skill_caps ORDER BY skill_id"
            ).fetchall()
        )
        unresolved_classes = tuple(
            class_id
            for class_id in class_ids
            if self.db.entity_by_namespaced_external_id("eqclient:class", str(class_id)) is None
        )
        unresolved_skills = tuple(
            skill_id
            for skill_id in skill_ids
            if self.db.entity_by_namespaced_external_id("eqclient:skill", str(skill_id)) is None
        )
        class_entities = int(
            self.db.conn.execute("SELECT COUNT(*) FROM entities WHERE kind='class'").fetchone()[0]
        )
        skill_entities = int(
            self.db.conn.execute("SELECT COUNT(*) FROM entities WHERE kind='skill'").fetchone()[0]
        )
        relationships = int(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM entity_relationships WHERE relation='can_train_skill'"
            ).fetchone()[0]
        )
        return MechanicsCoverage(
            class_ids_seen=class_ids,
            class_ids_named=len(class_ids) - len(unresolved_classes),
            class_ids_unresolved=unresolved_classes,
            skill_ids_seen=skill_ids,
            skill_ids_named=len(skill_ids) - len(unresolved_skills),
            skill_ids_unresolved=unresolved_skills,
            class_entities=class_entities,
            skill_entities=skill_entities,
            class_skill_relationships=relationships,
        )

    def reconcile(self) -> MechanicsCoverage:
        if not getattr(self.db, "knowledge_writable", True):
            raise RuntimeError("mechanics catalog reconciliation is builder-only")
        vocabulary_source_id = self._vocabulary_source()
        class_entities = self._upsert_classes(vocabulary_source_id)
        skill_entities = self._upsert_skills(vocabulary_source_id)
        self._link_client_evidence(class_entities, skill_entities)
        self._rebuild_class_skill_relationships(class_entities, skill_entities)
        coverage = self.coverage()
        self.db.set_meta("mechanics_catalog_version", MECHANICS_CATALOG_VERSION)
        self.db.set_meta(
            "mechanics_catalog_coverage",
            json.dumps(coverage.as_dict(), ensure_ascii=False, sort_keys=True),
        )
        return coverage


def mechanics_audit_text(db: Database) -> str:
    coverage = MechanicsCatalog(db).coverage()
    lines = [
        f"Mechanics catalog v{MECHANICS_CATALOG_VERSION}",
        "",
        f"Class IDs observed: {len(coverage.class_ids_seen)}",
        f"Class IDs resolved: {coverage.class_ids_named}",
        f"Skill IDs observed: {len(coverage.skill_ids_seen)}",
        f"Skill IDs resolved: {coverage.skill_ids_named}",
        f"Canonical class entities: {coverage.class_entities}",
        f"Canonical skill entities: {coverage.skill_entities}",
        f"Class -> skill relationships: {coverage.class_skill_relationships}",
    ]
    if coverage.class_ids_unresolved:
        lines.append(
            "Unresolved class IDs: " + ", ".join(map(str, coverage.class_ids_unresolved))
        )
    if coverage.skill_ids_unresolved:
        lines.append(
            "Unresolved skill IDs: " + ", ".join(map(str, coverage.skill_ids_unresolved))
        )
    if not coverage.class_ids_unresolved and not coverage.skill_ids_unresolved:
        lines.append("All observed class/skill support-table IDs have canonical identities.")
    return "\n".join(lines)
