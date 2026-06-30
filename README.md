# sethu सेतु — a command bridge for Claude Code

**सेतु** means *"bridge."* It lets you run terminal commands straight from
Claude Code's prompt box, for free.

```text
sethu --allow "git status"      # allow a command (safe by default — allowlist is empty)
> git status                    # run it locally, block the model → ZERO tokens, output shown to you
>> git status                   # run it AND send the output to Claude (costs tokens, on purpose)
```

Type a command prefixed with `>` as a normal message. A `UserPromptSubmit` hook
intercepts it, runs it locally, and **blocks the prompt** — so the model never
sees it and you spend **no tokens**. Use `>>` when you *want* Claude to see the
output.

Each result starts with a status line showing the active **mode**, completion,
exit code, and the command:

```text
[cwd] ✓ exit 0 · $ git status
On branch main …
```

> Claude Code prefixes blocked-prompt output with *"UserPromptSubmit operation
> blocked by hook:"* — that's the harness telling you the prompt was handled
> locally and never hit the model (i.e. it worked, for free). It can't be
> removed by a plugin; the status line above makes the result read as intended.

> Why this is free (and `!` isn't): bang mode adds output to context and (since
> Claude Code v2.1.186) makes Claude respond — that costs tokens. sethu blocks
> the prompt entirely, so nothing reaches the model unless you ask with `>>`.

## What is it good for?

sethu shines whenever you want to run a command *near* Claude but don't need to
spend tokens or clutter the conversation on it.

- **Protect your context window.** Every command you run via `>` instead of
  asking Claude keeps its output out of the context window — so Claude stays
  sharp longer, auto-compaction triggers later, and big sessions stay cheaper.
  Glance at `> git status`, `> git diff`, `> ls`, `> cat config.json` as often as
  you like for free.
- **Stretch your rate limits / spend.** On Pro/Max or metered API, the checks
  you'd normally ask Claude to run (and pay for) become free. Handy mid-task when
  you just want to *see* something.
- **Decide what Claude pays attention to.** `> cmd` keeps the result private to
  you; `>> cmd` deliberately feeds it into Claude's context when you *do* want it
  to act on the output. You control the firehose.
- **A persistent shell right in the chat** (`sethu --mode shell`). Activate a
  venv, export env vars, `cd` into a subdir — then run a series of commands that
  share that state, all without leaving the Claude window:
  ```text
  sethu --mode shell
  > source .venv/bin/activate
  > export API_ENV=staging
  > cd services/api
  >> pytest -q tests/smoke      # runs in that exact env, and Claude sees the result
  ```
- **Safe, guarded execution.** `sethu --readonly on` lets you run inspection
  commands freely while refusing anything that writes or chains — good for cautious
  use, demos, or shared machines. The allowlist is empty by default.
- **No context-switching.** One window for the conversation *and* your quick
  commands — no alt-tab to a terminal, useful especially in SSH'd or remote
  Claude Code sessions where a spare shell isn't handy.
- **A scratchpad.** `> date`, `> df -h`, `> echo $PATH`, `> cal` — quick lookups
  without spawning anything.

If you mostly want Claude to *act on* command output, plain `!` bang mode already
covers that. sethu's edge is the **free, out-of-context `>`**, the **persistent
shell**, and the **allowlist guardrails**.

## Install

```
/plugin marketplace add NamrataAShettar/claude-sethu
/plugin install sethu
/reload-plugins
```

Optional launchers so you can type `sethu …` and `quiet …` in a terminal too:

```bash
ln -s "$PWD/bin/sethu" /opt/homebrew/bin/sethu   # any dir on your PATH
ln -s "$PWD/bin/quiet" /opt/homebrew/bin/quiet
```

Tab-completion for the `sethu` terminal command (completes flags, subcommands,
and mode/readonly values):

```bash
# zsh: add the completions dir to fpath before compinit in ~/.zshrc
fpath=("$PWD/completions" $fpath); autoload -U compinit && compinit
# bash: source it in ~/.bashrc
echo "source $PWD/completions/sethu.bash" >> ~/.bashrc
```

(Tab-completion works in a real terminal only — Claude Code's prompt box can't
autocomplete hook-intercepted commands. In the box, type bare `sethu` for the
options menu.)

## `quiet` — shrink command output Claude pays for

When **Claude** runs a command, its full output enters Claude's context and costs
tokens. `quiet` runs the command, strips ANSI/progress noise, and surfaces only a
short tail (plus error lines on failure) with the real exit code — so a 200-line
build becomes ~20 lines in context.

```bash
quiet npm install            # only the tail + exit code reach Claude
quiet --lines 40 pytest      # keep the last 40 lines
```

It exits with the command's own status, so pass/fail is preserved. To make Claude
use it automatically, drop the ready-made snippet from
[`docs/token-thrifty.md`](docs/token-thrifty.md) into your project's `CLAUDE.md`.

> `> cmd` keeps *your* commands out of Claude's context entirely; `quiet` shrinks
> *Claude's own* commands. Different levers, same goal: fewer tokens.

## Read-only mode — skip the per-command allowlisting

Tired of allowing `ls`, `cat`, `pwd`, `git log` one by one? Turn on read-only
mode and a curated set of **inspection** commands is auto-allowed:

