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
open(p, 'w').write(json.dumps({"mode": "cwd", "readonly": True, "color": True}))
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

Substitute your own checkout path for `/path/to/claude-sethu` below. The `/plugin …`
lines are in-session slash commands; the same works from a terminal as
`claude plugin …` (e.g. `claude plugin marketplace add`).

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
there's nothing to remove/add and **nothing to undo**. Check out the branch you
want, then start Claude Code with the flag:

```bash
git checkout <branch>
claude --plugin-dir /path/to/claude-sethu
```

Switch branches during the session with `git checkout <branch>` + `/reload-plugins`.
To go back to the released plugin, just exit and start `claude` normally next time.

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
