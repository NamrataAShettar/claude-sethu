# `|^=^|` sethu: a bridge between Claude Code's prompt box and your shell

The name **sethu** is Sanskrit for *"bridge"* (a word shared across Indian
languages). It bridges the two, so you can run terminal commands without leaving
the Claude Code chat.

**The problem:** while working in Claude Code you constantly want to *peek* at
things like `git status`, a diff, a file, or `ls`. But every command you ask
Claude to run dumps its output into the context window. That **costs tokens**,
**clutters the conversation**, and fills your context faster (so auto-compaction
hits sooner). Alt-tabbing to a real terminal breaks your flow.

**sethu fixes that.** Run those commands **right in the prompt box** and see the
output yourself for **free** (it never touches the model). Share it with Claude
only when you actually want it to act on the result.

```text
> git status          # runs it, shows YOU the output (zero tokens, model never sees it)
>> git status         # runs it AND sends the output to Claude (costs tokens, on purpose)
sethu --allow "npm test"   # read-only commands work already; allowlist the ones that write
```

Type a command prefixed with `>` as an ordinary message. A `UserPromptSubmit`
hook catches it, runs it locally, and blocks the prompt, so the model never sees
it and you spend nothing. Use `>>` when you *do* want Claude to see the output.
Every result is tagged with the little `|^=^|` bridge so sethu's output is easy
to spot.

---

## ⚡ Why sethu

- **💸 Save tokens.** Glance at `> git status`, `> git diff`, `> ls`, or
  `> cat config.json` as often as you like, all for free. The output stays out of
  the context window, so Claude stays sharp longer and big sessions stay cheaper.
- **🎯 You control what Claude sees.** `>` keeps output private to you, while `>>`
  feeds it in only when you want Claude to act on it. No more dumping noise into
  the conversation.
- **🐚 A shell in the chat.** `sethu --mode shell` gives you a persistent shell:
  `cd`, `export`, activate a venv, then run commands that share that state,
  without leaving the Claude window.
- **🛡️ Safe by default.** Read-only mode is **on out of the box**, so inspection
  commands just work while anything that writes or chains is refused until you
  explicitly allow it.
- **🪶 No package installs.** Pure Python standard library, so there's no `pip`,
  no npm, and no third-party packages to manage. (It does need `python3`, see
  Requirements.)

> **sethu vs. `!` bang mode:** `!` always feeds output to Claude, so it always
> costs tokens. sethu's edge is the **free, out-of-context `>`**, plus a
> persistent shell and allowlist guardrails. If you always want Claude to act on
> the output, `!` is fine. If you want to look at things for free, use `>`.

---

## 📦 Install

**Requirements:**

