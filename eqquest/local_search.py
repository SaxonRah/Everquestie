from __future__ import annotations

from dataclasses import dataclass
import re
import shlex

from .db import Database, normalize_name


_KIND_ALIASES = {
    "quests": "quest",
    "npcs": "npc",
    "bestiary": "npc",
    "items": "item",
    "zones": "zone",
    "factions": "faction",
    "spells": "spell",
    "recipes": "recipe",
    "achievements": "achievement",
    "aas": "aa",
    "alternate_advancement": "aa",
    "overseer_agents": "overseer_agent",
    "overseer_quests": "overseer_quest",
    "mercenaries": "mercenary",
    "tributes": "tribute",
    "combat_abilities": "combat_ability",
}


@dataclass(frozen=True, slots=True)
class LocalQuery:
    text: str = ""
    kinds: tuple[str, ...] = ()
    zone: str | None = None
    source: str | None = None
    exact: bool = False


@dataclass(slots=True)
class SearchHit:
    row: object
    score: tuple
    reason: str
    current_zone: bool = False


def _kind_name(value: str) -> str:
    value = normalize_name(value).replace(" ", "_")
    return _KIND_ALIASES.get(value, value)


def parse_local_query(raw: str) -> LocalQuery:
    """Parse a forgiving local-search query.

    Supported filters are ``type:``/``kind:``, ``zone:``, ``source:``,
    ``exact:true`` and ``exact:<name>``. Quoted values work through shlex, e.g.
    ``type:npc zone:"Stone Hive" "Waning Wendlez"``.
    """
    raw = (raw or "").strip()
    if not raw:
        return LocalQuery()
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError:
        tokens = raw.split()

    text: list[str] = []
    kinds: list[str] = []
    zone = None
    source = None
    exact = False

    for token in tokens:
        if ":" not in token:
            text.append(token)
            continue
        key, value = token.split(":", 1)
        key = key.casefold().strip()
        value = value.strip()
        if key in {"type", "kind"} and value:
            for part in re.split(r"[,|]", value):
                kind = _kind_name(part)
                if kind and kind not in kinds:
                    kinds.append(kind)
        elif key == "zone" and value:
            zone = value
        elif key == "source" and value:
            source = value
        elif key in {"name", "exact"}:
            if key == "name" and value:
                exact = True
                text.append(value)
            elif value.casefold() in {"1", "true", "yes", "on"}:
                exact = True
            elif value.casefold() in {"0", "false", "no", "off"}:
                exact = False
            elif value:
                exact = True
                text.append(value)
        else:
            text.append(token)

    return LocalQuery(
        text=" ".join(text).strip(),
        kinds=tuple(kinds),
        zone=zone,
        source=source,
        exact=exact,
    )


def query_summary(raw: str, *, default_kind: str | None = None) -> str:
    q = parse_local_query(raw)
    parts: list[str] = []
    kinds = list(q.kinds)
    if default_kind and default_kind != "all" and not kinds:
        kinds = [default_kind]
    if q.text:
        parts.append(("exact " if q.exact else "") + f'name="{q.text}"')
    if kinds:
        parts.append("type=" + ",".join(kinds))
    if q.zone:
        parts.append(f'zone="{q.zone}"')
    if q.source:
        parts.append(f'source="{q.source}"')
    return "; ".join(parts) if parts else "all local entities"


def _effective_kinds(query: LocalQuery, default_kind: str | None) -> tuple[str, ...]:
    if default_kind in {None, "", "all"}:
        return query.kinds
    default = _kind_name(default_kind)
    if not query.kinds:
        return (default,)
    return (default,) if default in query.kinds else ("__no_match__",)


def _filter_sql(
    query: LocalQuery,
    *,
    default_kind: str | None,
    current_zone: str | None,
    include_text: bool,
    fts: bool,
) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    args: list[object] = []
    kinds = _effective_kinds(query, default_kind)
    if kinds:
        placeholders = ",".join("?" for _ in kinds)
        clauses.append(f"e.kind IN ({placeholders})")
        args.extend(kinds)

    if include_text and query.text:
        norm = normalize_name(query.text)
        if query.exact:
            clauses.append(
                "(e.normalized_name=? OR EXISTS (SELECT 1 FROM entity_aliases ax "
                "WHERE ax.entity_id=e.id AND ax.normalized_alias=?))"
            )
            args.extend([norm, norm])
        elif not fts:
            needle = f"%{norm}%"
            clauses.append(
                "(e.normalized_name LIKE ? OR EXISTS (SELECT 1 FROM entity_aliases ax "
                "WHERE ax.entity_id=e.id AND ax.normalized_alias LIKE ?))"
            )
            args.extend([needle, needle])

    zone = query.zone
    if zone and zone.casefold() == "current":
        zone = current_zone
    if zone:
        zone_norm = normalize_name(zone)
        clauses.append(
            "((e.kind='zone' AND e.normalized_name=?) OR lower(trim(COALESCE(e.zone,'')))=? OR EXISTS ("
            "SELECT 1 FROM entity_locations lz LEFT JOIN entities zz ON zz.id=lz.zone_entity_id "
            "WHERE lz.entity_id=e.id AND zz.normalized_name=?))"
        )
        args.extend([zone_norm, zone_norm, zone_norm])

    if query.source:
        needle = "%" + query.source.casefold().strip() + "%"
        clauses.append(
            "EXISTS (SELECT 1 FROM entity_sources es JOIN source_pages sx ON sx.id=es.source_page_id "
            "WHERE es.entity_id=e.id AND (lower(sx.source_name) LIKE ? OR lower(sx.source_kind) LIKE ? "
            "OR lower(sx.url) LIKE ? OR lower(sx.local_path) LIKE ?))"
        )
        args.extend([needle, needle, needle, needle])
    return clauses, args


