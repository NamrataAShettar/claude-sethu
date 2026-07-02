# Token-thrifty commands — a CLAUDE.md snippet

Copy the section below into any project's `CLAUDE.md`. It steers Claude to keep
command output small, which is where most wasted tokens go (a command's output
lands in Claude's context, and context is what you pay for).

The guidance keeps the *signal* (errors, results, exit status) and drops the
*noise* (progress bars, hundreds of "step N" lines, re-dumped files).

---

```markdown
## Command output: keep it lean (saves tokens)

Command output enters my context and costs tokens, so:

- For verbose installs/builds/tests, wrap them in `quiet` so only a short tail,
  any error lines, and the exit code enter context:
      quiet npm install
      quiet --lines 40 pytest
  (`quiet` ships with the `sethu` plugin: github.com/NamrataAShettar/claude-sethu)
- If `quiet` isn't available, redirect verbose output to a log and read only
  what's needed:
      npm test > /tmp/test.log 2>&1; tail -30 /tmp/test.log
      # on failure, just the errors:
      grep -iE "error|fail|exception" /tmp/test.log | tail -20
- Prefer terse forms: `git status -s`, `git log --oneline -10`, `pip install -q`,
  `npm install --silent`, build tools' `--quiet`/`-q` flags.
- When re-reading a file, read only the specific lines you need, not the whole
  file, *unless* it may have changed since you last read it. Correctness comes
  first: if a file was edited, or a command's result could have changed (`git
  status` after edits, tests after code changes, a listing after a write), re-read
  or re-run it. Never rely on a stale earlier result to save tokens.
- When checking a condition, return a small answer, not a dump:
  `test -f foo && echo yes` rather than `ls -la`.
```

---

Why this works: it changes behavior on *every* command, with no code and no risk
of hiding something important — Claude still sees errors and exit codes, just not
the hundreds of lines of progress noise around them.

---

**Further reading.** Anthropic's cost guide has a section on exactly this —
[Reduce token usage](https://code.claude.com/docs/en/costs#reduce-token-usage),
specifically *"offload processing to hooks"* (filter a command's output before
Claude sees it) and *"delegate verbose operations to subagents."* sethu's `>`
(keep output out of context entirely) and `quiet` (shrink what does go in) are
drop-in levers for that same "a command's full output lands in context" problem.
