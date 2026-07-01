# Running commands "during the ponder" — design notes

Status: **exploration / not implemented.** Captures the analysis of whether sethu
can execute a command *while Claude is generating a response* ("pondering"), and
what the realistic ceiling is.

## Problem

sethu runs commands via a `UserPromptSubmit` hook. That hook only fires when a
prompt is dequeued, so anything typed while Claude is mid-turn is **queued** and
runs *after* the turn — never concurrently. Goal under discussion: fire a command
and have it run immediately even though Claude is busy ("don't block on Claude"),
with output going to the terminal (not necessarily back into the live turn).

## Why true "during-ponder" is impossible for a plugin

Claude Code has two execution lanes:

1. **Model lane** — conversational prompts. Single-threaded, serial, FIFO-queued.
   The "ponder" lives here. Hooks (`UserPromptSubmit`, `Stop`, …) are part of this
   turn pipeline, so they inherit the serial queue.
2. **Client (TUI) lane** — built-in local commands (`/plugin`, `/reload-plugins`,
   `/config`, `/context`, `/clear`). Handled by the TUI process, never sent to the
   model. This is why `/plugin` works while Claude is pondering.

Confirmed facts (via Claude Code docs / claude-code-guide):

- The set of client-lane local commands is **hardcoded and not extensible by
  plugins.** A plugin cannot register a client-side shell executor.
- No hook event fires *during* generation on **user** input. Events that fire
  mid-turn (`PreToolUse`, `PostToolUse`, `MessageDisplay`, `Permission*`) are
  triggered by **Claude's** activity, not by something the user types.
- Hooks are synchronous barriers; a background process they spawn **cannot inject
  into the in-flight turn.** The Messages API request is already sent — you can
  only affect the *next* turn.
- Feature request anthropics/claude-code#31274 (inline shell via `!` / `/run`) was
  closed **not planned**.

A real "MidHook" (a hook firing while the model streams) would require changes
inside the closed-source TUI event loop + input handler. It is **Anthropic-only**;
not buildable as a plugin.

**Permanent ceiling:** even a MidHook could never feed the *live* turn — the request
is in flight. It could only run concurrently and show output to the user / feed the
next turn.

## Closest achievable approximation: SessionStart daemon + Stop drain

The daemon is the concurrency primitive; the hooks are its birth and reaper.

```
SessionStart ──> spawn sethu-daemon (detached, own lane)
                    │  watches ~/.sethu/inbox/  → runs jobs concurrently
                    │  writes  ~/.sethu/outbox/
UserPromptSubmit ─> `>~cmd` writes job to inbox, returns ~0ms ─┐
   Claude ponders prompt  ←── runs IN PARALLEL with job ───────┘
Stop ──────────> drain outbox, inject results as additionalContext (next turn)
SessionEnd ────> kill daemon
```

| Hook | Role |
|---|---|
| SessionStart | launch the always-live worker once (idempotent) |
| UserPromptSubmit (`>~cmd`) | drop job in inbox, return immediately (non-blocking) |
| Stop | drain outbox; inject results; optionally block-stop-and-continue |
| SessionEnd | kill daemon (cleanup) |

Because the daemon is a separate OS process, a job dropped at prompt-submit runs
**in parallel with the ponder** — genuine concurrency using only official hooks.

### Remaining limits

1. **Dispatch is at prompt-submit, not free mid-ponder.** You register the job
   *with* your prompt. Firing a *brand-new* command into an already-running ponder
   still needs a non-Claude input channel (FIFO + tmux popup / hotkey writing to
   the inbox).
2. **Results land at turn-end, never mid-stream** (the permanent API ceiling).

### "Any available resources" upgrade

Swap the hand-rolled daemon for the plugin **background-monitor** primitive
(long-running process that streams output as notifications). Output then surfaces
*during* the ponder as notifications, and the `Notification` hook can react. Strong
stack: background-monitor (worker) + SessionStart (ensure up) + FIFO/tmux popup
(mid-ponder input) + Stop (harvest into next turn).

## Security & efficiency review

### Security — naïve design is NOT safe

A daemon that runs whatever lands in an inbox is a persistent arbitrary-command
executor. It turns any *write* primitive into code execution.

