from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .db import normalize_name
from .eqmap import normalize_map_name
from .zone_authority import prefer_eqclient_zone_resolution
from .zone_identity import ZoneIdentityIndex


ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND = "curated_zone_alias_manifest"
ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE = "reviewed_zone_alias"
ZONE_ALIAS_SUPPLEMENT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ZoneAliasSupplementBuildStats:
    source_name: str
    source_version: str
    aliases: int


@dataclass(frozen=True, slots=True)
class _ResolvedAlias:
    entity_id: int
    canonical_name: str
    eq_zone_id: str
    alias: str
    source_key: str
    evidence: str
    source_urls: tuple[str, ...]


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _source_urls(raw: Any, default_url: str) -> tuple[str, ...]:
    if raw is None:
        values: list[Any] = [default_url] if default_url else []
    elif isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = raw
    else:
        raise ValueError("zone alias source_urls must be a string or array")
    urls = tuple(dict.fromkeys(_clean(value) for value in values if _clean(value)))
    if not urls:
        raise ValueError("zone alias requires at least one source URL")
    return urls


class ZoneAliasSupplementImporter:
    """Attach reviewed human zone aliases to exact EverQuest client identities.

    This builder-only compiler exists for identity facts that are source-backed but are
    not emitted by the installed client's ZoneNames.txt. It never creates zones, never
    fuzzy-matches a canonical name, never changes an EverQuest client ID, and never
    adds travel topology. Runtime consumes only the finalized ordinary entity_aliases
    rows.

    Every alias entry must pin both the canonical display name and ``eq_zone_id``. The
    numeric client ID is an additional constraint, not an override: the display name
    must resolve to (or ambiguously include) that exact client-backed identity. Alias
    collisions fail closed before any previously compiled rows are replaced.
    """

    def __init__(self, db):
        if not getattr(db, "knowledge_writable", True):
            raise RuntimeError("zone alias supplement import is builder-only")
        role = ""
        get_meta = getattr(db, "get_meta", None)
        if callable(get_meta):
            role = _clean(get_meta("database_role", ""))
        if role == "knowledge_snapshot":
            raise RuntimeError(
                "zone alias supplement import refuses finalized knowledge snapshots; "
                "apply it to the builder/working database and finalize a new copy"
            )
        self.db = db

    @staticmethod
    def _load(path: str | Path) -> dict[str, Any]:
        manifest_path = Path(path).expanduser().resolve()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("zone alias supplement manifest root must be a JSON object")
        return payload

    @staticmethod
    def _resolve_pinned_zone(
        index: ZoneIdentityIndex,
        canonical_name: str,
        eq_zone_id: str,
        *,
        field: str,
    ) -> int:
        id_resolution = index.resolve(eq_zone_id)
        if (
            id_resolution.status != "linked"
            or id_resolution.identity is None
            or id_resolution.entity_id is None
            or eq_zone_id not in id_resolution.identity.client_zone_ids
        ):
            raise ValueError(
                f"{field} eqclient zone ID {eq_zone_id!r} has no unique EverQuest client zone identity"
            )
        pinned_entity_id = int(id_resolution.entity_id)

        name_resolution = prefer_eqclient_zone_resolution(
            index.resolve(canonical_name), canonical_name
        )
        if name_resolution.status == "linked" and name_resolution.entity_id is not None:
            if int(name_resolution.entity_id) != pinned_entity_id:
                raise ValueError(
                    f"{field} canonical name {canonical_name!r} does not match "
                    f"eqclient zone ID {eq_zone_id!r}"
                )
            return pinned_entity_id
        if name_resolution.status == "ambiguous":
            candidate_ids = {int(candidate.entity_id) for candidate in name_resolution.candidates}
            if pinned_entity_id in candidate_ids:
                return pinned_entity_id
        raise ValueError(
            f"{field} canonical name {canonical_name!r} does not include "
            f"eqclient zone ID {eq_zone_id!r} among its authoritative candidates"
        )

    def _validated_aliases(
        self,
        payload: dict[str, Any],
    ) -> tuple[str, str, tuple[_ResolvedAlias, ...]]:
        schema_version = payload.get(
            "schema_version", ZONE_ALIAS_SUPPLEMENT_SCHEMA_VERSION
        )
        if schema_version != ZONE_ALIAS_SUPPLEMENT_SCHEMA_VERSION:
            raise ValueError(
                "unsupported zone alias supplement schema_version "
                f"{schema_version!r}; expected {ZONE_ALIAS_SUPPLEMENT_SCHEMA_VERSION}"
            )

        source_name = _clean(payload.get("source_name"))
        source_version = _clean(payload.get("source_version"))
        default_source_url = _clean(payload.get("source_url"))
        if not source_name:
            raise ValueError("zone alias supplement requires non-empty source_name")
        if not source_version:
            raise ValueError("zone alias supplement requires non-empty source_version")

        raw_aliases = payload.get("aliases")
        if not isinstance(raw_aliases, list):
            raise ValueError("zone alias supplement requires an aliases array")
        if not raw_aliases:
            raise ValueError("zone alias supplement requires at least one alias")

        index = ZoneIdentityIndex(self.db, include_map_bindings=True)
        seen_keys: set[str] = set()
        seen_alias_tokens: dict[str, int] = {}
        resolved: list[_ResolvedAlias] = []
        for position, raw in enumerate(raw_aliases, start=1):
            if not isinstance(raw, dict):
                raise ValueError(
                    f"zone alias supplement alias {position} must be a JSON object"
                )
            canonical_name = _clean(raw.get("canonical_name"))
            eq_zone_id = _clean(raw.get("eq_zone_id"))
            alias = _clean(raw.get("alias"))
            source_key = _clean(raw.get("source_key"))
            evidence = _clean(raw.get("evidence"))
            if not canonical_name or not eq_zone_id or not alias:
                raise ValueError(
                    f"zone alias supplement alias {position} requires canonical_name, "
                    "eq_zone_id, and alias"
                )
            if not source_key:
                raise ValueError(
                    f"zone alias supplement alias {position} requires source_key"
                )
            if not evidence:
                raise ValueError(
                    f"zone alias supplement alias {position} requires explicit evidence"
                )
            if alias.isdigit():
                raise ValueError(
                    f"zone alias supplement alias {position} must be a human-readable name"
                )
            if source_key in seen_keys:
                raise ValueError(f"duplicate zone alias supplement source_key: {source_key}")
            seen_keys.add(source_key)

            entity_id = self._resolve_pinned_zone(
                index,
                canonical_name,
                eq_zone_id,
                field=f"alias {position}",
            )
            if normalize_map_name(alias) == normalize_map_name(canonical_name):
                raise ValueError(
                    f"zone alias supplement alias {position} duplicates its canonical zone name"
                )

            token = normalize_map_name(alias)
            previous_target = seen_alias_tokens.get(token)
            if previous_target is not None and previous_target != entity_id:
                raise ValueError(
                    f"zone alias {alias!r} targets multiple canonical zones in one manifest"
                )
            seen_alias_tokens[token] = entity_id

            existing = index.resolve(alias)
            if existing.status == "linked" and existing.entity_id is not None:
                if int(existing.entity_id) != entity_id:
                    raise ValueError(
                        f"zone alias {alias!r} already resolves to a different canonical zone"
                    )
            elif existing.status == "ambiguous":
                candidate_ids = {int(candidate.entity_id) for candidate in existing.candidates}
                if candidate_ids != {entity_id}:
                    raise ValueError(
                        f"zone alias {alias!r} is already an ambiguous canonical identity token"
                    )

            urls = _source_urls(
                raw.get("source_urls", raw.get("source_url")),
                default_source_url,
            )
            resolved.append(
                _ResolvedAlias(
                    entity_id=entity_id,
                    canonical_name=canonical_name,
                    eq_zone_id=eq_zone_id,
                    alias=alias,
                    source_key=source_key,
                    evidence=evidence,
                    source_urls=urls,
                )
            )

        return source_name, source_version, tuple(resolved)

    @staticmethod
    def _provenance_url(source_url: str, source_key: str) -> str:
        separator = "&" if "#" in source_url else "#"
        return (
            f"{source_url}{separator}everquestie-zone-alias-"
            f"{quote(source_key, safe='')}"
        )

    def import_manifest(self, path: str | Path) -> ZoneAliasSupplementBuildStats:
        payload = self._load(path)
        source_name, source_version, aliases = self._validated_aliases(payload)

        # Validate the complete manifest before removing any last-known-good rows.
        with self.db.batch():
            self.db.conn.execute(
                "DELETE FROM source_pages WHERE source_kind=? AND source_name=?",
                (ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND, source_name),
            )
            for alias in aliases:
                provenance_text = "\n".join(
                    [
                        alias.evidence,
                        "",
                        *(f"Supporting source: {url}" for url in alias.source_urls),
                    ]
                )
                digest_payload = json.dumps(
                    {
                        "canonical_name": alias.canonical_name,
                        "eq_zone_id": alias.eq_zone_id,
                        "alias": alias.alias,
                        "source_key": alias.source_key,
                        "evidence": alias.evidence,
                        "source_urls": alias.source_urls,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
                source_page_id = self.db.upsert_source_page(
                    url=self._provenance_url(alias.source_urls[0], alias.source_key),
                    title=f"Reviewed zone alias: {alias.alias} → {alias.canonical_name}",
                    entity_type="zone_alias",
                    sha256=hashlib.sha256(digest_payload).hexdigest(),
                    plain_text=provenance_text,
                    raw_html="",
                    source_name=source_name,
                    source_kind=ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,
                    source_key=alias.source_key,
                    source_version=source_version,
                )
                self.db.add_alias(
                    alias.entity_id,
                    alias.alias,
                    alias_type=ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,
                    source_page_id=source_page_id,
                )
                self.db.link_entity_source(
                    alias.entity_id,
                    source_page_id,
                    role="identity_alias",
                    confidence=1.0,
                )

        return ZoneAliasSupplementBuildStats(
            source_name=source_name,
            source_version=source_version,
            aliases=len(aliases),
        )
