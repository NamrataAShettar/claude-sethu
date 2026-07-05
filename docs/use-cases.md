# sethu use cases

Concrete ways people use sethu, with the commands they'd type. Two things decide
the style:

- **`> cmd`** — you see the output, **free** (the model never sees it). A curated set
  of **gated** tools (ls, cat, grep, ps, jq, wc…) works **out of the box**; anything
  that can write or run other programs (git, find, npm…) needs `sethu --allow <tool>`
  once (that permits the whole tool, any flags).
- **`>> cmd`** — output is *also* sent to Claude (costs tokens) — use it when you
  want Claude to act on the result.
- **`sethu --launch "cmd"`** — interactive/full-screen programs, in a real pane.

---

## 1. Git — the most common use
Peek at repo state constantly without paying tokens or cluttering the chat. `git`
can write and (via config/aliases) run other programs, so it isn't gated — allow it
once, then all of git runs:

```text
sethu --allow git          # one-time; permits the whole `git` tool (any subcommand)
> git status
> git diff                 > git diff --staged
> git log --oneline -15
> git show HEAD            > git blame src/app.py
>> git diff                # share with Claude: "review these changes"
```

`--allow git` is whole-tool, so `git push` / `git reset --hard` run too — that's the
trade for a simple model (sethu warns you when you allow a tool that can run other
programs). It's your call: for inspection-only, just be mindful; for full control,
leave git un-allowed and run it in your own terminal.

## 2. Filesystem & navigation
`ls`/`pwd`/`du`/`df` are gated; `find` and `tree` can write/exec via a flag, so
`sethu --allow find` / `--allow tree` once to use them.
```text
> ls -la                   > ls -R src        > pwd
> du -sh *                 > df -h
sethu --allow find         > find . -name "*.py"
```

## 3. Reading files & config (keeps big files out of context)
```text
> cat package.json         > head -50 README.md
> cat tsconfig.json        > grep -n "TODO" -r src
> jq '.scripts' package.json
>> cat error.log           # share a log/config with Claude to debug
```

## 4. Build / test / lint
Depends on who needs the result:

```text
sethu --allow "npm test"   # allow once (it writes / hits the network)
> npm test                 # you check it, free
>> npm test                # tests fail, let Claude see and fix (costs tokens)
> pytest -q                > make lint       > tsc --noEmit
```

## 5. Environment & system diagnostics
```text
> printenv | grep API      > echo $PATH
> ps aux | grep node       > uname -a       > whoami
> uptime                   > date           > which python3
```

## 6. Dependencies (installs need --allow)
```text
> cat requirements.txt     > jq '.dependencies' package.json
sethu --allow "npm ls"  →  > npm ls --depth=0
sethu --allow "pip show"→  > pip show requests
```

## 7. Persistent shell workflows (`sethu --mode shell`)
Set up an environment once, then run a series of commands that share it. `export`
and `cd` (and other state builtins) work out of the box in shell mode; `source` runs
a file's contents, so you allow it once.

```text
sethu --mode shell
sethu --allow source          # source runs a file — allow it once (venv activation)
> source .venv/bin/activate    # activates, and persists to the commands below
> export API_ENV=staging       # sets shell state, out of the box
> cd services/api              # navigation, out of the box
>> pytest -q tests/smoke       # runs in that exact venv/dir (allow pytest first)
```

## 8. Logs & data inspection
```text
> grep -c ERROR app.log    > tail -100 app.log
> jq '.users | length' data.json
>> tail -50 app.log        # "here's what's failing, diagnose it"
```

## 9. Quick lookups / scratchpad
```text
> date     > cal     > df -h     > echo $HOME     > cat /etc/hosts
```

## 10. Interactive / full-screen → `--launch`
Things the captured runner can't do (no terminal):

```text
sethu --launch "vim notes.md"     sethu --launch "top"
sethu --launch "ssh myserver"     sethu --launch "python3"    # REPL
sethu --launch "lazygit"          sethu --launch "less big.log"
```

## 11. Deliberately feeding Claude a specific result (`>>`)
When you *want* the tokens spent because Claude should act on it:

```text
>> git diff                        # review my changes
>> cat build-error.txt             # fix this error
>> curl -s localhost:3000/health   # (allow curl) share the API response
```

## 12. Managing sethu
```text
sethu                      # options menu
sethu --allow git          sethu --gated-list
sethu --mode shell         sethu --timeout 60
sethu --trust on           # ⚠ run anything, gate off (footgun)
sethu --runner             # show config
```

---

## Who benefits most

- **Pro / Max users** hitting rate limits — free inspections don't count against them.
- **Metered-API users** — every `>` is a query you didn't pay for.
- **Long sessions** — keeping command output out of context delays auto-compaction
  and keeps Claude sharp longer.
- **Anyone mid-task** who just wants to *look* at something without derailing the
  conversation.
</content>
