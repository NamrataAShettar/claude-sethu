# sethu — working notes for Claude

sethu is a Claude Code plugin: a `UserPromptSubmit` hook (`hooks/sethu_hook.py` →
`hooks/_engine.py`) that runs terminal commands typed as `> cmd` / `>> cmd`, plus a
management CLI (`sethu --allow …`, `--mode …`, `--runner`). Pure stdlib, no deps.

## Before any change
- **Run it against the checklist in [`docs/design-guidelines.md`](docs/design-guidelines.md)**
  (UX / correctness / security / performance / storage). That doc is the single
  source of the principles — don't re-derive or duplicate them here.
- **Changing a shared render/format function?** (`_header`, `_msg`, `_reply`, the
  refusal/cd/interactive messages, the result header, config coercion, the temp
  sweep) — verify the **full input matrix** it handles (e.g. trust on/off × run /
  refusal × each mode), **not just the case you're changing**, and **pin the exact
  output with an `assertEqual` format test** (see `TestHeaderFormat`). A spacing /
  separator / branding regression should fail in CI, not by eye.
- Keep the suite green (`python3 -m unittest discover -s tests`) and
  `claude plugin validate .` passing. Every feature/arg needs a test + a coverage
  row (`TestCoverageEnforcement` enforces it).

## Gotchas & context
- **Token model (the point):** `> cmd` → `decision:block` → the model never sees it →
  zero tokens; `>> cmd` → `additionalContext` → costs tokens. Never hide the cost.
- **The "operation blocked by hook:" prefix and the amber tint are Claude Code's**,
  not sethu's — it frames/tints any block reason; sethu's header colors punch
  through, plain text shows amber. Unavoidable (see the README Troubleshooting FAQ) —
  don't re-investigate.
- **Interactive / TUIs** (vim, `claude`, lazygit) can't run captured — the
  `INTERACTIVE` list refuses known ones, the alt-screen escape catches unknown ones.
  Run `claude --plugin-dir` etc. in a real shell, **not** via `>`.
- **`!` bang mode always costs tokens**; `>` is the free path.
- **Test a branch live:** [`docs/testing.md`](docs/testing.md) (nothing auto-updates;
  use `/reload-plugins`).

## Release
Bump `version` in `.claude-plugin/plugin.json`, push, then refresh the marketplace
clone (`git -C ~/.claude/plugins/marketplaces/sethu pull origin main`). Users update
via `/plugin marketplace update sethu` + `/plugin update sethu`. CI `paths-ignore`s
docs, so doc-only pushes skip tests.

## Commits
End commit messages with:
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
