# sethu — working notes for Claude

sethu is a Claude Code plugin: a `UserPromptSubmit` hook (`hooks/sethu_hook.py` →
`hooks/_engine.py`) that runs terminal commands typed as `> cmd` / `>> cmd`, plus a
management CLI (`sethu --allow …`, `--mode …`, `--runner`). Pure stdlib, no deps.

## Code map
(By module and function/section, not line numbers, so it survives edits. `_engine.py`
is banner-commented — `# ── <section> ──` — grep those to jump.)

- **`hooks/sethu_hook.py`** — the `UserPromptSubmit` entry. Cheap fast-path gate
  (`_maybe_sethu`, decides with `json`/`os` only, does NOT import `_engine` for a
  normal prompt); routes a sethu prompt to `process()`; runs `sethu …` management
  commands as a subprocess; `_block` emits the zero-token `decision:block`.
- **`hooks/_engine.py`** — the core, in banner sections:
  - *config* — `DEFAULTS`, `load_config` (type + value coercion, whitespace-canonicalizes
    allow/launch), `save_config` (atomic via `_atomic_write`: temp+fsync+os.replace, so a
    crash can't torn/truncate it — `set_cwd` uses it too), `_config_lock` (fcntl.flock
    serializing the CLI's read-modify-write so concurrent writers don't lose updates),
    `config_path`.
  - *allow / launch matching* — `_matches` (exact/prefix), `_is_chain_unsafe` /
    `_has_unquoted_ops` / `_SUBST_META` (the injection-hardened chain guard).
  - *per-session cwd (cwd mode)* — `is_cd`, `resolve_cd`, `set_cwd`/`get_cwd` (atomic).
  - *command execution* — gated decision (`is_gated`, `GATED` (flag-safe tool set,
    no flag logic), `_DANGER`, `_pipe_segments` (quote-aware `|` split, so a pipe inside
    a quoted arg like `jq '.a | .b'` isn't mistaken for a chain), `_LAUNCHERS`,
    `_why_refused`, `gated_list_text`);
    interactive/TUI detection (`is_interactive`, `_REPL`,
    `_REPL_BATCH_FLAGS`, `INTERACTIVE`, `_looks_full_screen`); `run_capture` (the
    captured runner — streams via Popen, byte-capped at `MAX_CAPTURE_BYTES`, kills a
    runaway); truncation + temp hygiene (`_truncate`, `_out_path`, `_sweep_temp`,
    `_output_path`); `launch_in_terminal` + `_launch_command_script`.
  - *persistent shell (shell mode)* — `shell_run`, `_sock_path`, `_spawn_daemon`
    (+ `_acquire_spawn_lock`/`_release_spawn_lock`, the L7 spawn guard), `kill_daemons`,
    `_timeout_msg` (talks to `_shelld.py`).
  - *the core: process one submitted prompt* — `process()` (the one entry that returns
    `{passthrough|block|context}`), plus the header/color helpers `_header`, `_reply`,
    `_msg`, `_c`, `_color_on`, `_plain_on` (plain/spoken mode: `sethu:` prefix + words,
    no `|^=^|`/glyphs — threaded as a `plain` arg through the render helpers),
    `_style_cli` (the hook colors/plain-swaps the management CLI's captured stdout;
    HELP/`help_text` embed NO lead so `_lead` supplies the colored icon), `_ANSI`, `ICON`.
  - *management CLI* — `main` (wraps the read-modify-write in `_config_lock`),
    `_apply_cli_mutations` (the per-flag config mutations, run under the lock;
    `_announce_launch` opens a terminal AFTER the lock), `normalize_argv`
    (subcommand→flag aliasing), `_Parser` (branded errors), `help_text`, `_print_config`.
- **`hooks/_shelld.py`** — the persistent-shell daemon (PTY + unix-socket server) that
  backs shell mode; wire protocol version `_PROTO`. On a command timeout it verifies the
  shell recovered (`_probe`/`_recover`: Ctrl-C → SIGKILL the foreground pgrp → respawn on
  a wedge, H3) and byte-caps output (`MAX_OUTPUT`, ST7).
- **`hooks/session_start.py`** — SessionStart hook (first-run welcome).
- **`hooks/run.sh`** — POSIX-sh launcher: exec `python3`, or degrade gracefully when it's
  missing (the tolerant no-python3 block shim).
- **`hooks/hooks.json`** — hook registration. **`.claude-plugin/`** — `plugin.json`
  (version lives here), `marketplace.json`.
- **`tests/test_sethu.py`** — the whole suite + the coverage table and
  `TestCoverageEnforcement` (top of file). **`docs/`** — design-guidelines, testing,
  use-cases.

**Keep this map (and this file) current.** When a change adds, renames, moves, or
removes a module, a top-level function, or an `_engine.py` section — or changes a
workflow/gotcha noted below — update `CLAUDE.md` in the SAME change so it never drifts
from the code. A stale map is worse than none.

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
- **Update this file in the same change** when you move code (see the Code map note) or
  change a workflow/gotcha/release step documented here — don't let `CLAUDE.md` drift.

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
