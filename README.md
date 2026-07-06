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
> grep -n TODO src/   # runs it, shows YOU the output (zero tokens, model never sees it)
>> grep -n TODO src/  # runs it AND sends the output to Claude (costs tokens, on purpose)
sethu --allow git     # opt a whole tool in (git/find/npm/…); safe tools like grep/ls/cat run already
> git status          # now runs (git was allowed above)
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
- **🛡️ Safe by default.** **Gated** out of the box: a curated set of safe inspection
  tools (`ls`, `cat`, `grep`, `jq`, …) just works, while everything else is refused
  until you `--allow` that tool (or `--trust on` for everything).
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

That's it. Gated tools like `> ls` / `> grep` work immediately. For anything else
(git, find, npm, …), allow the tool once: `sethu --allow git`.

(You manage sethu right in the prompt box: type bare `sethu` for the options menu.
No terminal setup needed.)

---

## 📋 Cheat sheet

Type these as normal messages (no `!`). Bare `sethu` shows the full menu. Flag and
subcommand styles both work (`sethu --mode shell` ≡ `sethu mode shell`).

| You type | What happens |
| --- | --- |
| `> cmd` | run it, show **you** the output (free) |
| `>> cmd` | run it and **send output to Claude** (costs tokens) |
| `sethu --allow "tool"` | permit a whole tool, any flags (`git`, `find`, `npm`, …); gated ones already run |
| `sethu --unallow "tool"` | remove a tool from the allowlist |
| `sethu --launch "cmd"` | open `cmd` in a real terminal pane (for `vim`, `top`, `ssh`, …) |
| `sethu --gated-list` | tools that run without asking (built-in + ones you allowed) |
| `sethu --trust on` | ⚠ run **anything**, gate off (no guardrails) |
| `sethu --mode stateless\|cwd\|shell` | switch statefulness (default `cwd`; `shell` makes `cd`/`export`/venv stick, see below) |
| `sethu --rc on` | in `shell` mode, load your shell aliases/functions/env |
| `sethu --plain on` | `sethu:` prefix + words instead of `\|^=^\|`/glyphs (screen readers) |
| `sethu --restart` | restart the persistent shell (clears shell-mode state) |
| `sethu --timeout 60` | give commands up to 60s |
| `sethu --runner` | show the current config (with defaults) |

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

**Notes:**

- By default, `>` runs in your Claude Code session's working directory (the folder
  you launched Claude in).
- `shell` mode keeps a long-lived bash so `cd`, env vars, `source`, and venvs carry
  across commands. It idles out after 30 min, and `sethu --restart` clears it on demand.
- `shell` mode runs a clean `bash --norc` by default; turn on `sethu --rc on` to source
  your `~/.zshrc` / `~/.bashrc` so your aliases and functions work.

---

## 🛡️ Safety

- **Gated by default.** Only tools that can't write or exec with *any* flags
  (`ls`, `cat`, `grep`, `jq`, …) run on their own; anything that can (`git`, `find`,
  `npm`, …) waits for `sethu --allow`. A tool is gated whole or allowed whole, no
  per-flag policing.
- **A guardrail, not a sandbox.** You can always bypass it via your own terminal, or
  by widening the gate with `--allow` or `--trust`. Flag-safety is per-command too: in
  **shell mode** an `alias` or `PATH` you set can change what a later gated name runs.
- **The runner executes in your shell without Claude Code's per-command
  permission prompts**, so keep the allowlist tight, like shell aliases. `--allow`-ing
  a launcher (`git`, `sh`, `python`, …) permits *any* of its flags; sethu warns you.
- **Injection-hardened.** An allowed/gated tool may only be followed by plain
  arguments, not an unquoted pipe, redirect, `;`/`&&`, subshell, or substitution.
  Allowing `ls` does **not** allow `> ls; rm -rf ~`. (Metacharacters *inside
  quotes* are fine, so once `python3` is allowed, `> python3 -c "import os; print(1)"` works.)
- **Trust is the one safety knob.** `sethu --trust on` turns the gate off and runs
  anything with no guardrails at all. Off by default (= gated), warned loudly, shown as
  `⚠trust` while active.

---

## 🚧 When sethu *won't* work (the honest limits)

sethu is a hook, and hooks have boundaries. Here's where it can't help, and what
to do instead:

