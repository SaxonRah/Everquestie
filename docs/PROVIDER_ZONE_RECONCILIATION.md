# Provider zone reconciliation

EverQuestie keeps provider zone entities and live gameplay zone identity separate.

The installed EverQuest client is authoritative for gameplay identity. Provider rows
(Allakhazam today, additional mirrors later) retain their own external IDs, source pages,
relationships and provenance. They are not destructively merged into the client entity.

`zone_provider_bindings` is a builder-owned derived catalog that states whether facts
attached to one provider zone may be projected into one canonical gameplay zone.

## Binding statuses

- `linked` — safe for runtime knowledge projection. The provider zone has one exact-name
  EQ-client target and independent structured provider topology corroboration.
- `candidate` — one exact-name EQ-client target exists, but there is not enough
  independent evidence to project provider facts automatically.
- `ambiguous` — more than one EQ-client-backed zone owns the same exact canonical name.
- `unresolved` — no EQ-client-backed exact-name target exists.

Only `linked` rows are consumed by player-facing projections.

A `linked` binding is **not** permission to merge or delete the provider entity. It means
only that the provider's facts are safe to view in the target gameplay-zone context.

## Initial corroboration rule

The v1 catalog deliberately does not treat a display-name match as proof. Automatic
linking requires:

1. exactly one EQ-client-backed zone with the same normalized canonical name; and
2. at least one structured provider `connected_to` relationship touching the provider
   zone; and
3. the neighboring provider zone on that relationship must independently have exactly
   one EQ-client-backed exact-name target.

Allakhazam's structured **Connected Zones** table supplies this evidence today. The
binding stores the relationship ID, direction, source identity and neighboring provider
and gameplay IDs so the decision remains auditable after packaging.

## Build/runtime boundary

`ProviderZoneReconciliationCatalog.reconcile()` is builder-only. Snapshot finalization
runs it after all providers have imported and persists its coverage metadata alongside
the table.

`RuntimeDatabase` exposes the finalized table through its normal read-only knowledge
views. Runtime never scans mirrors, resolves provider identities, or writes bindings.

Zone Context keeps the EQ-client zone as the canonical coordinate/identity space. A
location originally attached to a linked provider zone is surfaced as a location in the
canonical gameplay zone while `ZoneLocatedEntity.projected_from_zone_entity_id` retains
the original provider-zone ID for diagnostics and provenance tracing.

This separation lets future provider enrichments improve NPC, quest, item, location and
travel context without making provider mirrors runtime dependencies and without losing
source-specific identity.
