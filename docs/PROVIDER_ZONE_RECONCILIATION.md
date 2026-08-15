# Provider zone reconciliation

EverQuestie keeps provider zone entities and live gameplay zone identity separate.

The installed EverQuest client is authoritative for gameplay identity. Provider rows
(Allakhazam today, additional mirrors later) retain their own external IDs, source pages,
relationships and provenance. They are not destructively merged into the client entity.

`zone_provider_bindings` is a builder-owned derived catalog that states whether facts
attached to one provider zone may be projected into one canonical gameplay zone.

## Binding statuses

- `linked` — safe for runtime knowledge projection. The provider zone has one unique
  EQ-client target under the conservative name rules and independent structured provider
  topology corroboration.
- `candidate` — one unique EQ-client target exists under those rules, but there is not
  enough independent evidence to project provider facts automatically.
- `ambiguous` — more than one EQ-client-backed zone matches the allowed display-name
  forms.
- `unresolved` — no EQ-client-backed target matches the allowed display-name forms.

Only `linked` rows are consumed by player-facing projections.

A `linked` binding is **not** permission to merge or delete the provider entity. It means
only that the provider's facts are safe to view in the target gameplay-zone context.

## Conservative corroboration rule

The catalog deliberately does not treat display-name similarity as proof. Automatic
linking requires:

1. exactly one EQ-client-backed target through an allowed provider display-name form;
2. at least one structured provider `connected_to` relationship touching the provider
   zone; and
3. the neighboring provider zone on that relationship must independently resolve to
   exactly one EQ-client-backed target through the same conservative rules.

Allakhazam's structured **Connected Zones** table supplies this evidence today. The
binding stores the relationship ID, direction, source identity, provider/client match
kinds, and neighboring provider/gameplay IDs so the decision remains auditable after
packaging.

### Catalog v2 display-name forms

Catalog v2 keeps exact normalized names as the preferred case and recognizes only two
additional source-owned forms:

- **leading article variant** — for example Allakhazam `Greater Faydark` versus the
  EQ-client canonical display name `The Greater Faydark`;
- **terminal parenthetical canonical name** — for example Allakhazam
  `Ruins of Old Paineel (The Hole)` versus the EQ-client canonical display name
  `The Hole`.

The parenthetical rule accepts only the complete final parenthetical text. It does not
extract arbitrary substrings. Neither rule enables significant-word matching,
containment, stemming, or general fuzzy matching. If an allowed variant produces more
than one client-backed target, the binding remains `ambiguous`. If there is no
independent structured Connected Zones corroboration, the unique match remains only a
`candidate`.

These rules are **builder reconciliation evidence only**. They do not add runtime aliases
and they do not relax player-facing zone resolution.

## Why v2 is needed

A real finalized route-acceptance report exposed canonical source zones with zero
compiled outgoing travel edges even though provider topology was present. The travel
compiler correctly refuses any provider `connected_to` relationship whose source or
target cannot map through a projection-safe provider binding. Exact-name-only v1
therefore stranded source-backed topology when the provider and client used one of the
known display-name forms above.

V2 fixes that binding boundary rather than teaching the pathfinder to guess around it.
Once the provider endpoint is uniquely matched and topology-corroborated, the existing
provider-travel compiler can emit the same canonical, direction-preserving travel edge it
would have emitted for an exact-name binding.

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
