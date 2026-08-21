from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Iterable

from .db import normalize_name
from .eqmap import normalize_map_name


SHORT_NAME_KEYS = (
    "map_short_name",
    "short_name",
    "shortName",
    "zone_short_name",
    "zoneShortName",
)
_STOP_WORDS = {"the", "of", "a", "an", "and"}


@dataclass(frozen=True, slots=True)
class ZoneIdentity:
    """One canonical EverQuest zone and the identity signals attached to it."""

    entity_id: int
    name: str
    aliases: tuple[str, ...]
    short_names: tuple[str, ...]
    client_zone_ids: tuple[str, ...]
    map_stems: tuple[str, ...]

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)


@dataclass(frozen=True, slots=True)
class ZoneResolution:
    """Conservative result from resolving one external zone token."""

    status: str
    match_kind: str
    reason: str
    identity: ZoneIdentity | None
    candidates: tuple[ZoneIdentity, ...] = ()

    @property
    def entity_id(self) -> int | None:
        return self.identity.entity_id if self.identity is not None else None

    @property
    def zone_name(self) -> str:
        return self.identity.name if self.identity is not None else ""


class ZoneIdentityIndex:
    """Canonical join layer for zone names, aliases, IDs and map short names.

    A zone has exactly one canonical ``entities(kind='zone')`` identity. Client zone
    IDs, provider aliases, provider/client short names and confirmed map-pack stems are
    evidence attached to that identity, not separate zone records.

    Runtime callers use exact identity by default. Builder-only callers that must infer
    a map filename may opt into the same conservative significant-word/containment
    rules used by the historic map catalog. Ambiguity is always preserved.

    ``include_derived_map_short_names`` separates finalized runtime knowledge from
    builder inputs. Runtime/travel may consume the short-name hint derived from a
    confirmed zone/map binding; map reconciliation itself disables that signal so a
    previous derived binding cannot prove and perpetuate itself.
    """

    def __init__(
        self,
        db,
        *,
        include_map_bindings: bool = True,
        include_derived_map_short_names: bool = True,
    ):
        self.db = db
        self.include_map_bindings = bool(include_map_bindings)
        self.include_derived_map_short_names = bool(include_derived_map_short_names)
        self._identities: dict[int, ZoneIdentity] = {}
        self._exact: dict[str, set[int]] = {}
        self._words: dict[str, set[int]] = {}
        self._containment_tokens: dict[int, set[str]] = {}
        self._load()

    def _object_exists(self, name: str) -> bool:
        return self.db.conn.execute(
            """
            SELECT 1 FROM sqlite_temp_master
            WHERE type IN ('table','view') AND name=?
            UNION ALL
            SELECT 1 FROM sqlite_master
            WHERE type IN ('table','view') AND name=?
            LIMIT 1
            """,
            (name, name),
        ).fetchone() is not None

    @staticmethod
    def _meaningful_words(value: str) -> set[str]:
        return {
            normalize_map_name(word)
            for word in re.findall(r"[A-Za-z0-9`']+", value or "")
            if normalize_map_name(word)
            and normalize_map_name(word) not in _STOP_WORDS
            and len(normalize_map_name(word)) >= 4
        }

    @staticmethod
    def _article_variants(value: str) -> tuple[str, ...]:
        value = " ".join((value or "").split()).strip()
        if not value:
            return ()
        variants = [value]
        if value.casefold().startswith("the ") and len(value) > 4:
            variants.append(value[4:])
        return tuple(dict.fromkeys(variants))

    def _add_exact(self, value: str, entity_id: int) -> None:
        token = normalize_map_name(value)
        if token:
            self._exact.setdefault(token, set()).add(int(entity_id))

    def _add_words(self, value: str, entity_id: int) -> None:
        for token in self._meaningful_words(value):
            self._words.setdefault(token, set()).add(int(entity_id))

    def _load(self) -> None:
        zone_rows = self.db.conn.execute(
            "SELECT id,name,data_json FROM entities WHERE kind='zone' ORDER BY id"
        ).fetchall()
        zone_ids = {int(row["id"]) for row in zone_rows}

        aliases: dict[int, list[str]] = {entity_id: [] for entity_id in zone_ids}
        if zone_ids:
            # Filter to zone aliases inside SQLite.  Large release snapshots contain
            # aliases for hundreds of thousands of items/NPCs/etc.; materializing all
            # of them in Python whenever a ZoneIdentityIndex is constructed makes a
            # live zone change stall the Tk UI.
            for row in self.db.conn.execute(
                """
                SELECT a.entity_id, a.alias, a.alias_type
                FROM entity_aliases a
                JOIN entities e ON e.id=a.entity_id
                WHERE e.kind='zone'
                ORDER BY a.entity_id, a.id
                """
            ).fetchall():
                entity_id = int(row["entity_id"])
                alias = str(row["alias"] or "").strip()
                alias_type = str(row["alias_type"] or "").casefold()
                # Numeric aliases from old imports are identity IDs, not human/map
                # tokens. Canonical client IDs are read from entity_external_ids.
                if not alias or alias.isdigit() or alias_type == "eq_zone_id":
                    continue
                aliases[entity_id].append(alias)

        client_ids: dict[int, list[str]] = {entity_id: [] for entity_id in zone_ids}
        if zone_ids:
            for row in self.db.conn.execute(
                "SELECT entity_id,external_id FROM entity_external_ids "
                "WHERE namespace='eqclient:zone' ORDER BY entity_id,external_id"
            ).fetchall():
                entity_id = int(row["entity_id"])
                if entity_id in zone_ids:
                    client_ids[entity_id].append(str(row["external_id"]))

        map_stems: dict[int, list[str]] = {entity_id: [] for entity_id in zone_ids}
        if self.include_map_bindings and self._object_exists("zone_map_bindings"):
            for row in self.db.conn.execute(
                "SELECT zone_entity_id,map_stem FROM zone_map_bindings "
                "WHERE status='linked' AND zone_entity_id IS NOT NULL "
                "ORDER BY zone_entity_id,source_name,map_stem"
            ).fetchall():
                entity_id = int(row["zone_entity_id"])
                if entity_id in zone_ids:
                    stem = str(row["map_stem"] or "").strip()
                    if stem:
                        map_stems[entity_id].append(stem)

        for row in zone_rows:
            entity_id = int(row["id"])
            name = str(row["name"])
            try:
                data: Any = json.loads(row["data_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                data = {}
            short_names: list[str] = []
            if isinstance(data, dict):
                derived_map_short_name = (
                    str(data.get("map_short_name_source") or "") == "zone_map_catalog"
                )
                for key in SHORT_NAME_KEYS:
                    if (
                        key == "map_short_name"
                        and derived_map_short_name
                        and not self.include_derived_map_short_names
                    ):
                        continue
                    value = str(data.get(key) or "").strip()
                    if value:
                        short_names.append(value)

            identity = ZoneIdentity(
                entity_id=entity_id,
                name=name,
                aliases=tuple(dict.fromkeys(aliases.get(entity_id, []))),
                short_names=tuple(dict.fromkeys(short_names)),
                client_zone_ids=tuple(dict.fromkeys(client_ids.get(entity_id, []))),
                map_stems=tuple(dict.fromkeys(map_stems.get(entity_id, []))),
            )
            self._identities[entity_id] = identity

            containment: set[str] = set()
            for variant in self._article_variants(name):
                self._add_exact(variant, entity_id)
                self._add_words(variant, entity_id)
                token = normalize_map_name(variant)
                if token:
                    containment.add(token)
            for alias in identity.aliases:
                for variant in self._article_variants(alias):
                    self._add_exact(variant, entity_id)
                    self._add_words(variant, entity_id)
                    token = normalize_map_name(variant)
                    if token:
                        containment.add(token)
            for value in identity.short_names:
                self._add_exact(value, entity_id)
                token = normalize_map_name(value)
                if token:
                    containment.add(token)
            for value in identity.map_stems:
                self._add_exact(value, entity_id)
                token = normalize_map_name(value)
                if token:
                    containment.add(token)
            for value in identity.client_zone_ids:
                self._add_exact(value, entity_id)
            self._containment_tokens[entity_id] = containment

    def identities(self) -> tuple[ZoneIdentity, ...]:
        return tuple(self._identities[key] for key in sorted(self._identities))

    def identity(self, entity_id: int) -> ZoneIdentity | None:
        return self._identities.get(int(entity_id))

    def _candidates(self, ids: Iterable[int]) -> tuple[ZoneIdentity, ...]:
        return tuple(
            self._identities[entity_id]
            for entity_id in sorted(set(int(value) for value in ids))
            if entity_id in self._identities
        )

    @staticmethod
    def _contains_token(values: Iterable[str], key: str) -> bool:
        return any(normalize_map_name(value) == key for value in values)

    def _exact_match_kind(self, identity: ZoneIdentity, raw: str, key: str) -> str:
        if raw.strip().isdigit() and raw.strip() in identity.client_zone_ids:
            return "client_id"
        if any(normalize_map_name(v) == key for v in self._article_variants(identity.name)):
            return "canonical_name"
        if any(
            normalize_map_name(v) == key
            for alias in identity.aliases
            for v in self._article_variants(alias)
        ):
            return "alias"
        if self._contains_token(identity.short_names, key):
            return "short_name"
        if self._contains_token(identity.map_stems, key):
            return "map_stem"
        if self._contains_token(identity.client_zone_ids, key):
            return "client_id"
        return "exact"

    @staticmethod
    def _exact_reason(match_kind: str) -> str:
        return {
            "canonical_name": "exact canonical zone name",
            "alias": "exact canonical zone alias",
            "short_name": "exact canonical zone short name",
            "map_stem": "exact confirmed zone/map binding",
            "client_id": "exact EverQuest client zone ID",
        }.get(match_kind, "exact canonical zone identity")

    def resolve(
        self,
        value: str,
        *,
        allow_significant_word: bool = False,
        allow_containment: bool = False,
    ) -> ZoneResolution:
        raw = " ".join((value or "").split()).strip()
        key = normalize_map_name(raw)
        if not key:
            return ZoneResolution("unresolved", "none", "empty zone identity token", None)

        exact = self._candidates(self._exact.get(key, set()))
        if len(exact) == 1:
            match_kind = self._exact_match_kind(exact[0], raw, key)
            return ZoneResolution(
                "linked",
                match_kind,
                self._exact_reason(match_kind),
                exact[0],
                exact,
            )
        if len(exact) > 1:
            return ZoneResolution(
                "ambiguous",
                "exact",
                f"exact zone token matches {len(exact)} canonical zones",
                None,
                exact,
            )

        if allow_significant_word:
            words = self._candidates(self._words.get(key, set()))
            if len(words) == 1:
                return ZoneResolution(
                    "linked",
                    "significant_word",
                    "unique significant zone-name word",
                    words[0],
                    words,
                )
            if len(words) > 1:
                return ZoneResolution(
                    "ambiguous",
                    "significant_word",
                    f"zone token is shared by {len(words)} canonical zone names",
                    None,
                    words,
                )

        if allow_containment and len(key) >= 5:
            ids = {
                entity_id
                for entity_id, tokens in self._containment_tokens.items()
                if any(
                    len(token) >= 5 and (key in token or token in key)
                    for token in tokens
                )
            }
            contained = self._candidates(ids)
            if len(contained) == 1:
                return ZoneResolution(
                    "linked",
                    "containment",
                    "unique canonical zone-token containment",
                    contained[0],
                    contained,
                )
            if len(contained) > 1:
                return ZoneResolution(
                    "ambiguous",
                    "containment",
                    f"zone token overlaps {len(contained)} canonical zones",
                    None,
                    contained,
                )

        return ZoneResolution(
            "unresolved",
            "none",
            "no conservative canonical zone identity match",
            None,
        )

    def exact_collisions(self) -> dict[str, tuple[ZoneIdentity, ...]]:
        """Return external tokens that currently point at multiple canonical zones."""
        return {
            token: self._candidates(ids)
            for token, ids in sorted(self._exact.items())
            if len(ids) > 1
        }


def resolve_zone(
    db,
    value: str,
    *,
    include_map_bindings: bool = True,
    include_derived_map_short_names: bool = True,
) -> ZoneResolution:
    """Resolve an exact zone identity without fuzzy/substring guessing."""
    return ZoneIdentityIndex(
        db,
        include_map_bindings=include_map_bindings,
        include_derived_map_short_names=include_derived_map_short_names,
    ).resolve(value)


def zone_identity_audit_text(db, *, detail_limit: int = 30) -> str:
    """Read-only audit of canonical zone identity pressure."""
    index = ZoneIdentityIndex(db)
    collisions = index.exact_collisions()
    identities = index.identities()
    client = sum(bool(identity.client_zone_ids) for identity in identities)
    mapped = sum(bool(identity.map_stems) for identity in identities)
    lines = [
        "Canonical zone identity audit",
        "",
        f"Zones: {len(identities)}",
        f"Zones with EQ client ID: {client}",
        f"Zones with confirmed map stem: {mapped}",
        f"Ambiguous exact external tokens: {len(collisions)}",
    ]
    for token, candidates in list(collisions.items())[: max(0, int(detail_limit))]:
        lines.append(
            f"  {token}: " + ", ".join(identity.name for identity in candidates)
        )
    if len(collisions) > detail_limit:
        lines.append(f"  ...and {len(collisions) - detail_limit} more")
    return "\n".join(lines)
