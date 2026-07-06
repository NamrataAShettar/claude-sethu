#!/usr/bin/env python3
"""Tests for sethu's engine. Stdlib only. Run with:

    python3 -m unittest discover -s tests -v
    # or: python3 tests/test_sethu.py

COVERAGE TABLE. Every feature and CLI argument maps to a test. When you add a
feature or argument, add a row here, write its test, and tick it. Keep in sync.

  Feature / CLI arg                      Test class(es)                        Done
  -------------------------------------  ------------------------------------  ----
  > cmd (run, block from model)          TestRunner, TestSafety                 [x]
  >> cmd (run + send to Claude)          TestRunner, TestHookOutput             [x]
  passthrough (non-sethu prompt)         TestRunner, TestLeadingWhitespace,     [x]
                                         TestHookOutput
  prefix only triggers at line start     TestLeadingWhitespace                  [x]
  --allow                                TestConfig, TestSafety,                [x]
                                         TestRefusalMessages
  --unallow                              TestConfig                             [x]
  --launch / --unlaunch                  TestLaunch, TestConfig                 [x]
  truthful add/remove + empty/multispace TestManagementCLI                     [x]
  --mode stateless/cwd/shell             TestModeSwitching, TestCwdMode,        [x]
                                         TestShellMode
  gated model (tool set, no flag logic)  TestGatedFn, TestSafety, TestConfig    [x]
  --trust on/off (one safety knob)       TestTrust                              [x]
  --rc on/off (+ aliases actually work)  TestConfig, TestRcAliases              [x]
  state builtins auto-run; source gated  TestStateBuiltinHint                   [x]
  --color on/off                         TestColor, TestConfig                  [x]
  --plain on/off (spoken/screen-reader)  TestPlainMode                          [x]
  --maxlines (truncation)                TestTruncate, TestConfig               [x]
  --timeout                              TestTimeout, TestConfig                [x]
  --prefix (custom trigger)              TestCustomPrefix, TestConfig,          [x]
                                         TestHookGate
  --restart                              TestManagementCLI, TestKillDaemons     [x]
  --runner / --show (config)             TestManagementCLI, TestHookOutput      [x]
  bare `sethu` (help menu)               TestManagementCLI                      [x]
  branded/colored CLI errors             TestManagementCLI                      [x]
  subcommand aliases (mode shell = …)    TestNormalizeArgv                      [x]
  interactive guard (REPL/version/help)  TestInteractiveFn, TestSafety,         [x]
                                         TestRefusalMessages
  full-screen TUIs (claude/…) + hint     TestFullScreenTUI                      [x]
  gated safety (injection / chain)       TestGatedFn, TestSafety                [x]
  --allow whole-tool + launcher warning  TestManagementCLI, TestGatedFn         [x]
  bare-cd guard (chain not exempt)       TestSafety, TestShellMode              [x]
  --gated-list (built-in + yours)        TestManagementCLI                      [x]
  every response opens with |^=^| ·       TestEveryResponseLeadsWithIcon         [x]
  refusal messages explain why           TestRefusalMessages                    [x]
  timeout message cites hook budget      TestRefusalMessages                    [x]
  long-output truncation + temp file     TestTruncate                           [x]
  temp-file sweep                        TestSweep                              [x]
  socket path + 0600 perms               TestSocketPath, TestSocketPerms        [x]
  kill / reap shell daemons              TestKillDaemons                        [x]
  timeout recovery (no wedge/bleed) H3   TestShellMode                          [x]
  output byte-cap (RAM/disk) ST1/ST7     TestOutputCap / TestShellMode          [x]
  daemon-spawn lock (L7, flock) / marker  TestSpawnLock / TestFirstRunHint       [x]
  config/cwd durability (atomic+flock)    TestConfigDurability                   [x]
  first-run welcome hint                 TestFirstRunHint                       [x]
  hook fast-path gate                    TestHookGate                           [x]
  hook output JSON shapes                TestHookOutput                         [x]
  python3-missing shim (run.sh)          TestPython3Shim                        [x]
  icon constant + header separator       TestIcon                               [x]
  header format (dot-sep, status/runs)   TestHeaderFormat                       [x]
  every CLI arg is referenced (guard)    TestCoverageEnforcement                [x]
  malformed config: type + value guard   TestConfig                             [x]
  unterminated-quote command refused     TestHookOutput                         [x]
  first-run hint skips if unwritable     TestFirstRunHint                       [x]
  orphaned socket + cwd file swept       TestSweep                              [x]
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest

HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
sys.path.insert(0, HOOKS)
import _engine  # noqa: E402
import _shelld  # noqa: E402
import sethu_hook  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "sethu.json")
        os.environ["SETHU_CONFIG"] = self.cfg
        self.write()

    def tearDown(self):
        os.environ.pop("SETHU_CONFIG", None)

    def write(self, **kw):
        c = {"prefix": ">", "mode": "cwd", "allow": [], "launch": [], "trust": False}
        c.update(kw)
        with open(self.cfg, "w") as f:
            json.dump(c, f)

    def proc(self, prompt, sid="t", cwd=None):
        return _engine.process(prompt, {"session_id": sid, "cwd": cwd or self.tmp})

    def _shutdown(self, sid):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(_engine._sock_path(sid))
            s.sendall(b"__SETHU_SHUTDOWN__\n")
            s.close()
        except Exception:
            pass


class TestGatedFn(unittest.TestCase):
    """The gated model: a tool auto-runs (trust off) iff its program is in GATED and
    the command has no chaining/redirection/substitution. NO flag logic — a tool is
    gated only if it's harmless with any flags, so git/find/fd/sort/etc are NOT gated
    (they need --allow), and a gated tool runs with ANY flags."""
    def test_gated(self):
        # gated tools, with any flags, and pipes of gated tools.
        for c in ["ls", "ls -la", "cat f | head", "pwd", "grep -n x f | head -5",
                  "date", "jq . x.json", "wc -l f"]:
            self.assertTrue(_engine.is_gated(c), c)

    def test_not_gated_tools_need_allow(self):
        # tools that can write/exec via a flag/operand aren't gated (any invocation).
        for c in ["git log", "git push", "find . -name x", "find . -delete",
                  "fd foo", "rg pat", "sort f", "sort -o out f", "xxd f", "yq . x",
                  "npm test", "bat f", "sed -n p f", "awk '{}' f"]:
            self.assertFalse(_engine.is_gated(c), c)

    def test_chaining_never_gated(self):
        # the chain guard: no gated command may chain/redirect/substitute.
        for c in ["ls; rm -rf ~", "ls && rm", "ls || rm", "echo x > f", "cat f >> g",
                  "cat f | sh", "$(rm)", "ls `rm`", "ls & rm", "cat <(rm)"]:
            self.assertFalse(_engine.is_gated(c), c)

    def test_no_exec_wrappers(self):
        # env / command are generic launchers — never gated.
        for c in ["env rm -rf x", "env FOO=1 sh -c id", "command rm -rf x"]:
            self.assertFalse(_engine.is_gated(c), c)

    def test_pipe_inside_quotes_is_not_a_chain(self):
        # A `|` INSIDE a quoted argument is literal text, not a shell pipe, so a gated
        # tool with such an arg stays gated (use-cases.md UC 8: `jq '.users | length'`
        # was wrongly refused by a naive `cmd.split("|")`).
        for c in ['jq ".users | length" data.json', "jq '.a | .b' f.json",
                  'grep "a|b" file', 'grep "x|y" f | wc -l']:
            self.assertTrue(_engine.is_gated(c), c)

    def test_real_pipe_to_non_gated_still_refused(self):
        # The fix must NOT weaken the guard: an UNQUOTED pipe to a non-gated tool is
        # still refused, and a real pipe of gated tools still runs.
        self.assertFalse(_engine.is_gated('jq ".x" f | rm -rf ~'), "unquoted pipe to rm")
        self.assertFalse(_engine.is_gated("cat f | sh"), "pipe to sh")
        self.assertTrue(_engine.is_gated("cat f | grep x | head"), "gated pipeline")

    def test_why_refused_not_gated(self):
        # A non-gated tool's refusal names it and says it's not gated (the `--allow`
        # pointer is in the refusal's bullets, not this reason line).
        msg = _engine._why_refused("npm test", {})
        self.assertIn("npm", msg)
        self.assertIn("run it automatically", msg)   # explains it's not auto-run
        self.assertNotIn("--allow", msg)   # reason-only; actions live in the bullets

    def test_why_refused_source_is_gated_exception(self):
        # source/. execute a file → not gated even though they're builtins.
        msg = _engine._why_refused("source venv/bin/activate", {})
        self.assertIn("contents of a file", msg)
        self.assertNotIn("--allow", msg)   # reason-only; actions live in the bullets

    def test_gated_set_excludes_write_exec_capable_tools(self):
        # INVARIANT (from the flag-safety audit): no tool that can write/delete a
        # file or execute another program via SOME flag/operand may be in GATED —
        # that's the whole point of dropping flag policing. If you add one of these
        # to GATED, this fails: put it behind --allow instead.
        forbidden = {
            "git", "find", "fd", "rg", "sort", "uniq", "xxd", "yq", "tree", "file",
            "env", "command", "sed", "awk", "gawk", "xargs", "tee", "sudo", "sh",
            "bash", "python", "python3", "perl", "node", "less", "vi", "vim",
        }
        leaked = forbidden & _engine.GATED
        self.assertEqual(leaked, set(), f"write/exec-capable tools leaked into GATED: {leaked}")


class TestHookGate(Base):
    """The cheap prefix/`sethu` gate in sethu_hook that decides, without importing
    the engine, whether a prompt could be for sethu."""
    def test_is_sethu_command(self):
        S = _engine.SUBCOMMANDS
        self.assertTrue(sethu_hook.is_sethu_command("sethu", S))
        self.assertTrue(sethu_hook.is_sethu_command("sethu --mode shell", S))
        self.assertTrue(sethu_hook.is_sethu_command("sethu mode shell", S))
        self.assertFalse(sethu_hook.is_sethu_command("sethu is great", S))
        self.assertFalse(sethu_hook.is_sethu_command("tell me about sethu", S))

    def test_maybe_sethu_default_prefix(self):
        self.write()  # default prefix ">"
        self.assertTrue(sethu_hook._maybe_sethu("> ls"))
        self.assertTrue(sethu_hook._maybe_sethu("   > ls"))     # leading space
        self.assertTrue(sethu_hook._maybe_sethu("sethu --runner"))
        self.assertFalse(sethu_hook._maybe_sethu("just a normal message"))

    def test_maybe_sethu_custom_prefix(self):
        self.write(prefix="!!")
        self.assertTrue(sethu_hook._maybe_sethu("!! ls"))
        self.assertFalse(sethu_hook._maybe_sethu("regular text"))

    def test_fast_path_skips_engine_import(self):
        # Every-prompt perf guard: a NON-sethu prompt must NOT import _engine (the
        # heavy module). Deterministic stand-in for "sethu's overhead is sub-ms" —
        # wall-clock isn't CI-stable, this is.
        self.write()
        hook = os.path.join(HOOKS, "sethu_hook.py")

        def imports_engine(prompt):
            r = subprocess.run([sys.executable, "-X", "importtime", hook],
                               input=prompt, capture_output=True, text=True,
                               env=dict(os.environ, SETHU_CONFIG=self.cfg))
            return "_engine" in r.stderr   # -X importtime writes to stderr

        self.assertFalse(imports_engine('{"prompt":"just a normal message"}'))
        self.assertTrue(imports_engine('{"prompt":"> ls"}'))  # loaded only on demand


class TestInteractiveFn(unittest.TestCase):
    def test(self):
        self.assertTrue(_engine.is_interactive("vim file"))
        self.assertTrue(_engine.is_interactive("top"))
        self.assertTrue(_engine.is_interactive("claude --plugin-dir ~/x"))  # TUI
        self.assertTrue(_engine.is_interactive("lazygit"))
        self.assertFalse(_engine.is_interactive("ls -la"))
        self.assertFalse(_engine.is_interactive(""))

    def test_bare_repl_is_interactive(self):
        for c in ["python", "python3", "node", "ipython", "irb",
                  "python -i", "python -i script.py"]:
            self.assertTrue(_engine.is_interactive(c), c)

    def test_interpreter_with_script_is_batch(self):
        # A script / -c / -m makes the interpreter run and exit — captureable.
        for c in ["python script.py", "python3 app.py --flag x",
                  'python -c "print(1)"', "python -m http.server",
                  "node app.js", 'node -e "console.log(1)"',
                  "python -u worker.py"]:
            self.assertFalse(_engine.is_interactive(c), c)

    def test_version_help_flags_are_batch(self):
        # M3: version/help flags print and exit — batch, not an interactive REPL,
        # so they must run captured (not get the wrong --launch hint).
        for c in ["python --version", "python -V", "python3 --help", "python -h",
                  "node --version", "node -v", "node -p 1", "node --eval x"]:
            self.assertFalse(_engine.is_interactive(c), c)

    def test_prompt_preserving_flags_still_interactive(self):
        # …but a bare interpreter with only prompt-preserving flags still opens a
        # REPL (python -v is verbose, NOT version), so it stays interactive.
        for c in ["python -q", "python -u", "python -O", "python -v"]:
            self.assertTrue(_engine.is_interactive(c), c)

    def test_more_repls_bare_is_interactive(self):
        # We support more than python/node: any dual-mode interpreter's BARE form
        # is a REPL (refuse, point at --launch).
        for c in ["deno", "php -a", "lua", "R", "julia", "clj", "tclsh",
                  "redis-cli", "mongosh", "pypy", "scala"]:
            self.assertTrue(_engine.is_interactive(c), c)

    def test_more_repls_with_script_or_command_is_batch(self):
        # …but running something with them (a script / -e code / a subcommand) is
        # batch and must still be captured, not refused.
        for c in ["deno run app.ts", "php index.php", "lua build.lua",
                  "Rscript analyze.R", "julia run.jl", 'redis-cli GET mykey',
                  'mongosh --eval "db.x.find()"', "R --version",
                  "php -v", "lua -v", "julia -v"]:   # -v = version (batch) off python
            self.assertFalse(_engine.is_interactive(c), c)

    def test_python_dash_v_stays_interactive_not_version(self):
        # The outlier: python -v is VERBOSE, not version, so it still opens a REPL.
        self.assertTrue(_engine.is_interactive("python -v"))
        self.assertTrue(_engine.is_interactive("python3 -v"))

    def test_always_interactive_repls_and_debuggers(self):
        # REPLs/debuggers with no useful captured form are unconditionally
        # interactive (the batch tool is a different command).
        for c in ["ghci", "iex", "erl", "gdb ./a.out", "lldb ./a.out"]:
            self.assertTrue(_engine.is_interactive(c), c)


class TestSafety(Base):
    def test_not_allowed_refused(self):
        r = self.proc("> rm -rf /tmp/x")
        self.assertIn("gated", r["block"])

    def test_gated_blocks_dangerous(self):
        self.write()
        for c in ["ls; rm -rf ~", "echo x > /tmp/f", "cat README | sh", "git push"]:
            self.assertIn("gated", self.proc("> " + c)["block"], c)

    def test_interactive_allowlisted_is_refused(self):
        self.write(allow=["vi"])
        self.assertIn("interactive", self.proc("> vi")["block"])

    def test_bare_cd_guard(self):
        # H4: only a simple cd is allowlist-exempt; a chained/substituted cd is not.
        for c in ["cd", "cd /tmp", "cd ..", "cd 'a dir'"]:
            self.assertTrue(_engine._is_bare_cd(c), c)
        for c in ["cd /tmp; rm -rf ~", "cd /tmp && rm", "cd $(evil)", "cd `evil`",
                  "cd x | sh", "cd x > f"]:
            self.assertFalse(_engine._is_bare_cd(c), c)

    def test_chained_cd_refused_not_exempt(self):
        # H4: a chained cd must hit the normal gate (refused), not the cd exemption.
        self.write()
        self.assertIn("gated", self.proc("> cd /tmp; rm -rf ~")["block"])

    def test_allowlist_no_pipe_injection(self):
        # Allowing `ls` must NOT permit `ls | rm -rf x` (the reported bug).
        self.write(allow=["ls"])
        self.assertIn("gated", self.proc("> ls | grep x | rm -rf x")["block"])
        self.assertIn("gated", self.proc("> ls; rm -rf x")["block"])
        self.assertIn("gated", self.proc("> ls && rm -rf x")["block"])
        self.assertIn("gated", self.proc("> ls $(rm)")["block"])
        # but plain args are still fine
        self.assertNotIn("gated", self.proc("> ls -la")["block"])

    def test_allowlist_no_newline_injection(self):
        self.write(allow=["ls"])
        self.assertIn("gated", self.proc("> ls\nrm -rf x")["block"])

    def test_quoted_metachars_are_allowed(self):
        # A `;`/`|` INSIDE quotes is argument text, not a command chain, so an
        # allowlisted interpreter with a `-c` one-liner is permitted.
        self.write(allow=["python3", "echo"])
        for c in ['python3 -c "import os; print(os.getpid())"',
                  "python3 -c 'a; b; c'",
                  'echo "a|b;c"']:
            self.assertNotIn("gated", self.proc("> " + c)["block"], c)

    def test_unquoted_ops_still_refused_with_interpreter(self):
        # But a real unquoted chain after the interpreter is still refused.
        self.write(allow=["python3"])
        for c in ['python3 -c "print(1)" ; rm -rf x',
                  "python3 -c \"print(1)\" | sh",
                  'python3 script.py > /etc/passwd',
                  'python3 -c "print(1)" && rm x']:
            self.assertIn("gated", self.proc("> " + c)["block"], c)

    def test_command_substitution_refused_even_quoted(self):
        # $( ) and backticks EXECUTE even inside quotes → always refused, even for a
        # gated/allowed tool. (Plain ${VAR} parameter expansion is harmless and runs.)
        self.write(allow=["echo"])
        for c in ['echo "$(rm -rf x)"', 'echo "`rm`"']:
            self.assertIn("gated", self.proc("> " + c)["block"], c)

    def test_gated_no_newline_injection(self):
        self.write()
        self.assertIn("gated", self.proc("> ls\nrm -rf x")["block"])

    def test_git_writes_refused(self):
        self.write()
        for c in ["git config user.name hacked", "git stash", "git branch -D main",
                  "git tag -d v1", "git remote add evil url"]:
            self.assertIn("gated", self.proc("> " + c)["block"], c)


class TestManagementCLI(Base):
    """Management args whose *execution* path (not just argv normalization) needs
    coverage: bare help, --runner/--show, --restart."""
    def _out(self, argv):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _engine.main(argv)
        return buf.getvalue()

    def test_bare_prints_help_menu(self):
        out = self._out([])
        for t in ["sethu:", "> cmd", ">> cmd", "--allow", "--launch", "--runner",
                  "Gated by default"]:
            self.assertIn(t, out, t)

    def test_runner_and_show_print_config(self):
        for flag in (["--runner"], ["--show"]):
            out = self._out(flag)
            self.assertIn("mode:", out, flag)
            self.assertIn("default", out, flag)   # shows each field's default
            self.assertIn("session's working dir", out, flag)  # where `>` runs

    def test_restart_reports(self):
        self.assertIn("restarted", self._out(["--restart"]))

    def test_allow_truthful_add_vs_duplicate(self):
        # M4/UX8: ✔ added only when it actually changed; a duplicate says so.
        self.write(allow=[])
        self.assertIn("✔ added to allow", self._out(["--allow", "npm test"]))
        out = self._out(["--allow", "npm test"])           # second time
        self.assertIn("already allowed", out)
        self.assertNotIn("✔ added", out)

    def test_unallow_truthful_present_vs_absent(self):
        # M4: ✔ removed only when the entry existed; otherwise "not in the list".
        self.write(allow=["npm test"])
        self.assertIn("✔ removed", self._out(["--unallow", "npm test"]))
        out = self._out(["--unallow", "neverexisted"])
        self.assertIn("not in the allowlist", out)
        self.assertNotIn("✔ removed", out)

    def test_unlaunch_absent_is_truthful(self):
        self.write(launch=[])
        self.assertIn("not in the launch list", self._out(["--unlaunch", "nope"]))

    def test_multispace_entry_is_removable(self):
        # M4: a multi-space allow must be removable via the (space-collapsing)
        # subcommand style — both canonicalize to one entry.
        self.write(allow=[])
        self._out(["--allow", "a   b"])                     # stored canonical
        cfg = _engine.load_config()
        self.assertEqual(cfg["allow"], ["a b"])
        self.assertIn("✔ removed", self._out(["--unallow", "a b"]))
        self.assertEqual(_engine.load_config()["allow"], [])

    def test_legacy_multispace_entry_canonicalized_on_load(self):
        # LOW-2: an entry stored raw (older version / hand-edit) with multiple
        # spaces is canonicalized when loaded, so it's removable AND can match.
        self.write(allow=["a   b"])
        self.assertEqual(_engine.load_config()["allow"], ["a b"])
        self.assertIn("✔ removed", self._out(["--unallow", "a b"]))
        self.assertEqual(_engine.load_config()["allow"], [])

    def test_empty_arg_says_nothing_not_config_dump(self):
        # UX10: `--allow ""` must say so, not silently dump the whole config.
        self.write(allow=[])
        for flag in ("--allow", "--unallow", "--launch", "--unlaunch"):
            out = self._out([flag, ""])
            self.assertIn("nothing to", out, flag)
            self.assertNotIn("sethu config", out, flag)  # not the --runner view

    def test_allow_launcher_warns(self):
        # --allow'ing a launcher (git/sh/env/…) ≈ trust for that tool, so warn — but
        # still allow it (user discretion). A non-launcher tool gets no warning.
        self.write(allow=[])
        for tool in ("git", "sh", "python3", "xargs"):
            out = self._out(["--allow", tool])
            self.assertIn("✔ added", out)
            self.assertIn("run other programs", out, tool)
        self.write(allow=[])
        self.assertNotIn("run other programs", self._out(["--allow", "npm test"]))

    def test_gated_list_shows_builtin_and_yours(self):
        self.write(allow=["git", "npm test"])
        out = self._out(["--gated-list"])
        for t in ["ls", "jq", "cd",                        # built-in gated names
                  "you allowed", "git", "npm test",        # your allowed tools, labeled
                  "--trust on"]:                           # the trust pointer
            self.assertIn(t, out, t)
        self.assertNotIn("git", out.split("you allowed")[0])  # git is NOT a built-in
        # Sorted → stable output (set iteration order is not).
        self.assertEqual(out, self._out(["--gated-list"]))

    def test_bad_arg_error_is_branded(self):
        # A bad flag gives a branded, concise error (icon + 'error:' + menu
        # pointer), not argparse's plain usage wall.
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), self.assertRaises(SystemExit):
            _engine.main(["--mode", "nope"])
        err = buf.getvalue()
        self.assertIn(_engine.ICON, err)          # icon brands it (no doubled "sethu:")
        self.assertIn("error:", err)
        self.assertNotIn("sethu: error:", err)    # the redundant prog prefix is gone
        self.assertIn("options menu", err)


class TestHeaderFormat(Base):
    """Pins the exact header across permutations (color off), so a spacing or
    separator regression fails here instead of by eye. Catches the class of bug
    where a part (e.g. ⚠trust) wasn't `·`-separated."""
    def test_run_header(self):
        self.write(color=False)
        h = self.proc("> ls")["block"].split("\n")[0]
        self.assertEqual(h, "|^=^| · [cwd] · ✓ exit 0 · $ ls")

    def test_refusal_header_omits_status(self):
        self.write(color=False)
        h = self.proc("> git branch")["block"].split("\n")[0]
        self.assertEqual(h, "|^=^| · [cwd] · $ git branch")

    def test_trust_segment_is_dot_separated(self):
        # regression: ⚠trust used to be space-glued to the [mode] tag.
        self.write(mode="shell", trust=True, color=False)
        h = self.proc("> claude")["block"].split("\n")[0]  # interactive refusal
        self.assertEqual(h, "|^=^| · [shell] · ⚠trust · $ claude")