| Situation | Why | Do this instead |
| --- | --- | --- |
| **Claude is still generating** ("pondering") | The hook only fires on a prompt that *starts* a turn. A `> cmd` typed mid-turn is queued and read by the **model** (costs tokens), not run by sethu. | Send `> cmd` when Claude is idle, or run things in a separate terminal / `sethu --launch <shell>`. |
| **Interactive programs** (`vim`, `top`, `ssh`, a bare REPL) | The runner has no terminal, so they'd hang. | `sethu --launch "vim"` opens a real pane. |
| **Commands that prompt for input** (`npm install` conflicts, `apt install` "[Y/n]", `gh auth login`) | Even shell mode can't *type back* at a prompt. | Use non-interactive flags (`-y`, `--yes`, `DEBIAN_FRONTEND=noninteractive`) or `--launch`. |
| **Long-running commands** (servers, `tail -f`) | Capped at 20s (`sethu --timeout` to raise, but the hook budget is ~30s). | Run them in a launched pane. |
| **Different modes in two sessions at once** | Settings (mode, allowlist, trust) live in one shared config, so `sethu --mode` / `--allow` apply to **all** your Claude sessions. (Each session's working dir and `shell` bash stay separate.) | Set the mode you need for now; you can't run one session in `shell` and another in `cwd` simultaneously. |
| **Windows (native)** | Shell mode + `--launch` need Unix sockets/PTYs. | Use WSL. |
| **`--allow`-ed git in an untrusted repo** | once you `--allow git`, `> git status`/`diff` run programs named in the repo's own `.git/config` (`core.fsmonitor`, `diff.external`, …); that's git's behavior, same as your terminal. | Don't run git in a repo you don't trust; git's `safe.directory` only guards other-owner repos. |

> A **launched** terminal (`--launch`) is a *plain shell*. It does **not** share
> sethu's allowlist, mode, or cwd. It's an escape hatch out of sethu for
> interactive or long-running programs, not a safer runner.

---

## 🛟 Troubleshooting

- **"UserPromptSubmit operation blocked by hook:" appears before my output**: that's
  normal, and it means it worked. Claude Code prints that wrapper around any prompt a
  hook handles locally; it's how sethu keeps your command out of the model. The
  `|^=^| [mode] ✓ exit 0` line below it is your actual result.
- **I typed `> cmd` but nothing ran (or Claude answered it instead)**: you typed it
  while Claude was still generating. sethu only fires on a prompt that *starts* a turn,
  so a `>` typed mid-response is read by the model (and costs tokens), not run by sethu.
  Send `> cmd` when Claude is idle.
- **"`X` isn't in the gated set."**: sethu is gated by default; the message tells you
  why (e.g. `git`/`npm` can write or run other programs). To permit it, `sethu --allow X`
  (the whole tool). If it's interactive (`vim`, a bare REPL), use `sethu --launch "X"`
  instead (allowlisting can't make those run). To drop the guardrails entirely, there's
  `sethu --trust on`, genuinely risky, so prefer allowlisting the specific tools you want.
- **"timed out after 20s."**: captured commands are capped under Claude Code's ~30s hook
  budget. Raise it with `sethu --timeout`, or run long-lived commands (servers, `tail -f`)
  in a real terminal with `sethu --launch`.

Still stuck? [Open an issue](https://github.com/NamrataAShettar/claude-sethu/issues).

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

---

## 🧩 Extras

<details>
<summary>Accessibility (screen readers, plain terminals)</summary>

The header is colorblind-safe (Okabe-Ito) and never color-only; status, mode, and
warnings are always words, so a screen reader gets the full meaning; `NO_COLOR` drops
color. For readers, **`sethu --plain on`** (or `SETHU_PLAIN`) swaps the `|^=^|` icon and
`·✓✗⚠→` glyphs for a plain `sethu:` prefix + comma-separated words (e.g. `sethu: [cwd],
exit 0, $ git status`), also a fallback for terminals without good Unicode.
</details>

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

## 🧪 Tests

Stdlib only, no dependencies:

```bash
python3 -m unittest discover -s tests -v
```

The suite covers the allowlist, gated safety (injection and chaining refused),
the interactive guard, all three modes (including the persistent shell), the `>>`
pipe, and config round-trips. Every feature and CLI argument maps to a test (a
coverage table at the top of `tests/test_sethu.py`, guarded by a meta-test that
fails if any argument is untested). CI runs them on every push and PR.

See **[docs/testing.md](docs/testing.md)** for how to exercise a behavior directly
and how to test a feature branch live in Claude Code before merging, and
**[docs/design-guidelines.md](docs/design-guidelines.md)** for the UX / correctness
/ security / performance / storage principles every change is checked against.

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