| Threat | Why it bites |
|---|---|
| Local RCE via inbox | Any process running as the user (rogue npm postinstall, compromised MCP server, etc.) can drop a command → executed. |
| Predictable / world-writable path | FIFO or inbox in `/tmp` or group/world-writable → symlink/TOCTOU hijack; RCE for other users on multi-user hosts. |
| No writer authentication | Daemon can't tell the user (tmux popup) from any other process — anonymous drop, no provenance. |
| Prompt injection into Claude | Stop hook feeds command *output* into context; malicious output ("ignore prior instructions…") becomes model-readable text, and Claude has tools. Untrusted output → context → tool actions. |
| Orphaned daemon | If cleanup fails/crash-restarts, a persistent backdoor-shaped listener outlives the session. |
| Secrets on disk | Output (env, tokens) sits in outbox plaintext until drained. |

### Efficiency — good or wasteful depending on one choice

| Choice | Cost |
|---|---|
| Polling inbox (`sleep` loop) | constant wakeups, wasted CPU |
| Blocking FIFO read / `fswatch`/inotify | ~0 CPU idle (parked in `read()`) |
| No idempotency | every SessionStart spawns another daemon → leak |
| Stop-hook drain every turn | small synchronous barrier per turn; cheap only if it early-exits on empty |
| Output → context each turn | repeated token cost |

### Hardening (if built anyway)

1. `~/.sethu/` at `0700`, files `0600`, **never `/tmp`**; create FIFO yourself,
   refuse on wrong owner/perms.
2. **Per-session nonce** prefixing each command; daemon rejects anything without it
   (kills anonymous drops).