class TestFullScreenTUI(Base):
    def test_known_tui_refused_as_interactive(self):
        # claude / lazygit / etc. are in the interactive list -> upfront --launch.
        self.write(color=False)
        self.assertIn("interactive", self.proc("> claude --plugin-dir ~/x")["block"])

    def test_unknown_tui_alt_screen_gets_hint(self):
        # A TUI captured mid-draw emits the alt-screen escape AND fails/times out;
        # sethu detects the escape (on a non-clean exit) and points at --launch.
        self.write(mode="stateless", trust=True, color=False)
        b = self.proc(r"> printf '\033[?1049hUI'; false")["block"]  # escape, exit 1
        self.assertIn("full-screen program", b)
        self.assertIn("--launch", b)

    def test_alt_screen_on_clean_exit_no_hint(self):
        # A command that legitimately prints those bytes and exits 0 must NOT trip
        # the hint (false-positive guard).
        self.write(mode="stateless", trust=True, color=False)
        self.assertNotIn("full-screen program",
                         self.proc(r"> printf '\033[?1049hUI'")["block"])

    def test_plain_output_gets_no_hint(self):
        self.write(color=False)
        self.assertNotIn("full-screen program", self.proc("> ls")["block"])

    def test_command_ansi_is_reset_to_prevent_bleed(self):
        # A command that leaves a colour/attribute open gets a trailing reset so it
        # doesn't bleed into the rest of the transcript. Plain output doesn't.
        self.write(trust=True, color=False)
        self.assertTrue(self.proc(r"> printf '\033[33mopen'")["block"].endswith("\x1b[0m"))
        self.assertFalse(self.proc("> printf plain")["block"].endswith("\x1b[0m"))


