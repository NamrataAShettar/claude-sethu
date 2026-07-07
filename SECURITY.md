# Security policy

sethu runs terminal commands you type into the Claude Code prompt (`> cmd` / `>> cmd`),
so its security posture matters. This page covers how to report a vulnerability and the
boundaries of sethu's own model.

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.** Use GitHub's private
reporting instead:

- Go to the repository's **Security** tab → **Report a vulnerability** (GitHub Private
  Vulnerability Reporting), which opens a private advisory only maintainers can see.

Include what you'd expect: affected version, a description, reproduction steps, and impact.
You'll get an acknowledgement, and a fix or mitigation will be coordinated before any
public disclosure.

## Scope

In scope (please report):

- A way to make sethu **auto-run** something it shouldn't without `--allow` / `--trust`
  (e.g. bypassing the gate or the chain guard so an unallowlisted or chained command runs
  from a plain `> cmd`).
- Injection past the allowlist (an allowlisted tool being coerced into running something
  else).
- A way for **command output or repo contents to be treated as instructions** by the
  model via `>>`.
- Local privilege / file issues in sethu's own artifacts (config, temp files, the
  shell-mode socket).

Out of scope (by design, documented in the README's Safety section):

- The user (or Claude, with the user's approval) running a dangerous command **they
  explicitly allowed** via `--allow` or `--trust`. Gating is a guardrail against
  surprises, not a sandbox — the user can always run anything via their own terminal.
- `git` executing programs named in a repo's own config once `git` is `--allow`-ed (that
  is git's behavior, the same as in a normal terminal).

## Supported versions

sethu is distributed through a Claude Code marketplace and moves forward only. Fixes ship
in a new release; there are no back-ported patches to old versions. Please update
(`/plugin marketplace update sethu` + `/plugin update sethu`) before reporting, in case
the issue is already fixed on the latest release.
