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

sethu's marketplace is named `sethu`, so the installed copy and a local one can't
both use that name at once. Two ways to switch over:

### Option A: local marketplace (persists across sessions)

```
/plugin marketplace remove sethu               # free the name
/plugin marketplace add /path/to/claude-sethu  # your working copy
/plugin install sethu
/reload-plugins
```

The install references the live files, so to switch branches:

```bash
git checkout <branch>     # in a terminal
```
```
/reload-plugins           # in Claude Code
```

### Option B: launch flag (no marketplace changes)

A `--plugin-dir` copy takes precedence over the installed one for that session, so
no remove/add is needed:

```bash
claude --plugin-dir /path/to/claude-sethu
```

Then `git checkout <branch>` + `/reload-plugins` as above.

### Option C: a pushed branch, without local editing

```
/plugin marketplace add https://github.com/NamrataAShettar/claude-sethu.git#<branch>
```

Use the full git URL with `#<branch>`; the `owner/repo#branch` shorthand isn't
reliable yet.

### Restore the released plugin

```
/plugin marketplace remove sethu
/plugin marketplace add NamrataAShettar/claude-sethu
/plugin install sethu
/reload-plugins
```

**Note:** a local install follows whatever branch is currently checked out, so make
sure the repo is on the branch you want before you `/reload-plugins`.