class TestRefusalMessages(Base):
    def test_interactive_leads_with_launch_not_allow(self):
        # Interactive commands point to --launch (allowlisting can't make them run).
        self.write(color=False)
        for c in ["vim", "python3", "top"]:
            b = self.proc("> " + c)["block"]
            self.assertIn("--launch", b, c)
            self.assertIn("interactive", b, c)
            self.assertNotIn('sethu --allow', b, c)   # allow is futile here

    def test_refusal_explains_why_and_still_offers_allow(self):
        self.write(color=False)
        # A non-gated tool: explain why (can change files / run programs) + offer --allow.
        for cmd in ("git log", "sort -o out f", "npm test"):
            b = self.proc("> " + cmd)["block"]
            self.assertIn("change files or run other programs", b, cmd)
            self.assertIn("sethu --allow", b, cmd)   # allowing the tool IS the fix
        # A chain can't be fixed by allowing a tool → no "Allow this tool" bullet, but
        # the reason explains it and --launch/--trust remain.
        b = self.proc("> ls; rm -rf ~")["block"]
        self.assertIn("joined by", b)
        self.assertNotIn("sethu --allow", b)
        self.assertIn("sethu --launch", b)

    def test_timeout_message_mentions_hook_budget(self):
        self.assertIn("hook budget", _engine._timeout_msg(20, "sleep 99"))

    def test_refusal_has_unified_header_without_status(self):
        # Every response shares the header format; a refusal echoes the command but
        # omits the exit-status slot (it never ran), so it can't be mislabelled.
        self.write(color=False)
        first = self.proc("> git branch")["block"].split("\n")[0]
        self.assertIn("[cwd]", first)          # mode tag
        self.assertIn("$ git branch", first)   # command echoed in the header
        self.assertNotIn("exit", first)        # but NO exit status
        # a real run DOES show a status
        self.assertIn("exit 0", self.proc("> ls")["block"].split("\n")[0])

    def test_refusal_offers_actionable_next_step(self):
        # A chain points to running parts separately; a non-gated tool points to
        # allowing that tool.
        self.write(color=False)
        self.assertIn("separate", self.proc("> ls; rm -rf ~")["block"])
        self.assertIn('--allow "npm"', self.proc("> npm test")["block"])

    def test_unknown_command_is_not_labelled_dangerous(self):
        # A typo / uninstalled tool isn't a safety wall — it says "can't find", NOT the
        # scary "can change files or run other programs" (which reads as if a mistyped
        # word were dangerous). The allow/trust/launch *bullets* are dropped too — they
        # can't run a command that doesn't exist.
        self.write(color=False)
        b = self.proc("> notacommand123xyz")["block"]
        self.assertIn("isn't a command sethu can find", b)
        self.assertNotIn("change files or run other programs", b)
        self.assertNotIn("--trust on", b)          # the bullet menu is suppressed
        self.assertNotIn("See what's gated", b)

    def test_real_dangerous_command_keeps_safety_message(self):
        # A command that DOES exist and can write/exec keeps the safety framing — the
        # not-found refinement must not weaken the real guardrail. (`rm` is on PATH.)
        self.write(color=False)
        b = self.proc("> rm foo")["block"]
        self.assertIn("change files or run other programs", b)
        self.assertIn('sethu --allow "rm"', b)     # and the full menu is present

    def test_unknown_command_stays_generic_in_shell_mode(self):
        # In shell mode a name may resolve to a user function/alias/PATH we can't see,
        # so we must NOT claim it's unknown — keep the generic refusal there.
        self.write(color=False, mode="shell")
        b = self.proc("> notacommand123xyz")["block"]
        self.assertIn("change files or run other programs", b)
        self.assertNotIn("isn't a command sethu can find", b)

    def test_unbalanced_quote_gets_friendly_hint_not_shell_error(self):
        # An unbalanced quote must NOT leak the raw `/bin/sh: unexpected EOF` — it gets
        # the same friendly "unbalanced quote" guidance the management CLI gives.
        self.write(color=False)
        for p in ('> echo "hi', ">> echo 'hi", '> cat "a b'):
            b = self.proc(p)["block"]
            self.assertIn("unbalanced quote", b, p)
            self.assertNotIn("EOF", b, p)
            self.assertNotIn("/bin/sh", b, p)
        # a *balanced* quoted command still runs normally
        r = self.proc('> echo "hi there"')["block"]
        self.assertIn("hi there", r)
        self.assertIn("exit 0", r)


