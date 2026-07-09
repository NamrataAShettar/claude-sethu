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

### Test plan

<!-- Enumerate the scenarios this change can produce, and mark whether each is covered
and how: `unit` (name the test that was added/updated), `manual` (verified by hand, per
docs/testing.md), or `n/a`. Be honest about anything NOT covered (a real terminal, macOS,
a live Claude Code session). This is the honest map of "what could happen and did we
check it", beyond just "tests pass". -->

| Scenario | Covered? | How |
| --- | --- | --- |
| happy path | ✅ | unit: `test_...` |
| edge / failure case | ✅ | unit: `test_...` |
| can't be unit-tested (real terminal / macOS / live) | 🖐 or n/a | manual, per docs/testing.md |


## Checklist

- [ ] PR title is a Conventional Commit (`fix:` / `feat:` / `docs:` / `chore:` / …)
- [ ] Tests added or updated; `python3 -m unittest discover -s tests` passes
- [ ] Test plan above is filled in (scenarios enumerated; anything not covered is called out)
- [ ] Security: does this change what auto-runs, or widen the gate / allowlist? If so, it's been audited.
- [ ] `docs/use-cases.md` still accurate if gating / permissions changed
- [ ] `CLAUDE.md` code-map updated if a function, section, or file moved
- [ ] Checked against `docs/design-guidelines.md`