- [Claude Code](https://claude.com/claude-code).
- **`python3`** on your `PATH`. sethu's hooks run it, so it's required. Check with
  `python3 --version`. If it's missing (recent macOS doesn't ship it by default),
  install via [Homebrew](https://brew.sh) (`brew install python`), the Xcode
  Command Line Tools (`xcode-select --install`), or
  [python.org](https://www.python.org/downloads/). Most Linux distros already
  include it. (If it's missing, sethu tells you at session start and stays out of
  your way, so your prompts still work normally, rather than erroring.)
- **macOS or Linux.** Shell mode and `--launch` are Unix-only; on Windows, use
  WSL. (The plain `>` / `cwd` / `stateless` runner is otherwise portable.)

Inside a Claude Code session:

```
/plugin marketplace add NamrataAShettar/claude-sethu
/plugin install sethu
/reload-plugins
```

That's it. Read-only commands like `> ls` work immediately. To write, allowlist
the command: `sethu --allow "npm test"`.

(You manage sethu right in the prompt box: type bare `sethu` for the options menu
with a "when to use what" guide. No terminal setup needed.)

---

## 📋 Cheat sheet

Type these as normal messages (no `!`). Bare `sethu` shows the full menu. Flag and
subcommand styles both work (`sethu --mode shell` ≡ `sethu mode shell`).

| You type | What happens |
| --- | --- |
| `> cmd` | run it, show **you** the output (free) |
| `>> cmd` | run it and **send output to Claude** (costs tokens) |
| `sethu --allow "cmd"` | permit a writing command (read-only ones already work) |
| `sethu --unallow "cmd"` | remove a command from the allowlist |
| `sethu --launch "cmd"` | open `cmd` in a real terminal pane (for `vim`, `top`, `ssh`, …) |
| `sethu --mode shell` | persistent shell (`cd`/`export`/venv stick) |
| `sethu --restart` | restart the persistent shell (clears shell-mode state) |
| `sethu --timeout 60` | give commands up to 60s |
| `sethu --readonly off` | stop auto-allowing read-only commands |
| `sethu --trust on` | ⚠ run **anything**, no allowlist (footgun) |
| `sethu --runner` | show the current config |

Config lives in `~/.claude/sethu.json`.

> 💡 **Want ideas?** See **[docs/use-cases.md](docs/use-cases.md)** for a full,
> copy-paste catalog covering git, file and log inspection, build and test,
> persistent-shell workflows, quick lookups, and more, with the exact commands
> for each.

---

## 🔀 Statefulness modes

`sethu --mode <mode>` picks how much state persists between commands:

| Mode | `cd` sticks | `export`/venv sticks | Notes |
| --- | :---: | :---: | --- |
| `stateless` | ❌ | ❌ | fresh `bash -c` each time |
| `cwd` *(default)* | ✅ | ❌ | working dir remembered in a temp file |
| `shell` | ✅ | ✅ | one persistent `bash` (PTY daemon), reused |

`shell` mode keeps a long-lived bash so `cd`, env vars, `source`, and venvs carry
across commands. It idles out after 30 min, and `sethu --restart` clears it on
demand. By default it runs a clean `bash --norc`. Turn on `sethu --rc on` to
source your `~/.zshrc` / `~/.bashrc` so your aliases and functions work.

---

## 🛡️ Safety

- **Read-only by default.** Inspection commands (`ls`, `cat`, `git log`, …) run,
  while anything that writes, chains, or execs is refused until you
  `sethu --allow` it.
- **The runner executes in your shell without Claude Code's per-command
  permission prompts**, so keep the allowlist tight, like shell aliases.
- **Injection-hardened.** An allowlisted command may only be followed by plain
  arguments, not an unquoted pipe, redirect, `;`/`&&`, subshell, or substitution.
  Allowing `ls` does **not** allow `> ls; rm -rf ~`. (Metacharacters *inside
  quotes* are fine, so `> python3 -c "import os; print(1)"` works.)
- **Trust mode is opt-in.** `sethu --trust on` removes the allowlist entirely and
  runs anything, a real footgun. It's off by default, warned loudly, and shown as
  `⚠trust` in the status line while active.

---

## 🤝 Coexisting with other hooks

sethu is a well-behaved `UserPromptSubmit` hook, and it installs cleanly alongside
your others (hooks run **in parallel**, with no ordering dependence):

- **Normal prompts** (not `>` / `>>` / `sethu`) pass straight through: sethu does
  **nothing**, so your other hooks run exactly as they would without it.
- **`>> cmd`** injects output as `additionalContext`, which Claude Code
  **concatenates** with any other hook's context, so they stack rather than clash.
- **`> cmd` / `sethu …`** blocks that one prompt (its purpose). Other hooks still
  run their side effects, but the model doesn't (as intended).

The only overlap to know about is another `UserPromptSubmit` hook that *also* acts
on `>`-prefixed prompts. If two hooks both block the same prompt it stays blocked
(fine), but Claude Code doesn't document how two block *reasons* are combined, so
the shown result may merge them. That's rare in practice, since sethu only claims
the `>` prefix.

## 🚧 When sethu *won't* work (the honest limits)

sethu is a hook, and hooks have boundaries. Here's where it can't help, and what
to do instead:

| Situation | Why | Do this instead |
| --- | --- | --- |
| **Claude is still generating** ("pondering") | The hook only fires on a prompt that *starts* a turn. A `> cmd` typed mid-turn is queued and read by the **model** (costs tokens), not run by sethu. | Send `> cmd` when Claude is idle, or run things in a separate terminal / `sethu --launch <shell>`. |
| **Interactive programs** (`vim`, `top`, `ssh`, a bare REPL) | The runner has no terminal, so they'd hang. | `sethu --launch "vim"` opens a real pane. |
| **Commands that prompt for input** (`npm install` conflicts, `apt install` "[Y/n]", `gh auth login`) | Even shell mode can't *type back* at a prompt. | Use non-interactive flags (`-y`, `--yes`, `DEBIAN_FRONTEND=noninteractive`) or `--launch`. |
| **Long-running commands** (servers, `tail -f`) | Capped at 20s (`sethu --timeout` to raise, but the hook budget is ~30s). | Run them in a launched pane. |
| **Windows (native)** | Shell mode + `--launch` need Unix sockets/PTYs. | Use WSL. |

> A **launched** terminal (`--launch`) is a *plain shell*. It does **not** share
> sethu's allowlist, mode, or cwd. It's an escape hatch out of sethu for
> interactive or long-running programs, not a safer runner.

---

## 🛟 Troubleshooting

**"UserPromptSubmit operation blocked by hook:" shows before my output.** That's
normal, and it means it worked. Claude Code prints that wrapper around any prompt a
hook handles locally; it's how sethu keeps your command out of the model. The
`|^=^| [mode] ✓ exit 0` line below it is your actual result.

**I typed `> cmd` but nothing ran, or Claude answered it instead.** You typed it
while Claude was still generating. sethu only fires on a prompt that *starts* a
turn, so a `>` typed mid-response is read by the model (and costs tokens), not run
by sethu. Send `> cmd` when Claude is idle.

**"`X` isn't allowed to run."** sethu is read-only by default. The message tells you
why (e.g. `git branch` can also write, `npm` isn't a read-only command). To permit
it, `sethu --allow "X"`. If it's interactive (`vim`, a bare REPL), use
`sethu --launch "X"` instead (allowlisting can't make those run). To drop the
guardrails entirely and run anything, there's `sethu --trust on`, but it's a
footgun, so prefer allowlisting the specific commands you actually want.

**"timed out after 20s."** Captured commands are capped under Claude Code's ~30s
hook budget. Raise it a bit with `sethu --timeout`, or run long-lived commands
(servers, `tail -f`) in a real terminal with `sethu --launch`.

Still stuck? [Open an issue](https://github.com/NamrataAShettar/claude-sethu/issues).

---

## 🧩 Extras

<details>
<summary>Long output &amp; temp files</summary>

Big output (`ps aux`, `ls -R`) is capped at **40 lines** inline (`sethu --maxlines`
to change; `0` = unlimited). The full text is saved to a per-session file and a
note points at it, so you can open it, or `sethu --launch "less <path>"` to scroll
it.

Storage stays bounded: the saved file is **reused per session** (one at a time),
sethu sweeps its own temp files older than 7 days, and the OS temp dir is purged
on its own schedule. Persistent-shell sockets are left to the daemon.
</details>

<details>
<summary>Running scripts vs. REPLs</summary>

An interpreter *with a script* runs and exits, so it works captured:

```
sethu --allow python3
> python3 build/report.py     # runs, output captured, zero tokens
> python3 -c "print(2**10)"   # -c / -m are batch too
> python3                     # bare REPL, refused (use --launch)
```

`python`/`node`/`irb`/`ipython` count as interactive only when launched bare or
with `-i`. A script path, `-c`, or `-m` means batch mode.
</details>

---

## 💬 Feedback & feature requests

sethu is actively developed and **your input shapes it.** If you find a rough
edge, hit a case that didn't work, or want a feature (a `--console` shared pane?
another mode?), please
**[open an issue](https://github.com/NamrataAShettar/claude-sethu/issues)**. Bug
reports, ideas, and "this was confusing" notes are all genuinely welcome.

---

## 🧪 Tests & contributing

Stdlib only, no dependencies:

```bash
python3 -m unittest discover -s tests -v
```

The suite covers the allowlist, read-only safety (injection and chaining refused),
the interactive guard, all three modes (including the persistent shell), the `>>`
pipe, and config round-trips. CI runs them on every push and PR. PRs welcome.

Every feature and CLI argument maps to a test, tracked in a **coverage table** at
the top of [`tests/test_sethu.py`](tests/test_sethu.py). If you add a feature or
argument, add a row, write its test, and tick it, so coverage stays complete.

## ℹ️ About Claude Code

sethu is a plugin for **[Claude Code](https://claude.com/claude-code)**,
Anthropic's official CLI for Claude, built entirely from its extension points (a
`UserPromptSubmit` hook for `>`/`>>`, and a `SessionStart` hook for the first-run
hint). Docs: [Claude Code](https://claude.com/claude-code) ·
[Plugins](https://code.claude.com/docs/en/plugins) ·
[Hooks](https://code.claude.com/docs/en/hooks).

## License

MIT
</content>
