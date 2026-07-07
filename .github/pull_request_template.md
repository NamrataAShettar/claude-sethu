<!--
Title this PR as a Conventional Commit. It becomes the squash-merge commit, and
release-please reads it to pick the next version. The `pr-title` check enforces it.

  fix: <what>    -> patch    (a bug a user would notice)
  feat: <what>   -> minor    (a new capability a user can use)
  feat!: <what>  -> breaking (minor while pre-1.0; explain the break below)
  docs: / chore: / test: / refactor: / ci:  -> no release

Full guide: docs/versioning.md
-->

## What and why

<!-- Closes #<issue> if this resolves one. -->


## How verified

<!-- Automated tests, plus any live-testing per docs/testing.md — the suite does NOT
cover --launch, shell mode, or macOS, so note manual verification for those. -->


## Checklist

- [ ] PR title is a Conventional Commit (`fix:` / `feat:` / `docs:` / `chore:` / …)
- [ ] Tests added or updated; `python3 -m unittest discover -s tests` passes
- [ ] Security: does this change what auto-runs, or widen the gate / allowlist? If so, it's been audited.
- [ ] `docs/use-cases.md` still accurate if gating / permissions changed
- [ ] `CLAUDE.md` code-map updated if a function, section, or file moved
- [ ] Checked against `docs/design-guidelines.md`
