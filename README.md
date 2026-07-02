# `|^=^|` sethu — a command bridge for Claude Code

Run terminal commands **straight from Claude Code's prompt box**. See the output
yourself for **free** (it never touches the model), or share it with Claude only
when you want it to act on the result.

```text
> git status          # runs it, shows YOU the output — zero tokens, model never sees it
>> git status         # runs it AND sends the output to Claude (costs tokens, on purpose)
sethu --allow "npm test"   # read-only commands work already; allowlist the ones that write
```

Type a command prefixed with `>` as an ordinary message. A `UserPromptSubmit`
hook catches it, runs it locally, and blocks the prompt — so the model never
sees it and you spend nothing. Use `>>` when you *do* want Claude to see the
output. Every result is tagged with the little `|^=^|` bridge so sethu's output
is easy to spot.

---

## Why sethu

- **💸 Save tokens.** Glance at `> git status`, `> git diff`, `> ls`,
  `> cat config.json` as often as you like — for free. The output stays out of
  the context window, so Claude stays sharp longer and big sessions stay cheaper.
- **🎯 You control what Claude sees.** `>` keeps output private to you; `>>`
  feeds it in only when you want Claude to act on it. No more dumping noise into
  the conversation.
- **🧰 A shell in the chat.** `sethu --mode shell` gives you a persistent shell —
  `cd`, `export`, activate a venv, then run commands that share that state,
  without leaving the Claude window.
- **🛡️ Safe by default.** Read-only mode is **on out of the box**: inspection
  commands just work, while anything that writes or chains is refused until you
  explicitly allow it.
- **🪶 Zero dependencies.** Pure Python standard library — nothing to `pip install`.

> **sethu vs. `!` bang mode:** `!` always feeds output to Claude (costs tokens).
> sethu's edge is the **free, out-of-context `>`** — plus a persistent shell and
> allowlist guardrails. If you always want Claude to act on the output, `!` is
> fine; if you want to look at things for free, use `>`.

---

## Install

