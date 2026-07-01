# sethu-wrap — a parallel, zero-token command lane for Claude Code

Status: **tmux implementation (first cut).**

`sethu-wrap` runs Claude Code inside tmux and gives you a keybinding that opens a
popup where you type a shell command. The command runs in a **separate process**,
so it executes **concurrently with whatever Claude is doing** ("during the
ponder"), and its output goes to a log file / tail pane — **never into Claude's
context, so it costs zero tokens.**

This is the out-of-lane version of sethu's `>` quiet philosophy: run beside Claude,
report only to you. See `docs/during-ponder-execution.md` for why in-plugin
approaches (hooks, queue-acting hooks, `/btw`, a daemon) cannot achieve
concurrency-with-the-ponder, and why moving up to a wrapper is the answer.

## Requirements

- **tmux >= 3.2** (for `display-popup`)
- `claude` on your `PATH`
- macOS, Linux, or Windows **via WSL** (native Windows console is not supported by
  tmux — that is a future PTY-proxy wrapper)

## Usage

```sh
bin/sethu-wrap
```

Then:

- Type to Claude as normal in the main pane.
- Press **Alt-g** (`M-g`) any time — even while Claude is generating — to open the
  popup. Type a command, Enter. It runs detached and concurrently.
- Watch results in the bottom **tail pane** (or `~/.sethu/out.log`). Claude never
  sees them.

### Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `SETHU_WRAP_SESSION` | `sethu` | tmux session name |
| `SETHU_CLAUDE_BIN` | `claude` | claude binary |
| `SETHU_WRAP_DIR` | `~/.sethu` | log/output dir |
| `SETHU_WRAP_KEY` | `M-g` | popup keybinding |
| `SETHU_WRAP_TAIL` | `1` | show the log tail pane |

## Why tmux (terminal-agnostic)

tmux draws its own UI with standard escape sequences, so `sethu-wrap` works
identically in **iTerm2, Terminal.app, Alacritty, kitty, wezterm, gnome-terminal,
xterm**, etc. You are bound to tmux, not to any particular terminal emulator.

## Security

The tmux popup is a **separate, explicit input surface** — it does not sit in the
middle of your keystrokes to Claude. That means the wrapper has:

- no listener / inbox / socket → no anonymous local injection (unlike a daemon)
- no keystroke MITM and no paste-injection into Claude's stream (unlike a PTY proxy)
- no path from command output into Claude's context → no prompt-injection

Residual, standard hygiene (handled): `~/.sethu/` is `0700` and `out.log` is `0600`
(output can contain secrets); commands run as your user, exactly like your shell.

## Not in this cut (follow-ups)

- Native Windows console support (PTY-proxy wrapper, Python + pywinpty)
- Opt-in `Stop`-hook bridge to feed a chosen result into Claude's next turn
  (costs tokens only when you opt in)
- Optional desktop notifications on command completion
