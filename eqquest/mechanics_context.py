from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .db import Database, normalize_name


@dataclass(frozen=True, slots=True)
class MechanicsSource:
    source_page_id: int | None
    source_name: str
    source_kind: str
    source_key: str
    source_version: str
    local_path: str
    url: str

    @property
    def label(self) -> str:
        base = self.source_name or self.local_path or self.url or self.source_key or "EverQuestie knowledge"
        return f"{base} {self.source_version}".strip()


@dataclass(frozen=True, slots=True)
class ClassIdentity:
    entity_id: int
    class_id: int
    name: str
    matched_by: str


@dataclass(frozen=True, slots=True)
class BaseStatsContext:
    level: int
    hp: float | None
    mana: float | None
    endurance: float | None
    hp_regen: float | None
    mana_regen: float | None
    endurance_regen: float | None
    source: MechanicsSource


@dataclass(frozen=True, slots=True)
class ACMitigationContext:
    level: int
    ac_cap: float | None
    soft_cap_multiplier: float | None
    source: MechanicsSource


@dataclass(frozen=True, slots=True)
class SkillCapContext:
    skill_entity_id: int | None
    skill_id: int
    name: str
    cap: int
    row_level: int
    first_positive_level: int
    new_this_level: bool
    changed_this_level: bool
    source: MechanicsSource


@dataclass(frozen=True, slots=True)
class ClassMechanicsContext:
    identity: ClassIdentity
    requested_level: int
    base_stats: BaseStatsContext | None
    ac_mitigation: ACMitigationContext | None
    skills: tuple[SkillCapContext, ...]

    @property
    def new_skills(self) -> tuple[SkillCapContext, ...]:
        return tuple(skill for skill in self.skills if skill.new_this_level)

    @property
    def changed_skills(self) -> tuple[SkillCapContext, ...]:
        return tuple(skill for skill in self.skills if skill.changed_this_level)


def _source_from_row(row: Any) -> MechanicsSource:
    return MechanicsSource(
        source_page_id=(int(row["source_page_id"]) if row["source_page_id"] is not None else None),
        source_name=str(row["source_name"] or ""),
        source_kind=str(row["source_kind"] or ""),
        source_key=str(row["source_key"] or ""),
        source_version=str(row["source_version"] or ""),
        local_path=str(row["local_path"] or ""),
        url=str(row["url"] or ""),
    )


def resolve_class_identity(db: Database, token: str | int) -> tuple[ClassIdentity | None, str]:
    """Resolve an EQ class using exact canonical/client identity signals only.

    Class context must never promote a unique substring to identity. Accepted inputs are
    the namespaced EQ client class ID, canonical class name, or an exact stored alias
    such as WAR/SK/Shadowknight.
    """
    text = " ".join(str(token or "").split()).strip()
    if not text:
        return None, "empty"

    try:
        class_id = int(text)
    except ValueError:
        class_id = None
    if class_id is not None:
        row = db.entity_by_namespaced_external_id("eqclient:class", str(class_id))
        if row is not None and str(row["kind"]) == "class":
            return ClassIdentity(int(row["id"]), class_id, str(row["name"]), "client_id"), "linked"

    norm = normalize_name(text)
    rows = db.conn.execute(
        "SELECT * FROM entities WHERE kind='class' AND normalized_name=? ORDER BY id",
        (norm,),
    ).fetchall()
    if len(rows) == 1:
        row = rows[0]
        ext = db.entity_by_namespaced_external_id("eqclient:class", str(row["external_id"] or ""))
        if ext is not None and int(ext["id"]) == int(row["id"]):
            return ClassIdentity(int(row["id"]), int(row["external_id"]), str(row["name"]), "name"), "linked"
        ext_rows = db.external_ids_for_entity(int(row["id"]))
        for ext_row in ext_rows:
            if str(ext_row["namespace"] or "").casefold() == "eqclient:class":
                try:
                    cid = int(str(ext_row["external_id"]))
                except ValueError:
                    continue
                return ClassIdentity(int(row["id"]), cid, str(row["name"]), "name"), "linked"
    elif len(rows) > 1:
        return None, "ambiguous"

    alias_rows = db.conn.execute(
        """
        SELECT DISTINCT e.*
        FROM entity_aliases a
        JOIN entities e ON e.id=a.entity_id
        WHERE e.kind='class' AND a.normalized_alias=?
        ORDER BY e.id
        """,
        (norm,),
    ).fetchall()
    if len(alias_rows) == 1:
        row = alias_rows[0]
        for ext_row in db.external_ids_for_entity(int(row["id"])):
            if str(ext_row["namespace"] or "").casefold() != "eqclient:class":
                continue
            try:
                cid = int(str(ext_row["external_id"]))
            except ValueError:
                continue
            return ClassIdentity(int(row["id"]), cid, str(row["name"]), "alias"), "linked"
    if len(alias_rows) > 1:
        return None, "ambiguous"
    return None, "missing"


def _exact_level_row(db: Database, table: str, class_id: int, level: int):
    if table not in {"base_stats", "ac_mitigation"}:
        raise ValueError(f"unsupported mechanics table: {table}")
    return db.conn.execute(
        f"""
        SELECT t.*, sp.source_name,sp.source_kind,sp.source_key,sp.source_version,
               sp.local_path,sp.url
        FROM {table} t
        LEFT JOIN source_pages sp ON sp.id=t.source_page_id
        WHERE t.class_id=? AND t.level=?
        LIMIT 1
        """,
        (class_id, level),
    ).fetchone()


