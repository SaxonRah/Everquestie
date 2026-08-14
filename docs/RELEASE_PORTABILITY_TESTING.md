# Reproducing the legacy map-path release check

After merging the legacy map portability migration, rerun the normal release command
against the existing builder database. A catalog created before portable map identities
were introduced should no longer fail merely because `legacy-local` map source rows
retain absolute Windows paths.

Example:

```powershell
.\tools\build_release.ps1 `
  -Version 2026.08.14-test `
  -WorkingDb "$HOME\.eqquest\eqquest.sqlite3" `
  -Force
```

A successful finalization should produce the immutable knowledge snapshot without
rewriting the builder database. Any absolute path remaining in a named/non-legacy map
source still fails the release portability audit and should be investigated rather than
auto-normalized.