def _current_zone_ids(db: Database, current_zone: str | None) -> set[int]:
    if not current_zone:
        return set()
    ids = {int(row["entity_id"]) for row in db.locations_in_zone(current_zone)}
    zone_row, _status = db.resolve_entity(current_zone, "zone")
    if zone_row is not None:
        ids.add(int(zone_row["id"]))
    norm = normalize_name(current_zone)
    for row in db.conn.execute("SELECT id FROM entities WHERE lower(trim(COALESCE(zone,'')))=?", (norm,)):
        ids.add(int(row["id"]))
    return ids


def _reason_for(db: Database, row, text: str, zone_match: bool, fts_rank: float | None) -> tuple[tuple, str]:
    norm = normalize_name(text)
    name = str(row["normalized_name"] or "")
    aliases = (
        [str(a["normalized_alias"]) for a in db.aliases_for_entity(int(row["id"]))]
        if norm else []
    )
    if norm and name == norm:
        base, reason = 0, "exact name"
    elif norm and norm in aliases:
        base, reason = 1, "exact alias"
    elif norm and name.startswith(norm):
        base, reason = 2, "name prefix"
    elif norm and any(alias.startswith(norm) for alias in aliases):
        base, reason = 3, "alias prefix"
    elif norm and norm in name:
        base, reason = 4, "name contains"
    elif norm and any(norm in alias for alias in aliases):
        base, reason = 5, "alias contains"
    else:
        base, reason = 6, "full-text"
    if zone_match:
        reason += " · current zone"
    rank = float(fts_rank) if fts_rank is not None else 0.0
    return (base, 0 if zone_match else 1, rank, str(row["kind"]), str(row["name"]).casefold()), reason


def search_local_hits(
    db: Database,
    raw_query: str | LocalQuery,
    *,
    default_kind: str | None = None,
    current_zone: str | None = None,
    limit: int = 250,
    offset: int = 0,
) -> list[SearchHit]:
    query = raw_query if isinstance(raw_query, LocalQuery) else parse_local_query(raw_query)
    safe_limit = max(1, min(int(limit), 5000))
    safe_offset = max(0, int(offset))
    use_fts = bool(
        query.text
        and not query.exact
        and db.fts_available
        and db.get_meta("fts_dirty", "1") != "1"
        and db._fts_query(query.text)
    )
    clauses, args = _filter_sql(
        query,
        default_kind=default_kind,
        current_zone=current_zone,
        include_text=True,
        fts=use_fts,
    )
    if use_fts:
        clauses.insert(0, "entity_fts MATCH ?")
        args.insert(0, db._fts_query(query.text))
        sql = (
            "SELECT e.*, sp.title AS source_title, bm25(entity_fts, 3.0, 1.5, 0.5) AS fts_rank "
            "FROM entity_fts JOIN entities e ON e.id=CAST(entity_fts.entity_id AS INTEGER) "
            "LEFT JOIN source_pages sp ON sp.id=e.source_page_id"
        )
    else:
        sql = (
            "SELECT e.*, sp.title AS source_title, NULL AS fts_rank FROM entities e "
            "LEFT JOIN source_pages sp ON sp.id=e.source_page_id"
        )
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    # Pull extra candidates before contextual ranking, then apply the requested page.
    candidate_limit = min(5000, max(safe_limit * 8, safe_limit + safe_offset, 250))
    if use_fts:
        sql += " ORDER BY fts_rank, e.kind, e.name LIMIT ?"
    else:
        sql += " ORDER BY e.kind, e.name LIMIT ?"
    args.append(candidate_limit)
    try:
        rows = db.conn.execute(sql, args).fetchall()
    except Exception:
        # FTS is an acceleration layer, not a correctness dependency.
        if use_fts:
            return _search_like_fallback(db, query, default_kind, current_zone, limit, offset)
        raise

    zone_ids = _current_zone_ids(db, current_zone)
    hits: list[SearchHit] = []
    for row in rows:
        zone_match = int(row["id"]) in zone_ids
        score, reason = _reason_for(db, row, query.text, zone_match, row["fts_rank"])
        hits.append(SearchHit(row=row, score=score, reason=reason, current_zone=zone_match))
    hits.sort(key=lambda hit: hit.score)
    return hits[safe_offset : safe_offset + safe_limit]