class TestBugBash2(Base):
    """Fixes from the 2026-07-06 review."""

    def _cli(self, *args):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                _engine.main(list(args))
            except SystemExit:
                pass
        return buf.getvalue()

    def test_allow_rejects_a_chain(self):
        # H-1: --allow won't store a chain; and a chain never matches the allowlist.
        out = self._cli("--allow", "ls; touch /tmp/SETHU_CHAIN_TEST")
        self.assertIn("won't allowlist a chain", out)
        self.assertEqual(_engine.load_config()["allow"], [])          # not stored
        self.assertFalse(_engine._matches("ls; rm", ["ls; rm"]))      # never matches
        self.assertFalse(_engine._matches("ls | sh", ["ls | sh"]))

    def test_allow_plain_tool_still_works(self):
        self.write(allow=[])
        self._cli("--allow", "git")
        self.assertIn("git", _engine.load_config()["allow"])

    def test_rc_does_not_drop_co_flags(self):
        # M-3: `--rc on --mode shell --allow git` must apply ALL of them.
        self.write(mode="cwd", rc=False, allow=[])
        self._cli("--rc", "on", "--mode", "shell", "--allow", "git")
        c = _engine.load_config()
        self.assertTrue(c["rc"])
        self.assertEqual(c["mode"], "shell")
        self.assertIn("git", c["allow"])

    def test_ag_not_gated(self):
        # M-4: ag dropped from GATED (--pager exec vector unverifiable).
        self.assertNotIn("ag", _engine.GATED)

    def test_cli_output_has_no_embedded_lead(self):
        # M-1: help/menu must NOT embed the icon or `sethu:` — the hook's `_lead`
        # supplies it (colored, or `sethu:` in plain), so the menu icon gets colored.
        self.assertNotIn(_engine.ICON, _engine.HELP)
        self.assertNotIn(_engine.ICON, _engine.help_text())
        self.assertFalse(_engine.help_text().startswith("sethu:"))

    def test_style_cli_plain_swaps_glyphs(self):
        # M-1: plain mode swaps CLI glyphs for words.
        out = _engine._style_cli("✔ added\n  ⚠ careful\n  • item", on=False, plain=True)
        self.assertNotIn("✔", out)
        self.assertNotIn("⚠", out)
        self.assertNotIn("•", out)
        self.assertIn("done:", out)
        self.assertIn("warning:", out)

    def test_style_cli_colors_markers(self):
        # M-1: in color mode the ✔/⚠ markers get ANSI (so CLI feedback isn't monochrome).
        out = _engine._style_cli("✔ added", on=True, plain=False)
        self.assertIn("\033[", out)


class TestPlainMode(Base):
    """Plain/spoken mode: `sethu:` prefix + words, no |^=^| / glyph ornaments."""

    def _first(self, cmd, sid="p", **kw):
        self.write(color=False, plain=True, **kw)
        return self.proc("> " + cmd, sid=sid)["block"].split("\n")[0]

    def test_run_ok_header(self):
        self.assertEqual(self._first("true", allow=["true"]),
                         "sethu: [cwd], exit 0, $ true")

    def test_run_fail_header(self):
        self.assertEqual(self._first("false", allow=["false"]),
                         "sethu: [cwd], exit 1 (failed), $ false")

    def test_trust_tag_is_word(self):
        h = self._first("true", allow=["true"], trust=True)
        self.assertEqual(h, "sethu: [cwd], trust on, exit 0, $ true")
        self.assertNotIn("⚠", h)

    def test_no_glyphs_anywhere(self):
        self.write(color=False, plain=True)
        b = self.proc("> git branch", sid="p")["block"]
        self.assertTrue(b.startswith("sethu: [cwd], $ git branch\n"))
        self.assertIn("  - Allow this tool:", b)          # plain bullet
        for g in ("|^=^|", "·", "✓", "✗", "⚠", "•", "→"):
            self.assertNotIn(g, b, g)

    def test_cd_echo_is_words(self):
        self.write(color=False, plain=True, mode="cwd")
        b = self.proc("> cd /", sid="p")["block"]
        self.assertIn("now in /", b)
        self.assertNotIn("→", b)

    def test_pipe_note_leads_with_sethu(self):
        self.write(color=False, plain=True, allow=["echo"])
        r = self.proc(">> echo hi", sid="p")
        self.assertTrue(r["note"].startswith("sethu: [cwd], exit 0, $ echo hi"))
        self.assertNotIn("|^=^|", r["note"])

    def test_env_var_enables_plain(self):
        self.write(color=False, allow=["true"])   # plain OFF in config
        os.environ["SETHU_PLAIN"] = "1"
        try:
            self.assertTrue(self.proc("> true", sid="p")["block"].startswith("sethu:"))
        finally:
            os.environ.pop("SETHU_PLAIN", None)

    def test_cli_toggle_persists(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                _engine.main(["--plain", "on"])
            except SystemExit:
                pass
        self.assertTrue(_engine.load_config()["plain"])
        self.assertIn("plain: on", buf.getvalue())


class TestTrust(Base):
    def test_trust_bypasses_allowlist(self):
        self.write(trust=True)  # nothing allowlisted
        r = self.proc("> echo trusted")
        self.assertNotIn("gated", r["block"])
        self.assertIn("trusted", r["block"])

    def test_trust_marker_in_header(self):
        self.write(trust=True)
        self.assertIn("trust", self.proc("> echo x")["block"])

    def test_trust_still_refuses_interactive(self):
        self.write(trust=True)
        self.assertIn("interactive", self.proc("> vim x")["block"])

    def test_trust_roundtrips(self):
        # One knob: --trust on/off is the whole safety axis (gated = trust off).
        self.write()
        _engine.main(["--trust", "on"])
        self.assertTrue(_engine.load_config()["trust"])
        _engine.main(["--trust", "off"])
        self.assertFalse(_engine.load_config()["trust"])

    def test_trust_on_runs_non_gated(self):
        # With trust on, a non-gated tool runs (no refusal) — the gate is off.
        self.write(trust=True, allow=[])
        r = self.proc("> mkdir /tmp/sethu-trust-test")["block"]
        self.assertNotIn("gated", r)


class TestRunner(Base):
    def test_batch_python_runs_when_allowed(self):
        # End-to-end: allowlisted `python <script>` runs captured (not refused as
        # interactive) — the refinement that lets scripts run in the runner.
        self.write(allow=["python3"])
        script = os.path.join(self.tmp, "s.py")
        with open(script, "w") as f:
            f.write("print('hi from script')")
        r = self.proc("> python3 " + script)["block"]
        self.assertNotIn("gated", r)
        self.assertNotIn("interactive", r)
        self.assertIn("hi from script", r)

    def test_bare_python_still_refused_as_interactive(self):
        self.write(allow=["python3"])
        self.assertIn("interactive", self.proc("> python3")["block"])

    def test_explicit_allow_runs(self):
        self.write(allow=["echo"])
        r = self.proc("> echo hello")
        self.assertNotIn("gated", r["block"])
        self.assertIn("hello", r["block"])

    def test_gated_allows_inspection(self):
        self.write()
        r = self.proc("> ls")
        self.assertNotIn("gated", r["block"])

    def test_completion_header(self):
        self.write()
        r = self.proc("> ls")
        self.assertIn("[cwd]", r["block"])
        self.assertIn("exit 0", r["block"])

    def test_pipe_returns_context(self):
        self.write(allow=["echo"])
        r = self.proc(">> echo to-claude")
        self.assertIn("context", r)
        self.assertIn("to-claude", r["context"])

    def test_pipe_gives_local_confirmation(self):
        # UX2: `>>` costs tokens, so it must show a local confirmation (the unified
        # header + what was shared + the cost), not just silently send to Claude.
        self.write(allow=["echo"], color=False)
        r = self.proc(">> echo hi")
        self.assertIn("note", r)
        self.assertIn("$ echo hi", r["note"])         # unified header, echoes cmd
        self.assertIn("shared 1 line with Claude", r["note"])
        self.assertIn("used tokens", r["note"])

    def test_passthrough(self):
        self.assertEqual(self.proc("just a normal prompt"), {"passthrough": True})

    def test_pipe_output_is_fenced_as_untrusted(self):
        # `>>` output is labeled untrusted data (prompt-injection defense).
        self.write(allow=["echo"], color=False)
        ctx = self.proc(">> echo hi")["context"]
        self.assertIn("untrusted", ctx.lower())
        self.assertIn("BEGIN COMMAND OUTPUT", ctx)
        self.assertIn("hi", ctx)

    def test_launch_listed_command_opens_terminal(self):
        # A `>` command on the launch list is opened in a terminal, not captured.
        self.write(launch=["vim"], color=False)
        orig = _engine.launch_in_terminal
        _engine.launch_in_terminal = lambda c: "↗ opened"
        try:
            r = self.proc("> vim notes.md")["block"]
        finally:
            _engine.launch_in_terminal = orig
        self.assertIn("opened", r)

    def test_cd_to_bad_dir_message(self):
        self.write(color=False)
        self.assertIn("not a directory",
                      self.proc("> cd /no_such_dir_xyz123")["block"])


class TestIcon(Base):
    def test_icon_on_header_not_in_pipe(self):
        self.write(allow=["echo"], color=False)
        self.assertIn(_engine.ICON, self.proc("> echo hi")["block"])
        # The pipe-to-Claude context stays clean (icon is for your eyes only).
        self.assertNotIn(_engine.ICON, self.proc(">> echo hi")["context"])

    def test_separator_between_icon_and_tag(self):
        # A dim `·` splits the icon from the [mode] tag so they don't blend (UX7).
        self.write(color=False)
        self.assertIn(_engine.ICON + " · [cwd]", self.proc("> ls")["block"])


class TestColor(Base):
    def test_header_colored_by_default(self):
        os.environ.pop("NO_COLOR", None)
        self.write()
        self.assertIn("\033[", self.proc("> ls")["block"])  # ANSI present

    def test_color_off_strips_ansi(self):
        self.write(color=False)
        self.assertNotIn("\033[", self.proc("> ls")["block"])

    def test_failure_is_red(self):
        os.environ.pop("NO_COLOR", None)
        self.write(allow=["false"])
        r = self.proc("> false")           # exits nonzero
        self.assertIn("exit 1", r["block"])
        self.assertIn("38;5;203", r["block"])  # the red used for failures

    def test_success_is_not_red(self):
        os.environ.pop("NO_COLOR", None)
        self.write(allow=["true"])
        self.assertNotIn("38;5;203", self.proc("> true")["block"])

    def test_no_color_env_disables(self):
        self.write()
        os.environ["NO_COLOR"] = "1"
        try:
            self.assertNotIn("\033[", self.proc("> ls")["block"])
        finally:
            os.environ.pop("NO_COLOR", None)

    def test_piped_context_has_no_ansi(self):
        # Output sent to Claude must stay plain (color is for your eyes only).
        os.environ.pop("NO_COLOR", None)
        self.write(allow=["echo"])
        self.assertNotIn("\033[", self.proc(">> echo hi")["context"])


class TestTruncate(Base):
    def test_long_output_truncated_with_pointer(self):
        self.write(allow=["seq"], maxLines=10, color=False)
        r = self.proc("> seq 100", sid="trunc1")["block"]
        self.assertIn("more line", r)          # truncation note present
        self.assertIn("full output", r)         # points at the file
        self.assertNotIn("\n100", r)            # line 100 not shown inline
        # …and the file has the whole thing.
        path = _engine._output_path("trunc1")
        with open(path) as f:
            self.assertIn("100", f.read())

    def test_short_output_not_truncated(self):
        self.write(allow=["seq"], maxLines=40, color=False)
        r = self.proc("> seq 5", sid="trunc2")["block"]
        self.assertNotIn("more line", r)
        self.assertIn("5", r)

    def test_zero_disables_truncation(self):
        self.write(allow=["seq"], maxLines=0, color=False)
        r = self.proc("> seq 200", sid="trunc3")["block"]
        self.assertNotIn("more line", r)
        self.assertIn("200", r)

    def test_pipe_truncates_and_flags_file(self):
        self.write(allow=["seq"], maxLines=10)
        r = self.proc(">> seq 100", sid="trunc4")
        self.assertIn("context", r)
        self.assertIn("truncated", r["context"])
        self.assertNotIn("\n100", r["context"])


class TestSweep(unittest.TestCase):
    def setUp(self):
        # Isolate the sweep to a private dir so it never touches the real /tmp
        # (the tests are age-gated, but keep the discipline the other classes have).
        self._orig_tempdir = tempfile.tempdir
        tempfile.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        tempfile.tempdir = self._orig_tempdir

    def test_old_files_removed_fresh_kept(self):
        import tempfile as _tf
        tmp = _tf.gettempdir()
        old = os.path.join(tmp, "sethu-out-deadbeef0001.log")
        cmd = os.path.join(tmp, "sethu-launch-deadbeef0002.command")
        sock = os.path.join(tmp, "sethu-deadbeef0004-p0.sock")   # orphaned socket
        cwd = os.path.join(tmp, "sethu-cwd-deadbeef0005")        # dead-session cwd
        fresh = os.path.join(tmp, "sethu-out-deadbeef0003.log")
        for p in (old, cmd, sock, cwd, fresh):
            open(p, "w").close()
        self.addCleanup(lambda: [os.path.exists(p) and os.unlink(p)
                                 for p in (old, cmd, sock, cwd, fresh)])
        now = os.path.getmtime(fresh) + 100
        # Backdate the stale files well past the max age.
        stale = now - _engine._TEMP_MAX_AGE - 1000
        for p in (old, cmd, sock, cwd):
            os.utime(p, (stale, stale))
        _engine._sweep_temp(now, force=True)   # bypass the once-an-hour throttle
        self.assertFalse(os.path.exists(old), "stale .log should be swept")
        self.assertFalse(os.path.exists(cmd), "stale .command should be swept")
        self.assertFalse(os.path.exists(sock), "stale orphaned .sock should be swept")
        self.assertFalse(os.path.exists(cwd), "stale cwd file should be swept")
        self.assertTrue(os.path.exists(fresh), "fresh file must be kept")

    def test_sweep_throttled(self):
        # A recent sentinel means the scan is skipped (no deletions) until it ages.
        import tempfile as _tf
        tmp = _tf.gettempdir()
        sentinel = os.path.join(tmp, "sethu-swept")
        old = os.path.join(tmp, "sethu-out-throttle01.log")
        open(old, "w").close()
        self.addCleanup(lambda: [os.path.exists(p) and os.unlink(p)
                                 for p in (old, sentinel)])
        now = os.path.getmtime(old) + 100
        os.utime(old, (now - _engine._TEMP_MAX_AGE - 1000,) * 2)  # very stale
        open(sentinel, "w").close()                               # sweep sentinel…
        os.utime(sentinel, (now - 10, now - 10))                  # …swept 10s ago
        _engine._sweep_temp(now)                                  # throttled → skip
        self.assertTrue(os.path.exists(old), "recent sweep must skip the scan")
        _engine._sweep_temp(now, force=True)                      # forced → runs
        self.assertFalse(os.path.exists(old))


class TestLeadingWhitespace(Base):
    def test_space_before_prefix_still_intercepts(self):
        self.write()
        r = self.proc("   > pwd")            # stray leading spaces
        self.assertNotIn("passthrough", r)   # handled, not leaked to the model
        self.assertIn("pwd", r["block"])

    def test_plain_prompt_still_passes_through(self):
        self.assertEqual(self.proc("just talking to claude"), {"passthrough": True})

    def test_prefix_mid_prompt_does_not_trigger(self):
        # `>` only triggers at the START of a prompt — never mid-text, so prompts
        # that merely mention `>` are not intercepted.
        self.write()
        for p in ["compare a > b in the code", "if x > 0 then run it",
                  "note a>b matters", "use foo > bar as an example"]:
            self.assertEqual(self.proc(p), {"passthrough": True}, p)
            self.assertFalse(sethu_hook._maybe_sethu(p), p)


class TestCwdMode(Base):
    def test_cd_persists(self):
        self.write()
        self.proc("> cd /tmp")
        r = self.proc("> pwd")
        self.assertIn("tmp", r["block"])

    def test_stateless_cd_message(self):
        self.write(mode="stateless")
        self.assertIn("stateless", self.proc("> cd /tmp")["block"])


class TestModeSwitching(Base):
    def test_switch_cwd_to_stateless_changes_cd_behavior(self):
        sid = "ms-cwd"
        self.write(mode="cwd", color=False)
        self.proc("> cd /tmp", sid=sid)
        self.assertIn("tmp", self.proc("> pwd", sid=sid)["block"])   # cwd persists
        _engine.main(["--mode", "stateless"])                        # switch
        self.assertEqual(_engine.load_config()["mode"], "stateless")
        self.assertIn("stateless", self.proc("> cd /tmp", sid=sid)["block"])

    def test_leaving_shell_mode_reaps_the_daemon(self):
        sid = "ms-shell"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", allow=["export", "echo"], color=False)
        self.proc("> export X=1", sid=sid)                           # spawns daemon
        sock = _engine._sock_path(sid)
        self.assertTrue(os.path.exists(sock))
        _engine.main(["--mode", "cwd"])                              # switch away
        self.assertEqual(_engine.load_config()["mode"], "cwd")
        self.assertFalse(os.path.exists(sock))                       # daemon reaped

    def test_switch_into_shell_mode_persists_state(self):
        sid = "ms-into-shell"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="cwd", allow=["export", "echo"], color=False)
        _engine.main(["--mode", "shell"])
        self.assertEqual(_engine.load_config()["mode"], "shell")
        self.proc("> export FOO=switched", sid=sid)
        self.assertIn("switched", self.proc("> echo $FOO", sid=sid)["block"])