def _skill_contexts(db: Database, class_id: int, level: int) -> tuple[SkillCapContext, ...]:
    rows = db.conn.execute(
        """
        SELECT sc.*,sp.source_name,sp.source_kind,sp.source_key,sp.source_version,
               sp.local_path,sp.url
        FROM skill_caps sc
        LEFT JOIN source_pages sp ON sp.id=sc.source_page_id
        WHERE sc.class_id=? AND sc.level<=?
        ORDER BY sc.skill_id,sc.level
        """,
        (class_id, level),
    ).fetchall()

    by_skill: dict[int, list[Any]] = {}
    for row in rows:
        by_skill.setdefault(int(row["skill_id"]), []).append(row)

    out: list[SkillCapContext] = []
    for skill_id, history in by_skill.items():
        positive = [row for row in history if int(row["cap"] or 0) > 0]
        if not positive:
            continue
        current = history[-1]
        current_cap = int(current["cap"] or 0)
        if current_cap <= 0:
            # An explicit zero at or below the requested level withdraws availability;
            # never resurrect an older positive cap merely because it was favorable.
            continue
        current_level = int(current["level"])
        first_level = int(positive[0]["level"])
        new_this_level = first_level == level
        previous = history[-2] if len(history) >= 2 else None
        changed_this_level = bool(
            current_level == level
            and not new_this_level
            and previous is not None
            and int(previous["cap"] or 0) != current_cap
        )
        skill = db.entity_by_namespaced_external_id("eqclient:skill", str(skill_id))
        out.append(
            SkillCapContext(
                skill_entity_id=(int(skill["id"]) if skill is not None else None),
                skill_id=skill_id,
                name=(str(skill["name"]) if skill is not None else f"Skill ID {skill_id}"),
                cap=current_cap,
                row_level=current_level,
                first_positive_level=first_level,
                new_this_level=new_this_level,
                changed_this_level=changed_this_level,
                source=_source_from_row(current),
            )
        )
    return tuple(sorted(out, key=lambda item: (item.name.casefold(), item.skill_id)))


def build_class_mechanics_context(
    db: Database,
    class_token: str | int,
    level: int,
) -> tuple[ClassMechanicsContext | None, str]:
    identity, status = resolve_class_identity(db, class_token)
    if identity is None:
        return None, status
    requested_level = max(1, int(level))

    base_row = _exact_level_row(db, "base_stats", identity.class_id, requested_level)
    base = None
    if base_row is not None:
        base = BaseStatsContext(
            level=int(base_row["level"]),
            hp=base_row["hp"],
            mana=base_row["mana"],
            endurance=base_row["endurance"],
            hp_regen=base_row["hp_regen"],
            mana_regen=base_row["mana_regen"],
            endurance_regen=base_row["endurance_regen"],
            source=_source_from_row(base_row),
        )

    ac_row = _exact_level_row(db, "ac_mitigation", identity.class_id, requested_level)
    ac = None
    if ac_row is not None:
        ac = ACMitigationContext(
            level=int(ac_row["level"]),
            ac_cap=ac_row["ac_cap"],
            soft_cap_multiplier=ac_row["soft_cap_multiplier"],
            source=_source_from_row(ac_row),
        )

    return (
        ClassMechanicsContext(
            identity=identity,
            requested_level=requested_level,
            base_stats=base,
            ac_mitigation=ac,
            skills=_skill_contexts(db, identity.class_id, requested_level),
        ),
        "linked",
    )


def class_mechanics_text(db: Database, class_token: str | int, level: int) -> str:
    context, status = build_class_mechanics_context(db, class_token, level)
    if context is None:
        if status == "ambiguous":
            return f"Class identity {class_token!r} is ambiguous; EverQuestie will not guess."
        return f"No canonical EQ-client class identity is present for {class_token!r}."

    lines = [
        f"{context.identity.name} | level {context.requested_level}",
        "Exact client-table facts only; missing base/AC levels are not interpolated.",
    ]
    if context.base_stats is None:
        lines += ["", "Base resources: no exact-level row in shipped knowledge."]
    else:
        base = context.base_stats
        lines += [
            "",
            "Base resources:",
            f"  HP {base.hp} | Mana {base.mana} | Endurance {base.endurance}",
            f"  Regen: HP {base.hp_regen} | Mana {base.mana_regen} | Endurance {base.endurance_regen}",
            f"  Source: {base.source.label}",
        ]
    if context.ac_mitigation is None:
        lines += ["", "AC mitigation: no exact-level row in shipped knowledge."]
    else:
        ac = context.ac_mitigation
        lines += [
            "",
            "AC mitigation:",
            f"  AC cap {ac.ac_cap} | soft-cap multiplier {ac.soft_cap_multiplier}",
            f"  Source: {ac.source.label}",
        ]

    lines += ["", f"Skills available by level {context.requested_level}: {len(context.skills)}"]
    for skill in context.skills:
        flags: list[str] = []
        if skill.new_this_level:
            flags.append("new this level")
        if skill.changed_this_level:
            flags.append("cap changed this level")
        suffix = f" | {', '.join(flags)}" if flags else ""
        row_note = "" if skill.row_level == context.requested_level else f" | last changed at {skill.row_level}"
        lines.append(
            f"  • {skill.name}: {skill.cap}{row_note}{suffix} | source: {skill.source.label}"
        )
    return "\n".join(lines)
