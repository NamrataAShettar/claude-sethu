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
/plugin marketplace add NamrataAShettar/sethu
/plugin install sethu
/reload-plugins
```

Optional launcher so you can type `sethu …` in a terminal too:

```bash
ln -s "$PWD/bin/sethu" /opt/homebrew/bin/sethu   # any dir on your PATH
```

## Safety

- The **allowlist is empty by default** — nothing runs until you `sethu --allow "<cmd>"`.
- A command runs only if it matches an allow entry exactly or as `"<entry> …"`,
  so `> rm -rf …` is refused unless explicitly allowed.
- ⚠️ The runner executes in your shell and **bypasses Claude Code's permission
  prompts**, so keep the allowlist tight — treat it like shell aliases.
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

```text
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

sethu is the bridge; [claude-yodha](https://github.com/NamrataAShettar/claude-yodha)
is the warrior — a status-line game for Claude Code. Different tools, same author.

## License

MIT
