# Testing sethu

## Run the test suite

Stdlib only, no dependencies:

```bash
python3 -m unittest discover -s tests -v
```

Every feature and CLI argument maps to a test (there's a coverage table at the top
of `tests/test_sethu.py`, guarded by a meta-test that fails if any argument is
untested). CI runs the suite on every push and PR.

## Exercise a behavior directly (no Claude Code needed)

The engine is importable, so you can drive `process()` and the CLI without a
session. This is the quickest way to eyeball a specific behavior or output header:

```bash
python3 - <<'PY'
import sys, os, json, tempfile
sys.path.insert(0, 'hooks'); import _engine
p = os.path.join(tempfile.mkdtemp(), 'c.json')
open(p, 'w').write(json.dumps({"mode": "cwd", "trust": False, "color": True}))
os.environ['SETHU_CONFIG'] = p
print(_engine.process("> ls", {"session_id": "s", "cwd": "/tmp"})["block"])
PY
```

Set `"color": True` and don't set `NO_COLOR` to see the real colored header; pipe
through `cat -v` to reveal the raw ANSI codes.

## Test a branch live in Claude Code (before merging)

Your installed plugin only reflects released versions, so a feature branch won't
appear in the prompt box until you point the plugin at your local checkout. Then
`git checkout <branch>` + `/reload-plugins` tests that branch.

The repo's marketplace is named `sethu` (your installed plugin shows as
`sethu@sethu`), so an install from a local or branch source and the released one
can't both hold that name at once. Pick an option by what you're doing:

| Option | Tests | Setup / cleanup | Best for |
| --- | --- | --- | --- |
| **A. local marketplace** | your **live local files** | swap the `sethu` marketplace out, restore when done | ongoing local dev, flipping branches often |
| **B. `--plugin-dir` flag** | your **live local files** | **none** (per session; just relaunch without it) | a quick, throwaway test of local changes |
| **C. branch URL** | the **pushed** branch (a snapshot) | swap + restore, like A | reviewing a pushed PR branch as-is |

Substitute your own checkout path for `/path/to/claude-sethu` below.

**Where each command runs — this matters:**
- ` ```bash ` blocks (`git …`, `claude …`, `python3 …`) run in your **normal
  terminal / shell**.
- Lines starting with `/` (`/plugin …`, `/reload-plugins`) are typed in the
  **Claude Code prompt**. (They also work from a terminal as `claude plugin …`.)
- **Do NOT prefix a terminal command with sethu's `>` (or `!`).** That runs it
  *through* sethu's captured runner, which garbles interactive full-screen programs
  — including `claude` itself. `claude --plugin-dir …` in particular must be run at
  a plain shell prompt, not in a sethu prompt.

### Option A: local marketplace (persistent local dev)

1. Point the `sethu` marketplace at your working copy:
   ```
   /plugin marketplace remove sethu
   /plugin marketplace add /path/to/claude-sethu
   /plugin install sethu
   /reload-plugins
   ```
2. It references your **live files**, so to test a branch, check it out and reload:
   ```bash
   git checkout <branch>     # in a terminal
   ```
   ```
   /reload-plugins           # in Claude Code
   ```
3. When done, **restore the released plugin** (see below).

### Option B: `--plugin-dir` launch flag (quick throwaway, no cleanup)

A `--plugin-dir` copy overrides the installed plugin for that session only, so
there's nothing to remove/add and **nothing to undo**. In a **plain terminal**
(not a sethu prompt — this launches a whole new Claude Code session), check out the
branch you want and start Claude Code with the flag:

```bash
git checkout <branch>
claude --plugin-dir /path/to/claude-sethu
```

That opens a fresh session with the local plugin loaded (no `/reload-plugins`
needed at startup). Inside it, type `> ls` to see your changes. Switch branches
mid-session with `git checkout <branch>` in a terminal + `/reload-plugins` in the
prompt. To go back to the released plugin, just exit and start `claude` normally
next time.

### Option C: branch URL (review a pushed PR)

Tests the **pushed** branch (a snapshot), not uncommitted local edits. Same
`sethu`-name swap as A:

```
/plugin marketplace remove sethu
/plugin marketplace add https://github.com/NamrataAShettar/claude-sethu.git#<branch>
/plugin install sethu
/reload-plugins
```

Use the full git URL with `#<branch>` (the `owner/repo#branch` shorthand isn't
reliable yet). Pull newer pushes with `/plugin marketplace update sethu`. When
done, **restore the released plugin** (below).

### Refreshing after new commits

Nothing updates automatically — a push to the remote does not reach a running
session on its own. To pick up new changes:

- **A / B (live local files):** they reflect your local checkout, not the remote.
  If the change is already in your working tree (you made it, or it's on the branch
  you're on), just `/reload-plugins`. If it was pushed from elsewhere, `git pull`
  (or `git checkout <branch> && git pull`) first, then `/reload-plugins`.
- **C (pushed branch):** `/plugin marketplace update sethu`, then `/reload-plugins`.

(Python code edits are re-read fresh on the next `>` command, but run
`/reload-plugins` after any change to be sure — and always after a `hooks.json`,
plugin.json, or marketplace change.)

### Restore the released plugin (after Option A or C)

```
/plugin marketplace remove sethu
/plugin marketplace add NamrataAShettar/claude-sethu
/plugin install sethu
/reload-plugins
```

Option B needs no restore. **Note:** a local install follows whatever branch is
checked out, so make sure the repo is on the branch you want before `/reload-plugins`.

If an `install` step reports sethu is already installed, run `/plugin uninstall
sethu` first, then re-run it.
