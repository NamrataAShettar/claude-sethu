# Versioning and how to title your PR

sethu's version number is bumped **automatically** by
[release-please](https://github.com/googleapis/release-please). You never edit
`version` in `.claude-plugin/plugin.json` by hand. Instead, the **title of your PR**
decides the next version, so this doc explains what the number means and how to title
a PR so the right thing happens.

## TL;DR

- We **squash-merge**, so your **PR title becomes the commit message** on `main`.
- Title it with a [Conventional Commit](https://www.conventionalcommits.org) prefix:
  `fix:`, `feat:`, `docs:`, `chore:`, etc. (table below). A `pr-title` CI check
  enforces this.
- release-please reads those titles, opens a "release" PR that bumps the version and
  updates `CHANGELOG.md`, and a maintainer merges it to cut the release.
- You do **not** touch the version file. If you do, release-please will fight you.

## What the version number means

sethu follows [Semantic Versioning](https://semver.org): `MAJOR.MINOR.PATCH`. The
position that changes tells a user how risky it is to update:

| Position | Bumps when you… | Signals to the user |
| --- | --- | --- |
| **PATCH** (`x.y.Z`) | fix a bug | safe to update, nothing new to learn, nothing breaks |
| **MINOR** (`x.Y.z`) | add a feature | safe to update, and there is new stuff you can use |
| **MAJOR** (`X.y.z`) | break compatibility | updating may break how you use it today |

The bump size is the **blast radius** of the change. That is the whole point of the
number: someone can look at it and decide whether updating is risky, without reading
the diff.

### Pre-1.0 (where we are now)

While sethu is `0.x`, SemVer treats everything as "still stabilizing", and cutting
`1.0.0` is a deliberate promise of stability we are not making yet. So the config sets
`bump-minor-pre-major: true`, which shifts breaking changes down one rung:

- a **breaking** change bumps the **minor** (`0.11.x` to `0.12.0`), not `1.0.0`
- `feat:` and `fix:` behave normally (minor / patch)

When sethu is ready to promise stability, we cut `1.0.0` on purpose; after that,
breaking changes bump the major.

## How to title your PR

The prefix before the colon is what release-please reads:

| PR title prefix | Example | Version effect |
| --- | --- | --- |
| `fix:` | `fix: quoted pipe in is_gated was refused` | patch (`0.11.6` to `0.11.7`) |
| `feat:` | `feat: add --json output to --runner` | minor (`0.11.6` to `0.12.0`) |
| `feat!:` or a `BREAKING CHANGE:` footer | `feat!: drop the readonly config key` | minor while pre-1.0 (major after 1.0) |
| `docs:` | `docs: clarify shell mode` | no release |
| `chore:` | `chore: bump CI action version` | no release |
| `test:` | `test: cover the timeout path` | no release |
| `refactor:` | `refactor: extract _pipe_segments` | no release |
| `ci:` | `ci: cache pip` | no release |

Notes:

- An optional **scope** goes in parentheses: `fix(shell): …`, `feat(cli): …`. It shows
  up in the changelog but does not change the bump.
- Mark a **breaking change** with a `!` before the colon (`feat!:`) or a
  `BREAKING CHANGE:` line in the PR body. Explain what breaks and how to migrate.
- Keep the title in the **imperative mood** and lower-case after the prefix, like a
  good commit message: "fix: refuse chained cd", not "fix: Refused chained cd".

## What actually triggers a release

1. You merge normal PRs (`fix:` / `feat:` / …) to `main`.
2. release-please keeps a standing **"chore(main): release x.y.z"** PR up to date with
   the accumulated version bump and changelog.
3. A maintainer **merges that release PR**. That is what bumps
   `.claude-plugin/plugin.json`, tags `vX.Y.Z`, and cuts a GitHub release.
4. Refresh the marketplace clone
   (`git -C ~/.claude/plugins/marketplaces/sethu pull origin main`); users update via
   `/plugin marketplace update sethu` + `/plugin update sethu`.

So no single PR "does a release" on its own; releases are cut deliberately by merging
the release PR.

## How a release reaches users

sethu ships through a **Claude Code marketplace**, not a package registry, so nothing
auto-updates on a user's machine. The path from merge to a user running the new code:

1. **You merge the release PR.** release-please bumps `plugin.json`, commits, tags
   `vX.Y.Z`, and publishes a GitHub Release with the changelog.
2. **The marketplace source is `main` of this repo.** A user's Claude Code has a local
   clone of it under `~/.claude/plugins/marketplaces/…`.
3. **The user pulls the update on their own schedule**, from inside Claude Code:
   - `/plugin marketplace update sethu` refreshes their local clone (sees the new
     version), then
   - `/plugin update sethu` installs it, and
   - `/reload-plugins` (or restarting the session) loads the new hook code.
4. Until they run those, they keep running whatever version they installed. There is
   **no forced upgrade and no telemetry back to us**; a release simply makes the new
   version *available*.

Practical implications:

- **Ship small, correct changes.** A user may jump several versions at once, so each
  release must stand on its own; `CHANGELOG.md` is how they see what changed.
- **Never break the config format without a fallback.** A user updating from an old
  version keeps their existing `~/.claude/sethu.json`; new keys must default sanely and
  old keys must not crash (see the "fail safe on bad input" guideline).
- **The tag and GitHub Release are the durable record**; the changelog entry is what a
  user reads before deciding to update.

## What happens if my title has no known prefix?

The `pr-title` CI check
([`amannn/action-semantic-pull-request`](https://github.com/amannn/action-semantic-pull-request),
in `.github/workflows/pr-title.yml`) **fails the PR** when the title is not a valid
Conventional Commit, so this is caught before merge. If it were not caught,
release-please would **silently ignore** the commit: no version bump and no changelog
entry, so a genuine user-facing change could ship **unversioned and unlogged**.

So: always pick the closest prefix. When unsure:

- fixed a user-visible bug → `fix:`
- added a capability a user can invoke → `feat:`
- internal only (refactor, tests, CI, docs) → `chore:` / `refactor:` / `test:` /
  `ci:` / `docs:`

If the `pr-title` check is red, edit the PR title to add a valid prefix and it re-runs.
