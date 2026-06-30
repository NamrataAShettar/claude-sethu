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

> Why this is free (and `!` isn't): bang mode adds output to context and (since
> Claude Code v2.1.186) makes Claude respond — that costs tokens. sethu blocks
> the prompt entirely, so nothing reaches the model unless you ask with `>>`.

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

## Safety

- The **allowlist is empty by default** — nothing runs until you `sethu --allow "<cmd>"`
  (or turn on read-only mode).
- A command runs only if it matches an allow entry exactly or as `"<entry> …"`,
  so `> rm -rf …` is refused unless explicitly allowed.
- ⚠️ The runner executes in your shell and **bypasses Claude Code's permission
  prompts**, so keep the allowlist tight — treat it like shell aliases. (Note:
  an explicit `--allow "git log"` lets you append `> git log …` including pipes,
  so don't allowlist a command you wouldn't trust with arbitrary trailing args;
  read-only mode is the injection-hardened option.)
- `cd` is exempt from the allowlist (it runs nothing — just moves the working
  directory).

## Statefulness modes

`sethu --mode <mode>` picks how much state persists between commands:

| Mode | `cd` persists | `export` / `source` / venv | How |
| --- | --- | --- | --- |
| `stateless` | ❌ | ❌ | each command is its own subprocess |
| `cwd` (default) | ✅ | ❌ | a per-session working directory is tracked |
| `shell` | ✅ | ✅ | a real persistent `bash` behind a PTY daemon |

In `shell` mode, one long-lived bash serves your commands over a Unix socket, so
`cd`, environment variables, `source`, and virtualenvs all carry across
commands — a genuine persistent shell. The daemon exits after 30 minutes idle.

## Manage it

Type these as normal messages in the prompt box (no `!`) — the hook intercepts
`sethu …`, runs it locally, and blocks the model, so it's **free**. Bare `sethu`
(or `sethu --help`) shows the options.

```text
sethu                     # show options / help
sethu --allow "<cmd>"     sethu --unallow "<cmd>"
sethu --launch "<cmd>"    sethu --unlaunch "<cmd>"   # open <cmd> in a real terminal
sethu --mode shell        sethu --prefix ">"
sethu --runner            # show the current config (~/.claude/sethu.json)
```

Config lives in `~/.claude/sethu.json`:

```json
{ "prefix": ">", "mode": "cwd", "allow": ["git status", "ls"], "launch": [] }
```

## Companion

sethu (the bridge) is published at
[claude-sethu](https://github.com/NamrataAShettar/claude-sethu).
[claude-yodha](https://github.com/NamrataAShettar/claude-yodha) is the warrior —
a status-line game for Claude Code. Different tools, same author.

## License

MIT
