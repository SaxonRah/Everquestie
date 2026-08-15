# Travel frontier audit

EverQuestie compiles only conservative, explicit map-label travel evidence into canonical `zone_travel_edges`. The travel frontier audit measures what is already usable and what stored map evidence sits just outside the current compiler boundary.

Run it against a builder database or finalized knowledge snapshot:

```powershell
python tools\audit_travel_frontier.py <everquestie-knowledge-db>
```

Use `--json` for machine-readable output and `--examples N` to control how many frontier examples are printed.

The audit is read-only. It does not scan Good's/Brewall folders, mirrors, EverQuest runtime files, or mutate SQLite.

It reports:

- current explicit travel labels already understood by the compiler, including `ZL`, `Zone Line`, `Portal`, `Teleport`, `Teleporter`, `Exit`, `Entrance`, and `To` forms;
- current candidates whose stored `zone_travel_edges` row is missing or stale;
- additional explicit spellings still outside the production parser, currently narrow forms such as `Connection to <zone>` and `Boundary to <zone>`;
- whether those frontier destinations currently resolve to a unique canonical zone;
- bare labels that exactly name another canonical zone, kept audit-only because a bare zone name may be a landmark rather than an exit;
- source and unresolved-destination breakdowns plus representative examples.

When a spelling graduates into the production compiler it must be removed from the audit-only frontier patterns. The audit should describe backlog, not double-count supported routes.

The audit intentionally does not promote frontier evidence into routes. Parser expansion should be driven by real-corpus results and preserve EverQuestie's rule that ambiguous or weak evidence is not guessed.