class TestShellMode(Base):
    def test_env_and_cd_persist(self):
        sid = "test-shell-1"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", allow=["export", "echo", "pwd"])
        self.proc("> export FOO=persisted", sid=sid)
        self.assertIn("persisted", self.proc("> echo $FOO", sid=sid)["block"])
        self.proc("> cd /tmp", sid=sid)
        self.assertIn("tmp", self.proc("> pwd", sid=sid)["block"])

    def test_restart_clears_state(self):
        sid = "test-shell-2"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", allow=["export", "echo"])
        self.proc("> export BAR=gone", sid=sid)
        self.assertIn("gone", self.proc("> echo $BAR", sid=sid)["block"])
        self._shutdown(sid)
        self.assertNotIn("gone", self.proc("> echo $BAR", sid=sid)["block"])

    def test_stale_socket_recovers(self):
        # Regression: a leftover socket file with no live daemon ("connection
        # refused") must be cleaned up and a fresh daemon spawned.
        sid = "test-shell-stale"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", allow=["echo"])
        sock = _engine._sock_path(sid)
        dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        dead.bind(sock)   # creates the socket file…
        dead.close()      # …but nothing is listening on it
        self.assertTrue(os.path.exists(sock))
        r = self.proc("> echo recovered", sid=sid)
        self.assertIn("recovered", r["block"])

    def test_chained_cd_does_not_execute_in_shell_mode(self):
        # H4 security regression: `cd` is allowlist-exempt, but in shell mode the raw
        # string runs in the daemon, so a chained `cd x; <cmd>` must be REFUSED, not
        # executed. (Pre-fix this created the sentinel.)
        import time
        sid = "test-shell-cdchain"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell")
        sentinel = os.path.join(self.tmp, "H4_PWNED")
        r = self.proc(f"> cd /tmp; touch {sentinel}", sid=sid)
        self.assertIn("block", r)                 # refused…
        self.assertIn("gated", r["block"])
        time.sleep(0.3)                           # give any (buggy) execution a chance
        self.assertFalse(os.path.exists(sentinel), "chained cd executed in shell mode!")

    def test_shell_disables_pager(self):
        # Regression: paged commands (git log/branch) must not hang under the PTY.
        sid = "test-shell-pager"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", allow=["echo"])
        r = self.proc("> echo PG=$GIT_PAGER", sid=sid)
        self.assertIn("PG=cat", r["block"])

    def test_timeout_recovers_from_sigint_surviving_job(self):
        # H3: a job that ignores Ctrl-C (`trap '' INT`) times out, but the shell
        # must NOT stay wedged — the very next command has to run normally (the
        # daemon escalates to SIGKILL / respawns).
        sid = "test-shell-h3-wedge"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", trust=True, timeout=2, color=False)
        self.proc("> trap '' INT; sleep 30", sid=sid)          # times out (~2s)
        r = self.proc("> echo RECOVERED_OK", sid=sid)["block"]  # must work
        self.assertIn("RECOVERED_OK", r)
        self.assertNotIn("timed out", r)

    def test_timeout_no_output_bleed_or_late_exec(self):
        # H3: a timed-out command's late output must not bleed into the next
        # command, and a fresh command must be clean.
        sid = "test-shell-h3-bleed"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", trust=True, timeout=2, color=False)
        self.proc("> trap '' INT; sleep 3; echo LEAKED_LATE", sid=sid)  # times out
        r = self.proc("> echo FRESH_QQQ", sid=sid)["block"]
        self.assertIn("FRESH_QQQ", r)
        self.assertNotIn("LEAKED_LATE", r)

    def test_real_uuid_session_id(self):
        # Regression: a full-length UUID must not overflow the AF_UNIX path.
        sid = "a253f39f-aecf-416f-b1f0-2702df515154"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", allow=["echo"])
        r = self.proc("> echo runs_ok", sid=sid)
        self.assertIn("runs_ok", r["block"])
        self.assertNotIn("path too long", r["block"])

    def test_shell_mode_caps_runaway_output(self):
        # ST1/ST7: a runaway (`yes`) in shell mode is stopped at the byte cap and
        # the shell recovers (next command works), with the cap note surfaced.
        sid = "test-shell-cap"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", trust=True, maxLines=5, color=False)
        r = self.proc("> yes", sid=sid)["block"]
        self.assertIn("capped at", r)
        self.assertIn("RECOVER_OK", self.proc("> echo RECOVER_OK", sid=sid)["block"])


