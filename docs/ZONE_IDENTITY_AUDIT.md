# Canonical zone identity audit

EverQuestie keeps source provenance instead of silently discarding provider records. As the knowledge corpus grows, multiple `entities(kind='zone')` rows can therefore share the same display name even though the EverQuest client supplies one authoritative live-game zone identity.

The runtime authority rule and destructive entity canonicalization are intentionally different operations:

- a unique EQ-client-backed member of an exact-name collision is a safe **gameplay join target** for live zone, map and travel projections;
- that does **not** prove every provider row with the same name represents the same underlying zone instance;
- multiple EQ-client IDs with the same display name remain a genuine identity ambiguity;
- provider-only duplicates require provider-specific evidence before consolidation.

Run the read-only audit against a builder DB or finalized knowledge snapshot:

```powershell
python tools\audit_zone_identities.py <everquestie-db>
python tools\audit_zone_identities.py <everquestie-db> --json --examples 100
```

The audit classifies exact normalized-name groups as:

- `unique_client` — one EQ-client-backed zone entity;
- `provider_only_unique` — one zone entity without an EQ-client ID;
- `client_authority_duplicate` — several exact-name entities with exactly one EQ-client-backed member;
- `multi_client_collision` — several exact-name entities and more than one EQ-client-backed member;
- `provider_only_duplicate` — several exact-name entities with no EQ-client-backed member.

For each duplicate member it inventories external IDs, source providers, aliases and downstream references through relationships, locations, map bindings and travel edges. Those reference counts are deliberately visible because a future canonicalization pass cannot safely delete a duplicate row; it must move or reconcile every dependent fact and preserve provenance.

This tool never changes entity IDs, rewrites provenance or merges knowledge.
