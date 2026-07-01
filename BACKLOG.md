# sethu — decisions to make later

Open design questions parked for a decision, not yet committed to. Each has the
problem, the options, and a leaning where there is one. Nothing here is built.

## 1. `--launch` is still a confusing name

`launch` reads like "do it now", and it now does open immediately — but it also
*registers* the command so future `> cmd` opens a pane. The dual nature (action +
config) is the root of the confusion reported twice.

- **Option A — rename to `--open`** (`sethu --open vi`, `> vi` → opens). Verb is
  clearer; keep `--launch` as a hidden alias for back-compat.
- **Option B — split the concepts**: a one-off open vs. a persistent "always open
  this in a pane" registration (see #2).
- **Option C — leave it**; the improved messages may be enough.
- _Leaning:_ A, low-risk and clearer.

## 2. One-off open vs. permanent registration

`sethu --launch "git log"` opens it now **and** permanently registers it, so
`> git log` opens a pane forever after. Sometimes you want a single scrollable
view without changing future behaviour.

- **Option A** — a transient open that does **not** register (e.g. `> ^git log`
  or `sethu --open-once "git log"`).
- **Option B** — keep registration as the only mode; `--unlaunch` to undo.
- _Open:_ which is the common case — browse once, or "this command is always a
  pager command"?

## 3. Scrollable output / a `--pager` convenience

`> git log` dumps inline (no TTY → no `less`). Real scrolling needs a real
terminal (today: launch it). Came up directly as "how to keep git log
scrollable".

- **Option A** — `sethu --pager "git log"` sugar that registers the usual
  scroll-heavy commands (`git log`, `git diff`, `git show`) into the launch list
  in one go.
- **Option B** — document the launch workflow and stop there (current state).
- _Note:_ inline scrollability is impossible — a plugin can't inject a pager into
  Claude Code's TUI; output is static transcript text. Real pager == real
  terminal == launch. This is a hard limit, not a TODO.

## 4. Drop the pre-register step for interactive commands

Today `> vi` (interactive, not in launch list) is *refused* with "run
`sethu --launch vi`". Could instead just open it directly — no registration
needed — since a launched command is visible in a pane the user drives.

- **Pro:** removes a whole step; `> vi` just works.
- **Con:** slightly weakens the "nothing auto-runs" guarantee (though only for
  interactive programs, and they run in a visible pane, not silently).
- _Open:_ worth deciding alongside #1/#2.

## 5. macOS Automation permission friction

Driving iTerm/Terminal via AppleScript triggers a one-time "Claude Code wants to
control iTerm2" prompt. If denied, we fall back to a `.command` window. Fine, but
undocumented in the README beyond a mention. Decide whether to add a short
"first launch asks for Automation permission" note to the README.

## 6. Linux GUI launch is unimplemented

`launch_in_terminal` handles tmux + macOS only. On Linux outside tmux it returns
"couldn't open". Decide whether to support `$TERMINAL`/`x-terminal-emulator` /
common emulators, or leave Linux as tmux-only.

## 7. Queued `> cmd` is consumed by the model (hook limitation)

If you type `> cmd` while Claude is mid-turn, Claude Code QUEUES it and folds it
into the running turn as more input — it does NOT re-submit it as a fresh prompt,
so the `UserPromptSubmit` hook never fires and the model interprets it instead
(observed live: a queued `>whoami` / `>cat ...` reached the model). This is a
harness limitation a plugin can't fix — hooks only fire on turn-starting prompts.

Key fact: once queued, the input is already in context — its tokens are spent no
matter what; nothing can reclaim them. The only truly token-free paths are
running `> cmd` when sethu is idle, or using a launched pane (a real shell that
never routes through the model).

- **Option A** — make the model recognize a stray leading `>` as "meant for
  sethu, not me": don't act on it, just remind the user to re-run it now that
  sethu's idle. Avoids misinterpretation; costs a negligible reminder. (This is a
  CLAUDE.md / behavior instruction, not plugin code — the hook can't see it.)