class TestOutputCap(Base):
    """ST1: captured output is byte-capped in RAM and on disk (maxLines only caps
    the DISPLAY). A runaway is killed at the cap, not buffered unbounded."""

    def test_run_capture_kills_runaway_at_cap(self):
        out, code = _engine.run_capture("yes")   # infinite output
        self.assertLessEqual(len(out.encode("utf-8", "replace")),
                             _engine.MAX_CAPTURE_BYTES + 4096)
        self.assertIn("capped at", out)
        self.assertIsNone(code)                  # killed, no clean exit

    def test_run_capture_normal_command_unaffected(self):
        out, code = _engine.run_capture("printf 'a\\nb\\nc\\n'")
        self.assertEqual(code, 0)
        self.assertNotIn("capped", out)
        self.assertEqual(out.strip(), "a\nb\nc")

    def test_run_capture_stderr_captured(self):
        out, _ = _engine.run_capture("ls /nonexistent-sethu-xyz")
        self.assertIn("nonexistent-sethu-xyz", out)   # stderr merged into output

    def test_exact_cap_boundary_is_clean_finish(self):
        # LOW-1: a command emitting EXACTLY the cap then EOF is not a runaway —
        # it must keep its exit code and NOT be flagged truncated.
        n = _engine.MAX_CAPTURE_BYTES
        out, code = _engine.run_capture(f"head -c {n} /dev/zero")
        self.assertEqual(code, 0)
        self.assertNotIn("capped", out)

    def test_cap_note_survives_display_truncation(self):
        # The note leads the output, so maxLines truncation can't bury it (cwd mode).
        self.write(trust=True, maxLines=3, color=False)
        self.assertIn("capped at", self.proc("> yes")["block"])


class TestStateBuiltinHint(Base):
    def test_safe_state_builtin_in_nonshell_hints_shell_mode(self):
        # UX1/UX4: export/alias/unset auto-run without --allow, but only persist in
        # shell mode; cwd/stateless say so (a no-op note) instead of running nothing.
        for m in ("cwd", "stateless"):
            self.write(mode=m, color=False)
            for c in ["export FOO=1", "alias g=git", "unalias g", "unset PATHX"]:
                b = self.proc("> " + c)["block"]
                self.assertIn("shell mode", b, f"{m}: {c}")
                self.assertIn("--mode shell", b, f"{m}: {c}")

    def test_safe_state_builtin_autoruns_in_shell_mode_without_allow(self):
        # UX1: in shell mode they auto-run WITHOUT --allow and persist.
        sid = "test-ux1-persist"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", allow=[], color=False)  # no --allow
        self.proc("> export FOO=ux1", sid=sid)
        self.assertIn("ux1", self.proc("> echo $FOO", sid=sid)["block"])

    def test_source_needs_allow_not_shell_hint(self):
        # UX1: source/. execute a file's contents (arbitrary code), so they are NOT
        # auto-permitted — they need --allow, with a message that says why (in every
        # mode, since the risk isn't mode-dependent).
        for m in ("cwd", "shell"):
            self.write(mode=m, color=False)
            for c in ["source venv/bin/activate", ". env/bin/activate"]:
                b = self.proc("> " + c)["block"]
                self.assertIn("--allow", b, f"{m}: {c}")
                self.assertIn("contents of a file", b, f"{m}: {c}")

    def test_state_builtin_autopermit_is_chain_guarded(self):
        # UX1 security: the auto-permit only applies to a simple builtin — a chained
        # or substituted one is NOT auto-run.
        self.write(mode="shell", color=False)
        for c in ["export A=1; rm -rf x", "export A=$(rm x)", "unset X && rm y"]:
            self.assertIn("gated", self.proc("> " + c)["block"], c)


class TestRcAliases(Base):
    def test_alias_and_env_from_rc_work_in_shell_mode(self):
        # With --rc on, an alias AND an exported var from the shell rc are usable
        # via `>` in shell mode (the daemon runs $SHELL and sources its rc).
        home = tempfile.mkdtemp()
        with open(os.path.join(home, ".bashrc"), "w") as f:
            f.write("alias greet='echo ALIAS_OK'\nexport RCVAR=rc_env_ok\n")
        sid = "test-rc-alias"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", rc=True, allow=["greet", "echo"], color=False)
        saved = {k: os.environ.get(k) for k in ("HOME", "SHELL")}
        os.environ["HOME"] = home
        os.environ["SHELL"] = "/bin/bash"
        try:
            alias_out = self.proc("> greet", sid=sid)["block"]
            env_out = self.proc("> echo $RCVAR", sid=sid)["block"]
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertIn("ALIAS_OK", alias_out)    # alias from rc ran
        self.assertIn("rc_env_ok", env_out)     # exported var from rc is set


class TestTimeout(Base):
    def setUp(self):
        super().setUp()
        os.environ["SETHU_CMD_TIMEOUT"] = "2"   # keep the test quick

    def tearDown(self):
        os.environ.pop("SETHU_CMD_TIMEOUT", None)
        super().tearDown()

    def test_cwd_timeout_points_to_launch(self):
        self.write(allow=["sleep"], color=False)
        r = self.proc("> sleep 5")["block"]
        self.assertIn("timed out after 2s", r)
        self.assertIn("--launch", r)

    def test_config_timeout_used(self):
        # With the env override cleared, the config `timeout` drives it.
        os.environ.pop("SETHU_CMD_TIMEOUT", None)
        self.write(allow=["sleep"], timeout=1, color=False)
        cfg = _engine.load_config()
        self.assertEqual(_engine.cmd_timeout(cfg), 1)
        r = self.proc("> sleep 5")["block"]
        self.assertIn("timed out after 1s", r)

    def test_env_overrides_config_timeout(self):
        self.write(timeout=99)
        os.environ["SETHU_CMD_TIMEOUT"] = "3"
        self.assertEqual(_engine.cmd_timeout(_engine.load_config()), 3)

    def test_timeout_roundtrips_and_floors_at_1(self):
        _engine.main(["--timeout", "45"])
        self.assertEqual(_engine.load_config()["timeout"], 45)
        _engine.main(["--timeout", "0"])
        self.assertEqual(_engine.load_config()["timeout"], 1)  # floored

    def test_shell_timeout_reports_and_recovers(self):
        sid = "test-timeout-shell"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", allow=["sleep", "echo"], color=False)
        r = self.proc("> sleep 5", sid=sid)["block"]
        self.assertIn("timed out after 2s", r)
        # The shell must recover — the stuck command was interrupted, so the next
        # command runs normally instead of hanging behind it.
        r2 = self.proc("> echo alive", sid=sid)["block"]
        self.assertIn("alive", r2)


class TestSocketPerms(unittest.TestCase):
    def test_owner_only_is_ok(self):
        # 0600 socket (the umask result) is accepted.
        self.assertTrue(_shelld._perms_ok(0o140600))

    def test_group_or_world_access_refused(self):
        # Any group/world bit means the daemon must fail closed.
        for m in [0o140660, 0o140666, 0o140640, 0o140604, 0o140700 | 0o010]:
            self.assertFalse(_shelld._perms_ok(m), oct(m))


class TestSocketPath(unittest.TestCase):
    def test_under_limit_for_uuid(self):
        sid = "a253f39f-aecf-416f-b1f0-2702df515154"
        self.assertLess(len(_engine._sock_path(sid)), 104)


class TestNormalizeArgv(unittest.TestCase):
    def test_subcommand_to_flag(self):
        n = _engine.normalize_argv
        self.assertEqual(n(["mode", "shell"]), ["--mode", "shell"])
        self.assertEqual(n(["trust", "on"]), ["--trust", "on"])
        self.assertEqual(n(["restart"]), ["--restart"])
        self.assertEqual(n(["runner"]), ["--runner"])
        self.assertEqual(n(["allow", "git", "status"]), ["--allow", "git status"])
        self.assertEqual(n(["help"]), [])

    def test_passthrough(self):
        n = _engine.normalize_argv
        self.assertEqual(n(["--mode", "shell"]), ["--mode", "shell"])  # already flags
        self.assertEqual(n(["git", "log"]), ["git", "log"])            # not a subcommand
        self.assertEqual(n([]), [])


class TestLaunch(Base):
    def test_osa_escaping(self):
        # Quotes and backslashes must be escaped so the AppleScript literal is
        # well-formed and can't break out of the string.
        self.assertEqual(_engine._osa_str('say "hi"'), 'say \\"hi\\"')
        self.assertEqual(_engine._osa_str('a\\b'), 'a\\\\b')

    def test_launch_command_script_self_deletes(self):
        # ST3: the last-resort .command file holds the raw command (may carry
        # secrets), so it removes itself the moment Terminal runs it — before the
        # command executes — rather than lingering until the 7-day sweep.
        s = _engine._launch_command_script("aws login --token SECRET", "/bin/zsh")
        self.assertIn('rm -f "$0"', s)
        self.assertIn("aws login --token SECRET", s)
        self.assertLess(s.index('rm -f "$0"'), s.index("aws login"))  # delete first

    def test_launch_registers_and_opens_now(self):
        # `sethu --launch vi` must both add vi to the launch list AND try to open
        # it immediately (the verb is an action, not just registration).
        opened = []
        orig = _engine.launch_in_terminal
        _engine.launch_in_terminal = lambda c: opened.append(c) or "↗ opened"
        try:
            _engine.main(["--launch", "vi"])
        finally:
            _engine.launch_in_terminal = orig
        self.assertEqual(opened, ["vi"])               # opened now
        self.assertIn("vi", _engine.load_config()["launch"])  # and registered

    def test_launch_message_states_both_effects(self):
        # UX5: --launch has a surprising DOUBLE effect (opens now AND permanently
        # registers). The message must make both, and the persistence, explicit.
        import io, contextlib
        orig = _engine.launch_in_terminal
        _engine.launch_in_terminal = lambda c: "↗ opened in a new tmux pane"
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                _engine.main(["--launch", "vi"])
        finally:
            _engine.launch_in_terminal = orig
        out = buf.getvalue()
        self.assertIn("launch list", out)      # registered
        self.assertIn("persistent", out)       # …and it's persistent
        self.assertIn("opened", out.lower())   # …and opened now
        self.assertIn("--unlaunch", out)       # how to undo


