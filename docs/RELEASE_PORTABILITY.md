# Release portability and legacy map catalogs

EverQuestie's release snapshot must not contain builder-machine filesystem paths.
Current map catalog builds already persist portable source identities (`source_name` +
relative `source_key`) and synthetic `mapcatalog://` provenance paths.

Builder databases created before the portable map-catalog migration can still contain
rows that were later schema-backfilled with `source_name = 'legacy-local'` while
retaining absolute paths in `root`, `source_key`, and `path`.

During knowledge snapshot finalization EverQuestie now normalizes those historical
`legacy-local` rows **inside the copied snapshot only**:

- the original map-pack name is recovered from the legacy `root` basename;
- the portable source key is recovered relative to that root;
- the persisted map path becomes `mapcatalog://<source>/<relative-key>`;
- if a newer portable row already represents the same source file, that row wins and
  non-conflicting map labels are preserved before the legacy duplicate is removed.

Named sources are never guessed by this migration. A named source that still contains
absolute filesystem paths remains a release-blocking portability error.

The working builder database is never rewritten by this release migration. This lets a
release snapshot be taken safely from a long-lived catalog database without mutating
its local provenance or interfering with active builder/import tooling.

## Reviewed-input artifact gate

Snapshot finalization also verifies any recorded reviewed zone-alias/travel counters
against the curated provenance rows in the copied database. The normal Windows release
coordinator performs a second, read-only audit against the **finished immutable
snapshot** before route acceptance, tests, PyInstaller, manifest creation, or ZIP
packaging. This catches post-finalization corruption or accidental artifact substitution
at the same boundary that will actually be distributed.

Run the artifact audit directly with:

```powershell
python .\tools\audit_release_inputs.py .\dist\everquestie-knowledge.sqlite3 --require-release-inputs
```

Without `--require-release-inputs`, older snapshots that predate the retained counters
remain diagnostic-compatible. Publish mode requires both reviewed families to be
recorded, internally complete, and equal to the persisted curated evidence. The audit
opens SQLite in `mode=ro`; it never imports manifests, rebuilds topology, or modifies
the knowledge file.
