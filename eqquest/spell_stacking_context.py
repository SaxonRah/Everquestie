from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .mechanics import spell_entity_for_client_id, spell_id_for_entity
from .mechanics_context import MechanicsSource


@dataclass(frozen=True, slots=True)
class SpellStackingPeer:
    entity_id: int | None
    spell_id: int
    name: str
    stacking_group: int | None
    rank: int | None
    stacking_type: int | None
    source: MechanicsSource


@dataclass(frozen=True, slots=True)
class SpellStackingContext:
    entity_id: int
    name: str
    spell_id: int
    stacking_group: int | None
    rank: int | None
    stacking_type: int | None
    source: MechanicsSource | None
    peers: tuple[SpellStackingPeer, ...]

    @property
    def has_stacking_row(self) -> bool:
        return self.source is not None


def _source_from_row(row) -> MechanicsSource:
    return MechanicsSource(
        source_page_id=(int(row["source_page_id"]) if row["source_page_id"] is not None else None),
        source_name=str(row["source_name"] or ""),
        source_kind=str(row["source_kind"] or ""),
        source_key=str(row["source_key"] or ""),
        source_version=str(row["source_version"] or ""),
        local_path=str(row["local_path"] or ""),
        url=str(row["url"] or ""),
    )


def _stacking_row(db: Database, spell_id: int):
    return db.conn.execute(
        """
        SELECT ss.*,sp.source_name,sp.source_kind,sp.source_key,sp.source_version,
               sp.local_path,sp.url
        FROM spell_stacking ss
        LEFT JOIN source_pages sp ON sp.id=ss.source_page_id
        WHERE ss.spell_id=?
        """,
        (int(spell_id),),
    ).fetchone()


def _peer_rows(db: Database, stacking_group: int) -> tuple[SpellStackingPeer, ...]:
    rows = db.conn.execute(
        """
        SELECT ss.*,sp.source_name,sp.source_kind,sp.source_key,sp.source_version,
               sp.local_path,sp.url
        FROM spell_stacking ss
        LEFT JOIN source_pages sp ON sp.id=ss.source_page_id
        WHERE ss.stacking_group=?
        ORDER BY CASE WHEN ss.rank IS NULL THEN 1 ELSE 0 END,ss.rank,ss.spell_id
        """,
        (int(stacking_group),),
    ).fetchall()
    peers: list[SpellStackingPeer] = []
    for row in rows:
        spell_id = int(row["spell_id"])
        entity = spell_entity_for_client_id(db, spell_id)
        peers.append(
            SpellStackingPeer(
                entity_id=(int(entity["id"]) if entity is not None else None),
                spell_id=spell_id,
                name=(str(entity["name"]) if entity is not None else f"spell ID {spell_id}"),
                stacking_group=(int(row["stacking_group"]) if row["stacking_group"] is not None else None),
                rank=(int(row["rank"]) if row["rank"] is not None else None),
                stacking_type=(int(row["stacking_type"]) if row["stacking_type"] is not None else None),
                source=_source_from_row(row),
            )
        )
    return tuple(peers)


def build_spell_stacking_context(
    db: Database,
    spell_entity_id: int,
) -> tuple[SpellStackingContext | None, str]:
    """Project one canonical spell's installed-client stacking row read-only.

    Numeric stacking fields are intentionally exposed without interpreting them as a
    stacking/overwrite verdict. Identity resolution is gated through installed-client
    spell IDs so another provider's coincident numeric ID cannot become client truth.
    """
    entity = db.entity(int(spell_entity_id))
    if entity is None or str(entity["kind"] or "") != "spell":
        return None, "entity_missing"

    spell_id = spell_id_for_entity(db, int(spell_entity_id))
    if spell_id is None:
        return None, "client_identity_missing"

    row = _stacking_row(db, spell_id)
    if row is None:
        return (
            SpellStackingContext(
                entity_id=int(spell_entity_id),
                name=str(entity["name"]),
                spell_id=int(spell_id),
                stacking_group=None,
                rank=None,
                stacking_type=None,
                source=None,
                peers=(),
            ),
            "stacking_missing",
        )

    group = int(row["stacking_group"]) if row["stacking_group"] is not None else None
    peers = _peer_rows(db, group) if group is not None else ()
    return (
        SpellStackingContext(
            entity_id=int(spell_entity_id),
            name=str(entity["name"]),
            spell_id=int(spell_id),
            stacking_group=group,
            rank=(int(row["rank"]) if row["rank"] is not None else None),
            stacking_type=(int(row["stacking_type"]) if row["stacking_type"] is not None else None),
            source=_source_from_row(row),
            peers=peers,
        ),
        "linked",
    )


def spell_stacking_text(db: Database, spell_entity_id: int) -> str:
    context, status = build_spell_stacking_context(db, spell_entity_id)
    if context is None:
        if status == "client_identity_missing":
            entity = db.entity(int(spell_entity_id))
            name = str(entity["name"]) if entity is not None else f"entity {spell_entity_id}"
            return f"{name}\n\nNo installed-client spell identity is linked to this canonical spell."
        return f"No canonical spell entity is present for entity ID {spell_entity_id}."

    lines = [
        f"{context.name} | EQ client spell ID {context.spell_id}",
        "Stacking group/rank/type are shown exactly as stored by the installed client; EverQuestie does not infer a stacking verdict from these numeric fields.",
    ]
    if status == "stacking_missing":
        lines += ["", "No SpellStackingGroups-derived row is present in shipped knowledge for this client spell ID."]
        return "\n".join(lines)

    lines += [
        "",
        f"Stacking group: {context.stacking_group}",
        f"Rank: {context.rank}",
        f"Stacking type: {context.stacking_type}",
        f"Source: {context.source.label if context.source is not None else 'EverQuestie knowledge'}",
    ]
    if context.stacking_group is not None:
        lines += ["", f"Other rows in stacking group {context.stacking_group}:"]
        for peer in context.peers:
            marker = " ← selected" if peer.spell_id == context.spell_id else ""
            lines.append(
                f"  • {peer.name} | ID {peer.spell_id} | rank {peer.rank} | type {peer.stacking_type}{marker} | source: {peer.source.label}"
            )
    return "\n".join(lines)
