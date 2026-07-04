# sethu — working notes for Claude

sethu is a Claude Code plugin: a `UserPromptSubmit` hook (`hooks/sethu_hook.py` →
`hooks/_engine.py`) that runs terminal commands typed as `> cmd` / `>> cmd`, plus a
management CLI (`sethu --allow …`, `--mode …`, `--runner`). Pure stdlib, no deps.

## Checklist for any change
Run every change against `docs/design-guidelines.md` (the full checklist). In brief:
- [ ] **Tested** — add/adjust a test, update the coverage table (top of
  `tests/test_sethu.py`), suite + `TestCoverageEnforcement` green,
  `claude plugin validate .` passes.
- [ ] **Shared render/format function?** Verify the full input matrix + pin the exact
  output (see Testing discipline below).
- [ ] **UX** — branded unified header, colorblind-safe & no new hue, truthful,
  actionable, plain language, no em-dashes.
- [ ] **Correctness** — validates input, fails safe, no stale-state assumptions.
- [ ] **Security** — does it widen what runs? flags (not names) audited? fails
  closed? trust still opt-in?
- [ ] **Performance** — no new work on the every-prompt path (fast path skips
  `_engine`).
- [ ] **Storage** — output stays bounded; any new temp artifact is swept.

## Before committing
- Keep the suite green: `python3 -m unittest discover -s tests`
- `claude plugin validate .` passes.

## Testing discipline
- **Every feature and CLI argument has a test**, tracked in the coverage table at the
  top of `tests/test_sethu.py`, enforced by `TestCoverageEnforcement`. Add a row +
  test for anything new.
- **When you change a shared render/format function** — `_header`, `_msg`, `_reply`,
  the refusal/interactive/cd messages, the result header, config coercion, the temp
  sweep — **verify the FULL input matrix it handles, not just the case you're
  changing** (e.g. trust on/off × run/refusal × each mode), and **pin the exact
  output with an `assertEqual` format test** (see `TestHeaderFormat`). A
  spacing / separator / branding / coverage regression should fail in CI, not by eye.

## Design
Follow `docs/design-guidelines.md` (UX / correctness / security / performance /
storage, with a per-change checklist). In short: brand every response with the
unified header (`|^=^| · [mode] · [status ·] $ cmd`); colorblind-safe, lean palette
(differentiate by weight/separator, not new hues); color = sethu's interpretation,
plain = relayed command output; refusals teach the safest path; truthful feedback;
plain language, no em-dashes.

## Security-sensitive areas
Read-only is decided by **flags**, not just program names — audit the whole
`READONLY` set when touching it (`fd -x`, `rg --pre`, `yq -i` were misses). Keep the
allowlist injection-hardened; fail closed; trust stays opt-in.

## Testing a branch live in Claude Code
See `docs/testing.md` (local marketplace / `--plugin-dir`; nothing auto-updates, use
`/reload-plugins`).

## Gotchas & context worth knowing
- **Token model (the whole point):** `> cmd` returns `decision:block` → the model
  never sees it → **zero tokens** (output shown only to the user). `>> cmd` injects
  the output as `additionalContext` → **costs tokens**. Never hide the `>>` cost.
- **The "operation blocked by hook:" prefix and the amber tint are Claude Code's,
  not sethu's.** Claude Code frames any `decision:block` reason and tints its text
  amber; sethu's explicit header colors punch through, plain text shows amber. It's
  unavoidable (there's no mechanism to display output without a block). Documented in
  the README Troubleshooting FAQ — don't re-investigate.
- **Interactive / TUIs:** full-screen programs (vim, `claude`, lazygit…) can't run
  captured. Known ones are in `INTERACTIVE` (refused up front → `--launch`); unknown
  ones are caught after the fact by the alt-screen escape → a `--launch` hint.
  Terminal commands (e.g. `claude --plugin-dir`) must be run in a real shell, **not**
  via `>` (that captures them and garbles the TUI).
- **`!` bang mode always costs tokens** (feeds output to Claude); sethu's `>` is the
  free path. Don't recommend `!` as equivalent.

## Release / propagation
Bump `version` in `.claude-plugin/plugin.json`, commit + push, then refresh the
marketplace clone: `git -C ~/.claude/plugins/marketplaces/sethu pull origin main`.
Users get it via `/plugin marketplace update sethu` + `/plugin update sethu`. CI
`paths-ignore`s docs, so doc-only pushes skip tests.

## Branches & local docs (not on main)
`quiet` + `docs/token-thrifty.md` → branch `feature/quiet`; completions + `bin/sethu`
→ `archive/terminal-cli`. The bug-bash findings/plan live in local, gitignored
`BUG-BASH-*.md`.

## Commits
End commit messages with:
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
