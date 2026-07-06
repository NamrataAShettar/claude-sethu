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



## Checklist

- [ ] PR title is a Conventional Commit (`fix:` / `feat:` / `docs:` / `chore:` / …)
- [ ] Tests added or updated; `python3 -m unittest discover -s tests` passes
- [ ] `docs/use-cases.md` still accurate if gating / permissions changed
- [ ] Checked against `docs/design-guidelines.md`