**Requirements:** [Claude Code](https://claude.com/claude-code), `python3` on your
`PATH`, and **macOS or Linux** (shell mode and `--launch` are Unix-only; Windows
via WSL).

Inside a Claude Code session:

```
/plugin marketplace add NamrataAShettar/claude-sethu
/plugin install sethu
/reload-plugins
```

That's it — read-only commands like `> ls` work immediately. To write, allowlist
the command: `sethu --allow "npm test"`.

<details>
<summary>Optional: terminal launchers &amp; tab-completion</summary>

Use `sethu …` and `quiet …` from a real terminal too:

```bash
ln -s "$PWD/bin/sethu" /opt/homebrew/bin/sethu   # any dir on your PATH
ln -s "$PWD/bin/quiet" /opt/homebrew/bin/quiet
```

Tab-completion for the `sethu` terminal command:

```bash
# zsh: add the completions dir to fpath before compinit in ~/.zshrc
fpath=("$PWD/completions" $fpath); autoload -U compinit && compinit
# bash: source it in ~/.bashrc
echo "source $PWD/completions/sethu.bash" >> ~/.bashrc
```

(Completion works in a real terminal only — the prompt box can't autocomplete
hook-intercepted text. In the box, type bare `sethu` for an options menu with a
"when to use what" guide.)
</details>

---

## Cheat sheet

Type these as normal messages (no `!`). Bare `sethu` shows the full menu. Flag and
subcommand styles both work (`sethu --mode shell` ≡ `sethu mode shell`).

| You type | What happens |
| --- | --- |
| `> cmd` | run it, show **you** the output — free |
| `>> cmd` | run it and **send output to Claude** — costs tokens |
| `sethu --allow "cmd"` | permit a writing command (read-only ones already work) |
| `sethu --launch "cmd"` | open `cmd` in a real terminal pane (for `vim`, `top`, `ssh`, …) |
| `sethu --mode shell` | persistent shell (`cd`/`export`/venv stick) |
| `sethu --timeout 60` | give commands up to 60s |
| `sethu --readonly off` | stop auto-allowing read-only commands |
| `sethu --trust on` | ⚠ run **anything**, no allowlist (footgun) |
| `sethu --runner` | show the current config |

Config lives in `~/.claude/sethu.json`.

---

## Statefulness modes

`sethu --mode <mode>` picks how much state persists between commands:

| Mode | `cd` sticks | `export`/venv sticks | Notes |
| --- | :---: | :---: | --- |
| `stateless` | ❌ | ❌ | fresh `bash -c` each time |
| `cwd` *(default)* | ✅ | ❌ | working dir remembered in a temp file |
| `shell` | ✅ | ✅ | one persistent `bash` (PTY daemon), reused |

`shell` mode keeps a long-lived bash so `cd`, env vars, `source`, and venvs carry
across commands. It idles out after 30 min; `sethu --restart` clears it. By
default it runs a clean `bash --norc` — `sethu --rc on` sources your `~/.zshrc` /
`~/.bashrc` so your aliases and functions work.

---

## Safety

- **Read-only by default.** Inspection commands (`ls`, `cat`, `git log`, …) run;
  anything that writes, chains, or execs is refused until you `sethu --allow` it.
- **The runner executes in your shell without Claude Code's per-command
  permission prompts** — so keep the allowlist tight, like shell aliases.
- **Injection-hardened.** An allowlisted command may only be followed by plain
  arguments — not an unquoted pipe, redirect, `;`/`&&`, subshell, or substitution.
  Allowing `ls` does **not** allow `> ls; rm -rf ~`. (Metacharacters *inside
  quotes* are fine — `> python3 -c "import os; print(1)"` works.)
- **Trust mode is opt-in.** `sethu --trust on` removes the allowlist entirely and
  runs anything — a real footgun. It's off by default, warned loudly, and shown
  as `⚠trust` in the status line while active.

---

## When sethu *won't* work (the honest limits)

sethu is a hook, and hooks have boundaries. Here's where it can't help — and what
to do instead:

| Situation | Why | Do this instead |
| --- | --- | --- |
| **Claude is still generating** ("pondering") | The hook only fires on a prompt that *starts* a turn. A `> cmd` typed mid-turn is queued and read by the **model** (costs tokens), not run by sethu. | Send `> cmd` when Claude is idle, or run things in a separate terminal / `sethu --launch <shell>`. |
| **Interactive programs** (`vim`, `top`, `ssh`, a bare REPL) | The runner has no terminal, so they'd hang. | `sethu --launch "vim"` opens a real pane. |
| **Commands that prompt for input** (`npm install` conflicts, `apt install` "[Y/n]", `gh auth login`) | Even shell mode can't *type back* at a prompt. | Use non-interactive flags (`-y`, `--yes`, `DEBIAN_FRONTEND=noninteractive`) or `--launch`. |
| **Long-running commands** (servers, `tail -f`) | Capped at 20s (`sethu --timeout` to raise, but the hook budget is ~30s). | Run them in a launched pane. |
| **Windows (native)** | Shell mode + `--launch` need Unix sockets/PTYs. | Use WSL. |

> A **launched** terminal (`--launch`) is a *plain shell* — it does **not** share
> sethu's allowlist, mode, or cwd. It's an escape hatch out of sethu for
> interactive/long-running programs, not a safer runner.

---

## Extras

<details>
<summary><code>quiet</code> — shrink the output <em>Claude</em> pays for</summary>

When **Claude** runs a command, its full output enters the context and costs
tokens. `quiet` runs it, strips ANSI/progress noise, and keeps only a short tail
(plus error lines on failure) with the real exit code — a 200-line build becomes
~20 lines.

```bash
quiet npm install         # only the tail + exit code reach Claude
quiet --lines 40 pytest   # keep the last 40 lines
```

It exits with the command's own status. Drop the snippet from
[`docs/token-thrifty.md`](docs/token-thrifty.md) into your `CLAUDE.md` to make
Claude use it automatically. (`> cmd` keeps *your* commands out of context;
`quiet` shrinks *Claude's own* — different levers, same goal.)
</details>

<details>
<summary>Long output &amp; temp files</summary>

Big output (`ps aux`, `ls -R`) is capped at **40 lines** inline (`sethu --maxlines`
to change; `0` = unlimited). The full text is saved to a per-session file and a
note points at it — open it, or `sethu --launch "less <path>"` to scroll it.

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
> python3                     # bare REPL → refused; use --launch
```

`python`/`node`/`irb`/`ipython` count as interactive only when launched bare or
with `-i`; a script path, `-c`, or `-m` means batch mode.
</details>

---

## Feedback &amp; feature requests

sethu is actively developed and **your input shapes it.** Found a rough edge, hit
a case that didn't work, or want a feature (a `--console` shared pane? another
mode?) — please
**[open an issue](https://github.com/NamrataAShettar/claude-sethu/issues)**. Bug
reports, ideas, and "this was confusing" notes are all genuinely welcome.

---

## Tests &amp; contributing

Stdlib only, no dependencies:

```bash
python3 -m unittest discover -s tests -v
```

The suite covers the allowlist, read-only safety (injection/chaining refused),
the interactive guard, all three modes (incl. the persistent shell), the `>>`
pipe, and config round-trips. CI runs them on every push and PR. PRs welcome.

## About Claude Code

sethu is a plugin for **[Claude Code](https://claude.com/claude-code)**,
Anthropic's official CLI for Claude, built entirely from its extension points (a
`UserPromptSubmit` hook for `>`/`>>`, a `SessionStart` hook for the first-run
hint). Docs: [Claude Code](https://claude.com/claude-code) ·
[Plugins](https://code.claude.com/docs/en/plugins) ·
[Hooks](https://code.claude.com/docs/en/hooks).

## License

MIT
</content>