class TestFirstRunHint(Base):
    def test_fires_once_then_silent(self):
        first = _engine.first_run_hint()
        self.assertIsNotNone(first)
        self.assertIn("systemMessage", first)
        self.assertIn("sethu", first["systemMessage"])
        # Marker now exists → never nudges again.
        self.assertTrue(os.path.exists(_engine._welcome_marker()))
        self.assertIsNone(_engine.first_run_hint())

    def test_marker_is_beside_config(self):
        self.assertEqual(os.path.dirname(_engine._welcome_marker()),
                         os.path.dirname(_engine.config_path()))

    def test_lost_race_stays_quiet(self):
        # If a concurrent session already claimed the marker (O_EXCL), stay quiet
        # even though this call passed the exists() check before it was created.
        m = _engine._welcome_marker()
        os.makedirs(os.path.dirname(m), exist_ok=True)
        os.close(os.open(m, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        self.assertIsNone(_engine.first_run_hint())

    def test_skips_hint_when_marker_unwritable(self):
        # If the marker can't be persisted, don't nudge (else it repeats every
        # session on a read-only config dir).
        f = tempfile.NamedTemporaryFile(delete=False)
        f.close()
        os.environ["SETHU_CONFIG"] = os.path.join(f.name, "sub", "sethu.json")
        try:
            self.assertIsNone(_engine.first_run_hint())
            self.assertIsNone(_engine.first_run_hint())   # still silent, not spam
        finally:
            os.environ["SETHU_CONFIG"] = self.cfg
            os.unlink(f.name)


class TestSpawnLock(Base):
    """L7: only one client spawns a daemon per session; the rest wait (fcntl.flock)."""

    def _sock(self, name):
        p = os.path.join(tempfile.gettempdir(), name)
        # flock never unlinks its lock file (by design), so clean it up after the test.
        self.addCleanup(lambda: os.path.exists(p + ".lock") and os.unlink(p + ".lock"))
        return p

    def test_lock_is_exclusive(self):
        sock = self._sock("sethu-testlock-p9.sock")
        fd = _engine._acquire_spawn_lock(sock)
        self.assertIsNotNone(fd)                                   # winner spawns
        try:
            self.assertIsNone(_engine._acquire_spawn_lock(sock))  # loser blocked
        finally:
            _engine._release_spawn_lock(fd)
        fd2 = _engine._acquire_spawn_lock(sock)                    # released → reacquire
        self.assertIsNotNone(fd2)
        _engine._release_spawn_lock(fd2)

    def test_leftover_lock_file_does_not_block(self):
        # flock guards the holder, not the file — a dead session's leftover lock file
        # (nobody flocked) must be immediately acquirable, not stuck until a timeout.
        sock = self._sock("sethu-testleftover-p9.sock")
        open(sock + ".lock", "w").close()          # stale file, no live holder
        fd = _engine._acquire_spawn_lock(sock)
        self.assertIsNotNone(fd)
        _engine._release_spawn_lock(fd)


class TestConfigDurability(Base):
    """Config/cwd durability: atomic write (A1 torn read / A2 crash-wipe / B cwd file)
    + flock on the CLI read-modify-write (A3 lost update)."""

    def _read(self, p):
        with open(p) as f:
            return f.read()

    def _no_temp(self, d):
        self.assertEqual([n for n in os.listdir(d) if n.startswith(".sethu-tmp-")], [])

    def test_atomic_write_roundtrip_no_temp_left(self):
        p = os.path.join(self.tmp, "f.txt")
        _engine._atomic_write(p, "hello\n")
        self.assertEqual(self._read(p), "hello\n")
        self._no_temp(self.tmp)

    def test_atomic_write_failure_keeps_original(self):
        from unittest import mock
        p = os.path.join(self.tmp, "f.txt")
        _engine._atomic_write(p, "original")
        with mock.patch("os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                _engine._atomic_write(p, "SHOULD-NOT-LAND")
        self.assertEqual(self._read(p), "original")      # never torn/replaced
        self._no_temp(self.tmp)                          # temp cleaned up

    def test_save_config_is_atomic_and_valid(self):
        self.write(allow=["ls"])
        _engine.save_config(_engine.load_config())
        with open(self.cfg) as f:
            json.load(f)                                 # complete valid JSON
        self._no_temp(os.path.dirname(self.cfg))

    def test_config_lock_releases(self):
        # Two sequential locks must not deadlock (proves release, and no fcntl crash).
        with _engine._config_lock():
            pass
        with _engine._config_lock():
            pass

    def test_concurrent_writers_lose_no_update(self):
        # A3: N racing `sethu --allow tool{i}` — flock serializes the RMW so every
        # entry survives (last-writer-wins would drop some).
        import subprocess as sp
        self.write(allow=[])
        env = dict(os.environ, SETHU_CONFIG=self.cfg)
        procs = [sp.Popen([sys.executable, _engine.__file__, "--allow", f"tool{i}"],
                          env=env, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
                 for i in range(12)]
        for pr in procs:
            pr.wait()
        allow = _engine.load_config()["allow"]
        for i in range(12):
            self.assertIn(f"tool{i}", allow)


class TestConfig(Base):
    def test_defaults_when_missing(self):
        os.unlink(self.cfg)
        cfg = _engine.load_config()
        self.assertEqual(cfg["mode"], "cwd")
        self.assertEqual(cfg["allow"], [])
        self.assertFalse(cfg["trust"])     # gated by default (trust off)
        self.assertNotIn("readonly", cfg)  # the old key is gone
        self.assertFalse(cfg["rc"])
        self.assertTrue(cfg["color"])

    def test_gated_default_allows_inspection_refuses_rest(self):
        # With no config at all, gated tools run and everything else is refused.
        os.unlink(self.cfg)
        self.assertNotIn("gated", self.proc("> ls")["block"])       # runs
        self.assertIn("gated", self.proc("> rm -rf /tmp/x")["block"])  # refused
        self.assertIn("gated", self.proc("> git log")["block"])     # git not gated

    def test_rc_roundtrips(self):
        _engine.main(["--rc", "on"])
        self.assertTrue(_engine.load_config()["rc"])
        _engine.main(["--rc", "off"])
        self.assertFalse(_engine.load_config()["rc"])

    def test_roundtrip(self):
        c = _engine.load_config()
        c["allow"].append("git status")
        c["mode"] = "shell"
        _engine.save_config(c)
        self.assertEqual(_engine.load_config()["allow"], ["git status"])
        self.assertEqual(_engine.load_config()["mode"], "shell")

    def test_max_lines_coerces_malformed(self):
        # A malformed maxLines must not crash the hook — fall back to the default.
        self.assertEqual(_engine.max_lines({"maxLines": "oops"}), 40)
        self.assertEqual(_engine.max_lines({}), 40)
        self.assertEqual(_engine.max_lines({"maxLines": 0}), 0)      # unlimited
        self.assertEqual(_engine.max_lines({"maxLines": 100}), 100)
        self.assertEqual(_engine.max_lines({"maxLines": -5}), 0)     # negative → clamped

    def test_malformed_config_types_fall_back(self):
        # A hand-edited config with wrongly-typed values falls back per key
        # instead of crashing callers that index/append.
        with open(self.cfg, "w") as f:
            json.dump({"allow": "ls", "launch": 5, "trust": "on",
                       "prefix": 9, "mode": ["x"]}, f)
        c = _engine.load_config()
        self.assertEqual(c["allow"], [])       # non-list -> default []
        self.assertEqual(c["launch"], [])
        self.assertIs(c["trust"], False)       # "on" (str) isn't a bool -> default
        self.assertEqual(c["prefix"], ">")     # non-str -> default
        self.assertEqual(c["mode"], "cwd")     # non-str -> default

    def test_allow_survives_malformed_config(self):
        # The CLI mutation path must not crash when the on-disk list is malformed.
        import io
        import contextlib
        with open(self.cfg, "w") as f:
            json.dump({"allow": "ls"}, f)
        with contextlib.redirect_stdout(io.StringIO()):
            _engine.main(["--allow", "foo"])   # previously AttributeError
        self.assertIn("foo", _engine.load_config()["allow"])

    def test_malformed_config_values_normalized(self):
        # Beyond type: non-string list entries are coerced (else `_matches` does
        # str + int → TypeError), a bad mode falls back, and an empty prefix falls
        # back (an empty prefix would match every prompt).
        with open(self.cfg, "w") as f:
            json.dump({"allow": [1, 2], "mode": "banana", "prefix": ""}, f)
        c = _engine.load_config()
        self.assertEqual(c["allow"], ["1", "2"])
        self.assertEqual(c["mode"], "cwd")
        self.assertEqual(c["prefix"], ">")
        self.proc("> ls")   # non-string allowlist previously crashed process()

    def test_setter_flags_roundtrip(self):
        # The management CLI persists each config-setter flag.
        _engine.main(["--color", "off"])
        self.assertFalse(_engine.load_config()["color"])
        _engine.main(["--maxlines", "100"])
        self.assertEqual(_engine.load_config()["maxLines"], 100)
        _engine.main(["--prefix", "!!"])
        self.assertEqual(_engine.load_config()["prefix"], "!!")
        _engine.main(["--mode", "cwd"])
        self.assertEqual(_engine.load_config()["mode"], "cwd")

    def test_allow_unallow_and_unlaunch_roundtrip(self):
        _engine.main(["--allow", "git status"])
        self.assertIn("git status", _engine.load_config()["allow"])
        _engine.main(["--unallow", "git status"])
        self.assertNotIn("git status", _engine.load_config()["allow"])
        # unlaunch removes without opening a terminal
        c = _engine.load_config(); c["launch"] = ["vim"]; _engine.save_config(c)
        _engine.main(["--unlaunch", "vim"])
        self.assertNotIn("vim", _engine.load_config()["launch"])


class TestCustomPrefix(Base):
    def test_custom_prefix_intercepts_and_default_passes(self):
        self.write(prefix="!!", color=False)
        self.assertIn("[cwd]", self.proc("!! pwd")["block"])       # !! runs
        self.assertEqual(self.proc("> pwd"), {"passthrough": True})  # > no longer


class TestKillDaemons(Base):
    def test_kill_daemons_reaps_live_daemon(self):
        # Regression for the v0.8.0 glob fix: kill_daemons must actually find and
        # shut down a live shell daemon (the socket is named sethu-<hash>-p<n>).
        sid = "test-killdaemons"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", allow=["echo"])
        self.proc("> echo hi", sid=sid)              # spawns the daemon
        sock = _engine._sock_path(sid)
        self.assertTrue(os.path.exists(sock))
        self.assertGreaterEqual(_engine.kill_daemons(), 1)
        self.assertFalse(os.path.exists(sock))       # socket removed


class TestHookOutput(Base):
    """End-to-end: sethu_hook.py emits the right hook JSON — and crucially emits
    NOTHING on a normal prompt, so it coexists cleanly with a user's other
    UserPromptSubmit hooks (which run in parallel; Claude Code concatenates any
    additionalContext and lets any block win)."""
    HOOK = os.path.join(HOOKS, "sethu_hook.py")

    def _run(self, prompt):
        data = {"prompt": prompt, "session_id": "hookout", "cwd": self.tmp}
        env = dict(os.environ, SETHU_CONFIG=self.cfg, NO_COLOR="1")
        return subprocess.run([sys.executable, self.HOOK], input=json.dumps(data),
                              capture_output=True, text=True, env=env)

    def test_normal_prompt_emits_nothing(self):
        # The coexistence guarantee: a non-sethu prompt produces NO output.
        self.write()
        r = self._run("just a normal message to claude")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_unterminated_quote_is_refused(self):
        # `sethu allow "oops` (unbalanced quote) must refuse, not persist garbage.
        self.write()
        out = json.loads(self._run('sethu allow "oops').stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("quotes", out["reason"])
        self.assertIn(_engine.ICON, out["reason"])         # branded like other messages
        self.assertIn("error:", out["reason"])             # matches the CLI error format
        self.assertNotIn('"oops', _engine.load_config()["allow"])

    def test_run_command_emits_block(self):
        self.write()
        out = json.loads(self._run("> ls").stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("ls", out["reason"])

    def test_pipe_emits_additional_context(self):
        self.write(allow=["echo"])
        out = json.loads(self._run(">> echo hi").stdout)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "UserPromptSubmit")
        self.assertIn("hi", hso["additionalContext"])
        self.assertNotIn("decision", out)   # >> does NOT block
        # UX2: and a local systemMessage surfaces the token cost to the user.
        self.assertIn("used tokens", out["systemMessage"])
        self.assertIn("shared 1 line with Claude", out["systemMessage"])

    def test_sethu_management_emits_block(self):
        self.write()
        out = json.loads(self._run("sethu --runner").stdout)
        self.assertEqual(out["decision"], "block")

    def test_management_response_carries_icon(self):
        # Every sethu response opens with the |^=^| icon so it's instantly
        # recognizable as sethu — including management output (the config dump and
        # ✔ successes), not just bridged commands.
        self.write(allow=[])
        for cmd in ("sethu --runner", "sethu --allow ls"):
            out = json.loads(self._run(cmd).stdout)
            self.assertIn(_engine.ICON, out["reason"], cmd)
        # …but it's not doubled up when the output already leads with the icon.
        help_out = json.loads(self._run("sethu").stdout)["reason"]
        self.assertEqual(help_out.count(_engine.ICON), 1, "icon doubled on help")


class TestEveryResponseLeadsWithIcon(Base):
    """Invariant: EVERY sethu response the user sees opens with `|^=^| · ` so it's
    instantly recognizable as sethu (vs. their own shell or Claude). The hook routes
    all user-facing output through `_lead`, which guarantees it; this test drives one
    of each response type end-to-end so a new/changed path that drops the icon fails
    CI. A new response kind → add a case here."""
    HOOK = os.path.join(HOOKS, "sethu_hook.py")

    def _user_text(self, prompt, **cfg):
        self.write(**cfg)
        data = {"prompt": prompt, "session_id": "iconinv", "cwd": self.tmp}
        env = dict(os.environ, SETHU_CONFIG=self.cfg, NO_COLOR="1")
        r = subprocess.run([sys.executable, self.HOOK], input=json.dumps(data),
                           capture_output=True, text=True, env=env)
        out = json.loads(r.stdout) if r.stdout.strip() else {}
        return out.get("reason") or out.get("systemMessage") or ""

    def test_all_response_types_open_with_icon_and_separator(self):
        self.addCleanup(self._shutdown, "iconinv")
        lead = _engine.ICON + " · "
        cases = [
            ("> ls", {}),                             # a run (result header)
            ("> rm -rf x", {}),                       # a refusal
            ("> cd /tmp", {"mode": "cwd"}),           # cd
            ("> vim", {"allow": ["vim"]}),            # interactive refusal
            (">> echo hi", {"allow": ["echo"]}),      # >> local note (systemMessage)
            ("sethu --runner", {}),                   # management: config dump
            ("sethu --allow ls", {}),                 # management: success line
            ("sethu --definitelynotaflag", {}),       # argparse error
            ("sethu", {}),                            # help menu
            ('sethu allow "oops', {}),                # mismatched quotes
            ('sethu --prefix "|^=^|"', {}),           # F1: a value CONTAINING the icon
        ]                                             #     must still get a leading icon
        for prompt, cfg in cases:
            txt = self._user_text(prompt, **cfg)
            self.assertTrue(txt.startswith(lead),
                            f"{prompt!r} response didn't open with the icon+separator: {txt[:50]!r}")


class TestPython3Shim(unittest.TestCase):
    """hooks/run.sh — the sh launcher that gives a clear message (instead of a
    cryptic hook error) when python3 isn't installed."""
    SHIM = os.path.join(HOOKS, "run.sh")

    def _run(self, role, script, env, stdin="{}"):
        return subprocess.run(
            ["/bin/sh", self.SHIM, role, os.path.join(HOOKS, script)],
            input=stdin, capture_output=True, text=True, env=env)

    def test_missing_python3_session_warns(self):
        # No python3 on PATH → session start shows one clear message.
        r = self._run("session", "session_start.py", {"PATH": "/nonexistent"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("systemMessage", r.stdout)
        self.assertIn("python3", r.stdout)
        json.loads(r.stdout)  # must be valid JSON

    def test_missing_python3_prompt_is_silent(self):
        # No python3 → a NORMAL prompt passes through silently (typing still works).
        r = self._run("prompt", "sethu_hook.py", {"PATH": "/nonexistent"},
                      stdin='{"prompt":"hello"}')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_missing_python3_sethu_prompt_warns(self):
        # No python3 → a SETHU-looking prompt (> … / sethu …) is blocked with the
        # install guidance, so it doesn't silently do nothing (or leak to Claude).
        # M5: the raw-bytes shim must tolerate the JSON formatting variations the
        # engine's json.loads()+lstrip() handles — space after the colon, pretty/
        # multi-line JSON, and leading-whitespace escapes (\t) in the value.
        for prompt in ('{"prompt":"> ls"}', '{"prompt":"  > ls"}',
                       '{"prompt":"sethu --runner"}',
                       '{"prompt": "> ls"}',                 # space after colon
                       '{"prompt"  :  "> ls"}',              # space around colon
                       '{\n  "prompt": "> ls"\n}',           # pretty / multi-line
                       '{"prompt":"\\t> ls"}',               # JSON \t before >
                       '{"other":"x",\n "prompt":"sethu x"}',   # key not on line 1
                       '{"role":"prompt","prompt":"> ls"}'):  # decoy value == "prompt"
            r = self._run("prompt", "sethu_hook.py", {"PATH": "/nonexistent"},
                          stdin=prompt)
            self.assertEqual(r.returncode, 0, prompt)
            out = json.loads(r.stdout)               # valid JSON
            self.assertEqual(out["decision"], "block", prompt)
            self.assertIn("python3", out["reason"], prompt)

    def test_missing_python3_nonsethu_stays_silent(self):
        # M5 regression: tolerant parsing must NOT over-block. A normal prompt —
        # even one whose text merely contains a `>` — passes through silently.
        for prompt in ('{"prompt":"hello"}', '{"prompt":"is 3 > 2 true?"}',
                       '{"prompt": "just chatting"}',
                       '{"prompt":"a \\"prompt\\":\\"> x\\" in text"}'):
            r = self._run("prompt", "sethu_hook.py", {"PATH": "/nonexistent"},
                          stdin=prompt)
            self.assertEqual(r.returncode, 0, prompt)
            self.assertEqual(r.stdout.strip(), "", prompt)

    def test_present_python3_runs_hook(self):
        # With python3, the shim execs it — session_start emits the first-run
        # hint when the welcome marker is absent (fresh config dir).
        d = tempfile.mkdtemp()
        env = dict(os.environ, SETHU_CONFIG=os.path.join(d, "sethu.json"))
        r = self._run("session", "session_start.py", env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("sethu is installed", r.stdout)


class TestCoverageEnforcement(unittest.TestCase):
    """Self-enforcing coverage: every CLI argument the engine defines must be
    referenced somewhere in this test file. Add a flag without a test and CI goes
    red — no reliance on anyone remembering to update the coverage table by hand.
    (This is a presence check, not proof of assertion quality; pair with a real
    test for the flag's behavior.)"""
    def test_every_cli_arg_is_referenced_in_tests(self):
        import re
        engine = open(_engine.__file__).read()
        tests = open(__file__).read()
        calls = re.findall(r"add_argument\((.*?)\)", engine, re.DOTALL)
        args = {opt for body in calls for opt in re.findall(r'"(--[a-z-]+)"', body)}
        self.assertTrue(args, "no CLI args discovered — regex likely broke")
        missing = sorted(a for a in args if a not in tests)
        self.assertEqual(missing, [], f"CLI args with no test reference: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
