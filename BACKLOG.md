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