- **Option B** — document the launched-pane workflow (`sethu --launch zsh` → a
  persistent iTerm pane, independent of Claude's turns) as THE way to use a shell
  while Claude is busy, and otherwise leave queued lines alone.
- **Option C** — both.
- _Leaning:_ B is the real answer (a launched pane is genuinely independent and
  token-free); A is a nice-to-have guard. Lean B, optionally + A.

## 8. Refusals have no colored header / exit code

A refused command ("`cat ech` isn't allowed", interactive guard, launch-couldn't-
open) prints as plain text — no `[mode]` tag, no red, no exit code (nothing ran,
so there's no status). User expected the refusal to read as red/error. Decide
whether to give refusals a header like `[cwd] ✗ refused · $ <cmd>` in red (with a
glyph cue), so they visually match real failures. Started, not shipped.

## 10. Interactive confirmation prompts can't be answered (fundamental)

Commands that pause to ask a question (`npm install` conflict resolution, `apt
install` "[Y/n]", `pip`, `brew`, `gh auth login`, git credential prompts) can't
be answered — the captured runner has no interactive terminal, and even `shell`
mode (which persists state) can't *type back* at a prompt. Documented in the
README with workarounds (non-interactive flags like `-y`/`--yes`/`DEBIAN_FRONTEND
=noninteractive`, or `--launch` into a real terminal). Possible future ideas, if
worth it: (a) detect a likely-interactive installer and pre-suggest the `-y`
form / `--launch`; (b) a way to send a canned answer (e.g. `yes |` prefix
support, though `|` is currently blocked outside readonly). Low priority — the
`-y` flags and `--launch` cover it. Noting so it's a known limitation, not a bug.

## 14. `sethu --console` — a launched pane that shares sethu's config

Today `sethu --launch <shell>` opens a PLAIN shell — no allowlist, no mode, no
cwd sharing, no guardrails (now warned in the README + launch message). It's an
escape out of sethu. Idea: `sethu --console` opens a launched pane running a
small sethu REPL that applies the SAME config (allowlist/readonly/mode/truncation
/`|^=^|` header) and, ideally, the session's cwd — a persistent sethu surface
that runs **in parallel** with Claude's work (the only genuine parallelism path,
since the in-box hook can't fire mid-turn — see #7). Also relevant to the
"execute queued `> cmd`" discussion: a console is the clean answer to "run sethu
stuff while Claude is busy." Design open: how the REPL shares/reloads config,
whether it tracks the Claude session cwd. Medium interest.

## 15. Rescue queued `> cmd` that reaches the model (from #7 discussion)

When a `> cmd` is typed while Claude is working, it's folded into the running
turn and only the MODEL sees it (no hook fires — see #7). Option: a `sethu --run
"<cmd>"` subcommand (runs through the same allowlist/mode/safety and prints the
result) + a CLAUDE.md snippet telling Claude "if a user message is only a `> …`
command, execute it via `sethu --run` instead of interpreting it." Effect: a
queued command executes through sethu's safety model instead of being misread.
Tradeoff (be explicit): NOT free (it's already in context) and NOT parallel — it
runs as part of Claude's turn via the Bash tool. Solves "don't waste/​misread my
queued command," not "run it free while Claude works" (that's #14). Parked.

## 13. `sethu …` management path forks a second python (perf, rare path)

Benchmark (v0.8.2, 40 iters, median): non-sethu prompt **28.0ms** (baseline bare
python3 = 27.5ms — i.e. sethu adds ~0.5ms, effectively free ✅); `> echo hi`
**39.2ms**; `sethu --runner` **71.2ms**. The management CLI is the outlier because
`sethu_hook.py` shells out to a SECOND python (`subprocess.run([python, _engine.py,
…])`) instead of calling the CLI in-process. Fix idea: import and call
`_engine.main(argv)` in-process (capturing stdout) rather than forking — roughly
halves the `sethu …` latency (~71ms → ~40ms). Low priority: `sethu …` is a rare,
human-initiated management action, not the hot path. The every-prompt path is
already ~free. Parked to revisit if the mgmt latency ever feels sluggish.

## 11. Idle shell-daemon memory & orphan reaping (perf audit)

Each `shell`-mode session spawns a persistent bash + python daemon (~7–14MB, 2
procs, a PTY fd, a listening socket) that lingers up to `IDLE_TIMEOUT` = 30 min
after last use. Across many short sessions these accumulate (audit saw daemons
from different plugin versions coexisting). The v0.8.0 `kill_daemons` fix reaps
them on `--restart`/`--mode`/`--rc`/`--timeout`, but nothing reaps on session
end. Options (each a tradeoff, so parked): (a) lower `IDLE_TIMEOUT` to ~10 min —
less lingering memory, but a returning user loses their venv/cd state sooner;
(b) wire a **SessionEnd hook** that calls `kill_daemons()` (or kills just this
session's socket) — the correct fix, promptly reaps, but adds a hook. Lean (b).
Only affects shell mode; cwd/stateless have zero daemon cost.

## 12. Unbounded output capture for a single command (perf audit)

`run_capture` uses `subprocess.run(capture_output=True)`, buffering ALL of a
command's stdout/stderr in memory before truncation runs — so `> cat hugefile`
or `> find /` can transiently hold hundreds of MB even though only `maxLines` are
shown. (`_truncate` was fixed in the perf pass to not also copy every line.)
Fix idea: read from the child with a byte cap (e.g. stop at ~1–2 MB, mark
truncated) instead of unbounded capture. Tradeoff: `>>` can't pipe output it
didn't capture — but it's truncating to `maxLines` anyway, so acceptable. Parked
because it needs switching run_capture from `subprocess.run` to a manual Popen
read loop (more code, more timeout/interrupt handling). Medium priority.

## 9. Mid-session logout (NOT a sethu issue — investigate separately)

User got logged out of Claude Code mid-session, `/login` fixed it instantly.
Neither sethu nor yodha touches auth, so ruled out. Most likely a routine OAuth
token-refresh hiccup (or a second device invalidating the token). Parked: if it
recurs, ask the claude-code-guide agent what triggers re-auth and how to make the
session stickier. Not a plugin change.

---

## Standing offers (separate from the above)

- Make both repos (`claude-sethu`, `claude-yodha`) **public**.
- **Tag releases** (currently only version bumps in `plugin.json`).
- Give **yodha** the same polish sethu has: tests, CI, a richer use-cases README.
- **yodha v2**: an interactive TUI rather than a status-line-only HUD.
