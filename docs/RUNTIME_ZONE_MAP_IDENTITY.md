# Runtime live-zone map identity

EverQuestie's canonical zone graph remains conservative: if multiple distinct zone
entities own the same identity token, builder reconciliation and knowledge audits keep
that token ambiguous instead of silently merging the entities.

The Map tab has a narrower runtime question: given a zone name observed in the live
EverQuest log, which local map geometry may safely be rendered?

Runtime map lookup therefore applies two additional evidence rules without modifying
canonical knowledge:

1. A literal canonical zone name outranks another entity that exposes the same token
   only as an alias, short name, or map stem.
2. When several entities literally share the same zone name and exactly one is backed
   by an `eqclient:zone` identity, the EQ-client-backed entity is preferred for that
   live log token. The observed zone name itself came from the client, so this is
   stronger runtime evidence than a provider-only duplicate.

If several EQ-client identities genuinely share the same literal display name, the
knowledge identity remains ambiguous. The Map tab may nevertheless render one local
map geometry only when all ambiguous candidates share that exact canonical display
name and the local geometry is uniquely determined. If Good's and Brewall both provide
that same geometry, normal local-map variant selection remains required.

Alias ambiguity is never broken by a local filename. For example, if `Freeport` or
`qeynos` names several distinct canonical zones only through aliases, EverQuestie still
refuses to guess.

These rules are read-only runtime projections. They do not merge zone entities, rewrite
the packaged knowledge snapshot, rebuild the map catalog, or weaken builder identity
audits.