def _search_like_fallback(
    db: Database,
    query: LocalQuery,
    default_kind: str | None,
    current_zone: str | None,
    limit: int,
    offset: int,
) -> list[SearchHit]:
    clauses, args = _filter_sql(
        query,
        default_kind=default_kind,
        current_zone=current_zone,
        include_text=True,
        fts=False,
    )
    sql = (
        "SELECT e.*, sp.title AS source_title, NULL AS fts_rank FROM entities e "
        "LEFT JOIN source_pages sp ON sp.id=e.source_page_id"
    )
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY e.kind, e.name LIMIT 5000"
    rows = db.conn.execute(sql, args).fetchall()
    zone_ids = _current_zone_ids(db, current_zone)
    hits = []
    for row in rows:
        zone_match = int(row["id"]) in zone_ids
        score, reason = _reason_for(db, row, query.text, zone_match, None)
        hits.append(SearchHit(row=row, score=score, reason=reason, current_zone=zone_match))
    hits.sort(key=lambda hit: hit.score)
    return hits[max(0, offset) : max(0, offset) + max(1, limit)]


def search_local_entities(db: Database, raw_query: str, **kwargs):
    return [hit.row for hit in search_local_hits(db, raw_query, **kwargs)]


def count_local_entities_by_kind(
    db: Database,
    raw_query: str,
    *,
    default_kind: str | None = None,
    current_zone: str | None = None,
) -> list[dict[str, object]]:
    query = parse_local_query(raw_query)
    use_fts = bool(
        query.text
        and not query.exact
        and db.fts_available
        and db.get_meta("fts_dirty", "1") != "1"
        and db._fts_query(query.text)
    )
    clauses, args = _filter_sql(
        query,
        default_kind=default_kind,
        current_zone=current_zone,
        include_text=True,
        fts=use_fts,
    )
    if use_fts:
        clauses.insert(0, "entity_fts MATCH ?")
        args.insert(0, db._fts_query(query.text))
        sql = "SELECT e.kind, COUNT(DISTINCT e.id) AS count FROM entity_fts JOIN entities e ON e.id=CAST(entity_fts.entity_id AS INTEGER)"
    else:
        sql = "SELECT e.kind, COUNT(*) AS count FROM entities e"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " GROUP BY e.kind ORDER BY e.kind"
    try:
        rows = db.conn.execute(sql, args).fetchall()
    except Exception:
        if use_fts:
            clauses, args = _filter_sql(query, default_kind=default_kind, current_zone=current_zone, include_text=True, fts=False)
            sql = "SELECT e.kind, COUNT(*) AS count FROM entities e"
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " GROUP BY e.kind ORDER BY e.kind"
            rows = db.conn.execute(sql, args).fetchall()
        else:
            raise
    return [{"kind": str(row["kind"]), "count": int(row["count"])} for row in rows]


def map_label_terms(term: str) -> list[str]:
    """Generate canonical guesses from decorated Good/Brewall map labels."""
    raw = " ".join((term or "").replace("_", " ").split()).strip()
    if not raw:
        return []
    variants: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = " ".join(value.split()).strip(" -*?:;,.[]{}")
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            variants.append(value)

    add(raw)
    prefix_re = re.compile(r"^(?:zone\s+to|exit\s+to|entrance\s+to|portal\s+to|to)\s+", re.I)
    add(prefix_re.sub("", raw))

    clean = raw
    # Strip one or more trailing role/quest/map-author notes.
    while re.search(r"\s*\([^)]*\)\s*$", clean):
        clean = re.sub(r"\s*\([^)]*\)\s*$", "", clean).strip()
        add(clean)
        add(prefix_re.sub("", clean))
    clean = re.sub(r"[?*#]+$", "", clean).strip()
    add(clean)
    add(prefix_re.sub("", clean))
    return variants


def resolve_local_hits(
    db: Database,
    term: str,
    *,
    kind: str | None = None,
    current_zone: str | None = None,
    preferred_entity_id: int | None = None,
    limit: int = 40,
) -> list[SearchHit]:
    hits: list[SearchHit] = []
    seen: set[int] = set()
    if preferred_entity_id is not None:
        row = db.entity(preferred_entity_id)
        if row is not None:
            eid = int(row["id"])
            seen.add(eid)
            hits.append(SearchHit(row=row, score=(-2, 0, 0.0, str(row["kind"]), str(row["name"])), reason="selected map entity", current_zone=True))

    terms = map_label_terms(term)
    for candidate in terms:
        exact_query = LocalQuery(text=candidate, kinds=((kind,) if kind else ()), exact=True)
        for hit in search_local_hits(db, exact_query, current_zone=current_zone, limit=20):
            eid = int(hit.row["id"])
            if eid not in seen:
                seen.add(eid)
                hits.append(hit)
    for candidate in terms:
        for hit in search_local_hits(db, candidate, default_kind=kind, current_zone=current_zone, limit=limit):
            eid = int(hit.row["id"])
            if eid not in seen:
                seen.add(eid)
                hits.append(hit)
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    hits.sort(key=lambda hit: hit.score)
    return hits[:limit]