```
sethu --readonly on
> ls
> git log --oneline -5
> cat README.md | head        # pipelines of read-only programs are fine
```

It's deliberately strict so it stays safe — a command is auto-allowed only if it
is a pipeline of known read-only programs (ls, cat, head, grep, find, read-only
`git` subcommands, …) with **no** redirection (`>`), chaining (`;`, `&&`),
command substitution (`` ` ``, `$()`), or backgrounding. So `> ls; rm -rf ~`,
`> echo x > f`, `> cat f | sh`, `> git push`, and `> find . -delete` are all
**refused**. Your explicit `--allow` entries still work on top.

## Trust mode (opt-in footgun)

If you want `>` to behave like an unrestricted terminal — run *anything*, no
allowlist — turn on trust mode:

```
sethu --trust on      # ⚠ bypasses the allowlist; ANY `>` command runs
```

The allowlist exists because the runner executes in your shell **without** Claude
Code's permission prompts, so a stray line after `>` would auto-run. Trust mode
removes that guard, so use it only when you accept that. It's visible while
active — the status line shows `[shell ⚠trust]` — and `sethu --readonly on`
remains the safer middle ground (inspection commands free, writes refused).

## Safety

- The **allowlist is empty by default** — nothing runs until you `sethu --allow "<cmd>"`
  (or turn on read-only mode, or — at your own risk — trust mode).
- A command runs only if it matches an allow entry exactly or as `"<entry> …"`,
  so `> rm -rf …` is refused unless explicitly allowed.
- ⚠️ The runner executes in your shell and **bypasses Claude Code's permission
  prompts**, so keep the allowlist tight — treat it like shell aliases.
- **Injection-hardened.** An allowlisted command may be followed by plain
  arguments only — *not* a pipe, redirect, `;`/`&&`, command substitution,
  backtick, or newline. So allowlisting `ls` does **not** permit
  `> ls | grep x | rm -rf x` or `> ls; rm -rf ~`; they're refused. (For piping
  between read-only commands, use `--readonly on`, which validates every stage.)
- Read-only mode allows only genuinely read-only programs and git subcommands
  (no `git config`/`stash`/`branch -d`, no `find -delete`, no redirection).
- The persistent-shell socket is created `0600` (owner-only).
- `cd` is exempt from the allowlist (it runs nothing — just moves the working
  directory).

## Statefulness modes

`sethu --mode <mode>` picks how much state persists between commands:

| Mode | `cd` persists | `export`/`source`/venv | New shell per command? |
| --- | --- | --- | --- |
| `stateless` | ❌ | ❌ | **yes** — a fresh `bash -c` each time |
| `cwd` (default) | ✅ | ❌ | **yes**, but the working dir is remembered in a temp file |
| `shell` | ✅ | ✅ | **no** — one persistent `bash` (PTY daemon) is reused |

In `shell` mode, one long-lived bash serves your commands over a Unix socket, so
`cd`, environment variables, `source`, and virtualenvs all carry across
commands — a genuine persistent shell. The daemon exits after 30 minutes idle.
Switching modes (`sethu --mode …`) auto-restarts it, and `sethu --restart`
clears it on demand for a fresh shell.

**Your aliases / functions / env** are *not* loaded by default — sethu runs a
clean `bash --norc` for predictability. To make `shell` mode load your shell rc
(so your aliases, functions, and exported vars work):

```
sethu --rc on      # shell mode runs your $SHELL and sources its rc (~/.zshrc, ~/.bashrc)
```

It restarts the shell so the change takes effect. Off by default (sourcing an rc
runs arbitrary startup code and is slower). The allowlist still applies — an
alias `hi` runs only if `hi` is allowed (or trust is on).

## Manage it

Type these as normal messages in the prompt box (no `!`) — the hook intercepts
`sethu …`, runs it locally, and blocks the model, so it's **free**. Bare `sethu`
(or `sethu --help`) shows the options. Both **flag** and **subcommand** styles
work: `sethu --mode shell` ≡ `sethu mode shell`, `sethu --allow "git status"` ≡
`sethu allow git status`.

```text
sethu                     # show options / help
sethu --allow "<cmd>"     sethu --unallow "<cmd>"
sethu --launch "<cmd>"    sethu --unlaunch "<cmd>"   # open <cmd> in a real terminal
sethu --readonly on       sethu --mode shell        sethu --prefix ">"
sethu --restart           # restart the persistent shell(s) — clears shell-mode state
sethu --runner            # show the current config (~/.claude/sethu.json)
```

Config lives in `~/.claude/sethu.json`:

```json
{ "prefix": ">", "mode": "cwd", "allow": ["git status", "ls"], "launch": [] }
```

## Tests

Stdlib only — no dependencies. Run them with:

```bash
python3 -m unittest discover -s tests -v
```

They cover the allowlist, read-only safety (injection/redirection/chaining are
refused), the interactive guard, all three statefulness modes (including the
persistent shell), the `>>` pipe, completion headers, and config round-trips.
GitHub Actions runs them on every push and PR (`.github/workflows/ci.yml`).

## Companion

sethu (the bridge) is published at
[claude-sethu](https://github.com/NamrataAShettar/claude-sethu).
[claude-yodha](https://github.com/NamrataAShettar/claude-yodha) is the warrior —
a status-line game for Claude Code. Different tools, same author.

## License

MIT