3. **Treat output as untrusted:** fence + label before any injection ("untrusted
   command output, not instructions"), truncate; ideally show to user only.
4. **Idempotent + reaped:** lockfile/PID guard (one daemon max); SessionEnd kill +
   self-timeout.
5. **Event-driven**, not polling.
6. Optional **command allowlist**.

## Recommendation

The daemon's only real advantage over a plain **tmux pane / second `claude`
session** is auto-bridging output back to Claude — which is also its most dangerous
feature (the prompt-injection path).

- **Just want concurrent shell during a ponder?** Use a tmux split or a second
  session — concurrent, **zero new attack surface**, no listener, no injection
  channel. Simpler and strictly safer.
- **Want the auto-bridge-to-Claude convenience?** Build the daemon, but only with
  nonce-auth + untrusted-output fencing + strict perms + (ideally) an allowlist.

Concept is efficient *if* event-driven and idempotent, but **not secure by
default**. For most of the stated goal, the plain-pane approach avoids the risk the
daemon reintroduces.

## Other in-lane approaches evaluated (and rejected)

### Hook that acts on the message queue instead of a daemon

A `UserPromptSubmit` hook *does* act on queued messages — but one at a time, at the
moment each is **dequeued**, and it can block the model turn (this is already how
sethu's `>` works). So queued `>cmd`s drain in order at turn-end with no model turn
between them — no daemon needed to *process* them.

What it cannot do:
- Run concurrently *during* the ponder (dequeue is serial and post-turn).
- See the pending queue as a batch — no hook receives the list of unprocessed
  messages; `UserPromptSubmit` only ever sees the current prompt.
- Fire while a message still sits in the queue.

Conclusion: the hook replaces the daemon for everything **except**
concurrency-with-the-ponder. If that property isn't needed, drop the daemon.

### "The queued input is visible on screen"

True — the TUI renders queued messages — but visible ≠ accessible:
- Hooks don't receive the pending queue (only current prompt + metadata).
- Queued messages aren't persisted; the transcript logs turns only *as processed*.

The queue lives in the client's in-memory UI state. The only programmatic path is
**terminal scraping** (`tmux capture-pane`), which is brittle (parses rendered text:
wrapping, ANSI, truncation), racy (double-execution vs Claude's own dequeue → needs
dedup), and still out-of-lane. Not a clean solution.

## The right layer: a wrapper around Claude Code

Plugins/hooks all plug *into* Claude's single serial lane, so none can run
concurrently with a ponder. A **wrapper sits above Claude on its own lane**, making
parallelism trivial. Two buildable shapes.

### Option A — tmux wrapper (pragmatic, ~1 hour) — RECOMMENDED FIRST

tmux is itself a wrapper. A launcher sets up Claude in one pane and a command lane
in another, with a keybind popup that runs commands **concurrently** with the ponder.

```sh
tmux new-session \; \
  send-keys 'claude' Enter \; \
  bind-key g display-popup -E 'read -e -p "› " c && setsid bash -c "$c" &'
```

- Pros: real concurrency, robust, near-zero engineering, no terminal-proxy work.
- Cons: command lane is a popup/pane, not literally Claude's input line.
- ~90% of the value for ~5% of the effort.

### Option B — PTY proxy (true single-window wrapper)

A process owns the outer terminal, allocates a PTY, spawns `claude` as a child on
it, and transparently forwards bytes both ways. A **hotkey** (e.g. Ctrl-G) is
intercepted by the wrapper: it captures a line, runs it in a background thread
(parallel with the ponder), and shows output — Claude's queue never sees it.

```
wrapper (owns real terminal)
  keystrokes ─┬─► claude (child on inner PTY)      normal typing
              └─► on Ctrl-G: capture line,
                  run in bg thread (parallel),      the sethu lane
                  output → status line / log
  claude render ◄── proxied back
```

Hard parts (honest):
1. Trigger = a hotkey/chord, not a `>` prefix (Claude's raw-mode TUI consumes every
   keystroke; sniffing a prefix mid-type collides).
2. Output placement: don't split/composite (that reimplements tmux) — use a reserved
   status line + logfile + notification.
3. Proxy fidelity: must forward SIGWINCH/resize, signals, mouse, bracketed-paste.
4. Concurrency: run the command in a separate thread/subprocess so the proxy loop
   never blocks — this is the actual win.

Tooling: `node-pty` (most robust; VS Code/Hyper use it), Go `creack/pty`, Rust
`portable-pty` (wezterm), or Python `pty`/`pexpect`.

### Effect on sethu

The wrapper **replaces the hook** for the parallel path (no more fighting the
queue). sethu's hooks shrink to one optional job: the **bridge back** — the wrapper
writes results to a file, and a `Stop`/`UserPromptSubmit` hook injects them into
Claude's next turn *if* the user wants Claude to see them.

### Security & efficiency (better than the daemon)

- Security: a wrapper runs only commands the user types — no anonymous inbox, no
  listener, no network, no unauthenticated drop. As safe as the user's shell. The
  only injection risk is auto-bridging output into Claude (same fenced-untrusted
  caveat). Strictly safer than the daemon.
- Efficiency: a PTY select-loop copying bytes is negligible overhead; tmux is
  battle-tested. Both fine.

### Verdict

1. Build **Option A (tmux)** first — concurrent-with-ponder execution, today.
2. Graduate to **Option B (PTY proxy)** only if the inline single-window feel is
   required; budget real time (you are writing a mini terminal host).

The wrapper is the honest answer to the whole thread: **to get parallelism, move up
the stack — wrap Claude, don't plug into it.**

## Keystroke triggers

Question: can sethu be triggered by a keystroke instead of typing `>cmd`? Splits by
lane.

### In-Claude keybindings (`~/.claude/keybindings.json`) — dead end

Verified against the keybindings docs: bindings map keys **only** to built-in UI
actions (`chat:submit`, `app:interrupt`, navigation/toggles, etc.). They **cannot**:

- run a shell command / subprocess
- insert text, or insert-and-submit a predefined string (no `insertText` action)
- trigger a slash command (built-in or plugin)
- invoke a hook

So there is no way to bind a key to fire sethu from inside Claude Code — not even a
"type `>whoami` and submit" macro, since there is no insert-text action. And
`chat:submit` queues behind the current turn like normal typing anyway. The
in-Claude keystroke door is fully closed.

### Out-of-lane keystroke — the only path (and it is concurrent)

The terminal/OS layer is the sole trigger option, and it runs in parallel with the
ponder:

| Tool | Keystroke → | Mid-ponder? |
|---|---|---|
| tmux | `bind-key` → popup/pane runs command | yes |
| skhd (macOS) | global hotkey → script | yes |
| Hammerspoon (macOS) | `hs.hotkey.bind` → prompt + `hs.execute` | yes |
| iTerm2 / wezterm / kitty | key → send-text / spawn / coprocess | yes |
| Karabiner | key → shell script | yes |

### Rule this confirms

Claude Code exposes **no user-programmable trigger that runs code in its own lane** —
not hooks-during-ponder, not client commands for plugins, not keybindings. Any
keystroke that runs a sethu command must originate above/beside Claude. This is the
same conclusion as the wrapper section: the wrapper is the natural home for that
keystroke (e.g. macOS Hammerspoon/skhd global hotkey, or a tmux popup keybind), with
an optional file drop that a `Stop` hook bridges into Claude's next turn.

---

# Update — the official `monitors` primitive (confirmed) changes the picture

The "background-monitor primitive" floated above as an *"any available resources
upgrade"* is **real and documented**, not speculative:
[plugins-reference § Monitors](https://code.claude.com/docs/en/plugins-reference.md#monitors)
(Claude Code **v2.1.105+**).

- A plugin declares monitors in `monitors/monitors.json` (or inline via
  `experimental.monitors` in `plugin.json`). Each has `name`, `command`,
  `description`, optional `when` (`"always"` | `"on-skill-invoke:<skill>"`).
- Each monitor **runs a shell command for the lifetime of the session** and
  **delivers every stdout line to Claude as a notification** — asynchronously,
  *without* blocking or waiting on the turn queue. A `Notification` hook can react.
- Same trust level as hooks, unsandboxed, interactive sessions only. Claude Code
  **manages its lifecycle** (start at session/reload, stop at end).

**What this overturns:** a plugin *can* run a process concurrently with the ponder
and surface its output **during** generation (as notifications) — using an official,
lifecycle-managed primitive, with none of the hand-rolled SessionStart-daemon +
reaper + idempotency code. It does **not** overturn the permanent ceiling: a monitor
still can't inject into the *in-flight* API request; its notifications land as
context Claude sees going forward, not mid-stream in the current completion. And a
monitor runs a **fixed** command — it isn't itself a way to type a *new* arbitrary
command mid-ponder.

### The clean, all-official architecture

Combine three official primitives — no `/tmp` inbox daemon to hand-roll or harden:

```
monitors.json ──> monitor runs `sethu --serve` for the session (Claude-managed)
                     │  reads jobs from sethu's existing Unix socket (0600)
                     │  runs each through the allowlist, streams result to stdout
                     │        └─► surfaces to Claude as a NOTIFICATION (mid-ponder)
hotkey / tmux popup ─> `sethu --run "<cmd>"` drops a job on the socket (out-of-lane)
Notification hook ──> optional: react to / format the monitor's output
```

- **Monitor** = the concurrent worker, lifecycle-managed by Claude Code (replaces
  the SessionStart-daemon + Stop-reaper + idempotency lockfile entirely).
- **Hotkey/popup** = the only mid-ponder *input* channel (still out-of-lane, per the
  keystroke section).
- **Notification hook** = optional reaction/formatting.

# Connecting to sethu's existing codebase

Three concrete ties the design notes above don't yet make — they collapse a lot of
the proposed new build into "reuse what sethu already has, hardened":

1. **The inbox daemon is already built and hardened — it's `hooks/_shelld.py`.**
   The notes propose a new inbox/outbox FIFO in `~/.sethu/` and then a hardening
   checklist (0700 dir, 0600 files, fail-closed perms, reaping, event-driven).
   sethu's shell-mode daemon already *is* this: a per-session worker over a **Unix
   socket created `0600` via umask, fail-closed if group/world-accessible
   (`_perms_ok`), spawned/reaped by `_spawn_daemon`/`kill_daemons`, idle-timed-out**,
   event-driven (`select`, not polling). Use the **socket** as the auth'd job
   channel (add a per-session nonce), not a world-guessable `/tmp` file. Most of the
   notes' "hardening if built anyway" list is done in-tree.

2. **Everything should funnel through one guarded executor: `sethu --run "<cmd>"`.**
   A single subcommand that runs a command through the SAME allowlist / readonly /
   mode / truncation / `|^=^|` header logic (`_engine.process`/`run_capture`), and
   prints the result. Then the tmux popup, the monitor worker, AND the "rescue a
   queued `> cmd` that reached the model" idea all reuse **one safe code path**
   instead of three ad-hoc executors. This is the missing shared primitive under
   the file-drop bridge and Option A both.

3. **Option A's popup as written bypasses sethu's guardrails — route it through
   `sethu --run`.** The `bind-key … 'bash -c "$c"'` example runs commands with **no
   allowlist, no mode, no readonly** — the exact "a launched terminal shares none of
   sethu's guardrails" footgun sethu now warns about on every `--launch` (README,
   v0.8.3). Change the popup body to `sethu --run "$c"` (or `sethu --serve` +
   socket drop) so the parallel lane keeps sethu's safety model instead of
   discarding it.

**Net:** the honest build is smaller than the notes imply — an official `monitor`
running `sethu --serve` (worker) + a `sethu --run` guarded executor (shared entry) +
the existing `_shelld` socket (hardened channel) + a hotkey (out-of-lane input). No
new daemon lifecycle, no `/tmp` inbox, no re-hardening. Still parked; captured so the
implementation reuses what's already secure.

# Option — monitor as the sethu daemon (recommended synthesis)

Instead of sethu spawning and reaping its own shell daemon, **declare a monitor that
runs `sethu --serve`** and let Claude Code own its lifecycle. This is the cleanest
synthesis of everything above because a monitor solves *two* problems at once.

### Why it's strong

1. **Lifecycle is handed to Claude Code.** Today sethu hand-rolls the daemon's life:
   lazy `_spawn_daemon`, `kill_daemons`, `IDLE_TIMEOUT`, plus the orphan-accumulation
   problem (see the perf notes) and the class of bug that was the `kill_daemons` glob
   mismatch. A manifest monitor is **started at session start, kept alive, killed at
   session end** by Claude Code — the reaper, idempotency lockfile, and idle timer all
   disappear.
2. **The monitor's stdout is an official "bridge to Claude" — and it's mid-ponder.**
   The earlier SessionStart-daemon design bridged results back via a hand-rolled
   `Stop`-hook drain (turn-end only). A monitor's stdout becomes a **notification
   delivered *during* generation**, so a `>>` job dropped mid-ponder → daemon runs it
   → writes to stdout → Claude sees it concurrently. Official, and strictly better than
   the Stop-drain.

### The rule that makes it safe (and keeps `>` free)

A monitor's stdout is **model-facing** — every line it prints costs tokens. So the
daemon must route output by prefix, and **stay silent by default**:

| Job | Daemon writes the result to… | Claude sees it? | Tokens |
|---|---|---|---|
| `> cmd` (free) | the **socket → a user pane/file**; **stdout stays SILENT** | ❌ no | **free** |
| `>> cmd` (share) | its **stdout** → notification | ✅ yes | tokens (intended) |

The freeness of `>` no longer comes from a hook block (there's no hook on the socket
path) — it comes from the daemon **withholding output from stdout**. One slip (a
banner, a stray error to stdout) leaks every "free" command to Claude, so: redirect
ALL daemon logging/errors to a file, and treat stdout as a deliberate, `>>`-only
channel.

### Shape

```
monitors/monitors.json ─> monitor: `sethu --serve`   (Claude-managed lifecycle)
                             ├─ listens on the existing _shelld socket (0600, nonce)
                             ├─ `>  job` → run via allowlist → result to pane/file  (stdout SILENT → free)
                             └─ `>> job` → run via allowlist → result to STDOUT → notification (tokens)
hotkey / tmux popup ──────> drops a job on the socket                 (out-of-lane, works mid-ponder)
```

### Honest caveats

- **It runs always.** A manifest monitor starts every session (a bash+python process
  for *every* user, even those who never use shell mode) — vs. today's lazy spawn that
  only runs when shell mode is actually used. Mitigation: gate it with
  `when: "on-skill-invoke:<skill>"` so it only starts once the user opts into the
  concurrent lane.
- **Input during the ponder is still out-of-lane.** The monitor is the *worker*, not
  the *trigger*; a new mid-ponder command still arrives via a hotkey/popup onto the
  socket (per the keystroke section — no in-Claude path exists).
- **Free output still needs a pane.** `> cmd`'s user-facing output can't be painted
  into the Claude TUI (only notifications reach it, and those are model-facing), so it
  needs a pane/file surface.
- **Nonce-auth the socket.** An always-listening `sethu --serve` is an executor; any
  local process could drop a job. The `_shelld` socket is already `0600`/fail-closed —
  add a per-session nonce so only the user's hotkey/hook can enqueue.
- **Requires Claude Code v2.1.105+** (monitors), and monitors run unsandboxed at hook
  trust level.

### What it replaces

Monitor-as-daemon collapses **two** hand-rolled pieces into official primitives: the
daemon **lifecycle** (Claude Code manages it) *and* the **bridge-to-Claude** channel
(monitor stdout, mid-ponder, replacing the Stop-drain). The architecture reduces to:
monitor `sethu --serve` + the hardened socket + a hotkey drop + a pane for free
output — provided the daemon keeps stdout silent for `>` and speaks only for `>>`.
Still design-only; nothing built.
