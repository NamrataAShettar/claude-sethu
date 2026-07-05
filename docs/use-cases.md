# sethu use cases

Concrete ways people use sethu, with the commands they'd type. Two things decide
the style:

- **`> cmd`** — you see the output, **free** (the model never sees it). Read-only
  commands (git, ls, cat, grep, ps, jq…) work **out of the box**; anything that
  writes or installs needs `sethu --allow "cmd"` once.
- **`>> cmd`** — output is *also* sent to Claude (costs tokens) — use it when you
  want Claude to act on the result.
- **`sethu --launch "cmd"`** — interactive/full-screen programs, in a real pane.

---

## 1. Git — the most common use
Peek at repo state constantly without paying tokens or cluttering the chat.

```text
> git status
> git diff                 > git diff --staged
> git log --oneline -15
> git show HEAD            > git blame src/app.py
> git ls-files             > git describe --tags
>> git diff                # share with Claude: "review these changes"
```

Read-only git subcommands (`status`, `log`, `diff`, `show`, `blame`, `ls-files`,
`describe`, `rev-parse`, `shortlog`, `reflog`…) work out of the box. A few —
`branch`, `stash`, `remote`, `config` — can *also write* (`git branch -D`,
`git stash drop`, `git remote add`, `git config <key> <value>`), so they're **not**
auto-allowed. Permit them explicitly if you want them: `sethu --allow "git branch"`.

## 2. Filesystem & navigation
```text
> ls -la                   > ls -R src
> tree -L 2                > pwd
> find . -name "*.py"      > du -sh *      > df -h
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
Set up an environment once, then run a series of commands that share it:

```text
sethu --mode shell
> source .venv/bin/activate
> export API_ENV=staging
> cd services/api
>> pytest -q tests/smoke   # runs in that exact venv/dir, Claude sees the result
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
sethu --allow "npm test"   sethu --readonly off
sethu --mode shell         sethu --timeout 60
sethu --trust on           # ⚠ run anything (footgun)
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
