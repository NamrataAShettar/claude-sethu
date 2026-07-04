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
  --readonly on/off                      TestReadonlyFn, TestSafety,            [x]
                                         TestConfig, TestTrust
  --trust on/off                         TestTrust                              [x]
  --rc on/off (+ aliases actually work)  TestConfig, TestRcAliases              [x]
  state builtins hint at shell mode      TestStateBuiltinHint                   [x]
  --color on/off                         TestColor, TestConfig                  [x]
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
  readonly safety (injection / chain)    TestReadonlyFn, TestSafety             [x]
  git globals / exec-c / --ext-diff      TestReadonlyFn                         [x]
  --readonly-list + honest refusal       TestManagementCLI, TestReadonlyFn      [x]
  refusal messages explain why           TestRefusalMessages                    [x]
  timeout message cites hook budget      TestRefusalMessages                    [x]
  long-output truncation + temp file     TestTruncate                           [x]
  temp-file sweep                        TestSweep                              [x]
  socket path + 0600 perms               TestSocketPath, TestSocketPerms        [x]
  kill / reap shell daemons              TestKillDaemons                        [x]
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
        c = {"prefix": ">", "mode": "cwd", "allow": [], "launch": [], "readonly": False}
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


class TestReadonlyFn(unittest.TestCase):
    def test_safe(self):
        for c in ["ls", "ls -la", "cat f | head", "git log --oneline", "pwd",
                  "grep -n x f | head -5", "find . -name x"]:
            self.assertTrue(_engine.is_readonly_safe(c), c)

    def test_unsafe(self):
        for c in ["ls; rm -rf ~", "ls && rm", "ls || rm", "echo x > f", "cat f >> g",
                  "cat f | sh", "git push", "git reset --hard", "find . -delete",
                  "$(rm)", "ls `rm`", "ls & rm", "sed -i s/a/b/ f", "awk '{}' f"]:
            self.assertFalse(_engine.is_readonly_safe(c), c)

    def test_no_exec_wrappers(self):
        # env / command are generic launchers — must NOT be readonly-safe.
        for c in ["env rm -rf x", "env FOO=1 sh -c id", "command rm -rf x",
                  "command id"]:
            self.assertFalse(_engine.is_readonly_safe(c), c)

    def test_no_write_flags(self):
        # Read-only programs that can write a file via an option are refused.
        for c in ["sort -o /tmp/v f", "sort --output=/tmp/v f", "sort -o/tmp/v f",
                  "xxd -r hex out", "date -s 2020-01-01",
                  "git diff --output=/tmp/v", "git log --output=/tmp/v",
                  "git show --output=/tmp/v HEAD",
                  "find . -fls out", "find . -fprint0 out", "find . -okdir rm {} ;"]:
            self.assertFalse(_engine.is_readonly_safe(c), c)

    def test_write_flag_guard_no_overblock(self):
        # …but legit read-only invocations of the same programs still pass.
        for c in ["sort f", "sort -r f", "sort -n f", "xxd f", "date",
                  "git diff", "git show HEAD", "find . -follow", "find . -name x"]:
            self.assertTrue(_engine.is_readonly_safe(c), c)

    def test_git_global_options_readonly(self):
        # M2: a read-only git subcommand stays read-only behind leading globals.
        for c in ["git -C /tmp status", "git --no-pager log", "git -p diff",
                  "git --git-dir=/r/.git log", "git -C /tmp --no-pager show HEAD",
                  "git --literal-pathspecs ls-files"]:
            self.assertTrue(_engine.is_readonly_safe(c), c)

    def test_git_global_options_still_refuse_writes(self):
        # M2: globals must not smuggle a write subcommand past the gate…
        for c in ["git -C /tmp push", "git --no-pager reset --hard",
                  "git --git-dir=/r/.git commit -m x"]:
            self.assertFalse(_engine.is_readonly_safe(c), c)

    def test_git_exec_globals_refused(self):
        # M2/security: -c / --config-env / --exec-path can run arbitrary code even
        # in front of a read-only subcommand, so they're never read-only.
        for c in ["git -c core.pager=evil log", "git -c alias.x='!sh' status",
                  "git --exec-path=/evil status",
                  "git --config-env=core.pager=X log"]:
            self.assertFalse(_engine.is_readonly_safe(c), c)

    def test_git_ext_diff_refused(self):
        # L1 (shipped with M2): --ext-diff runs the configured external diff program.
        for c in ["git log --ext-diff", "git show --ext-diff HEAD",
                  "git -C /tmp diff --ext-diff"]:
            self.assertFalse(_engine.is_readonly_safe(c), c)

    def test_why_refused_git_globals(self):
        # M2: refusal reasons stay accurate through leading globals.
        cfg = {"readonly": True}
        self.assertIn("push", _engine._why_refused("git --no-pager push", cfg))
        self.assertIn("arbitrary code",
                      _engine._why_refused("git -c core.pager=x log", cfg))
        self.assertIn("--ext-diff",
                      _engine._why_refused("git log --ext-diff", cfg))

    def test_why_refused_unknown_is_honest(self):
        # An unrecognized command is genuinely read-only but not in our set — the
        # refusal must say "doesn't recognize", not the false "isn't a read-only
        # command", and point to the list.
        msg = _engine._why_refused("bat file.txt", {"readonly": True})
        self.assertIn("doesn't recognize", msg)
        self.assertIn("bat", msg)
        self.assertIn("--readonly-list", msg)
        self.assertNotIn("isn't a read-only command", msg)


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


class TestSafety(Base):
    def test_not_allowed_refused(self):
        r = self.proc("> rm -rf /tmp/x")
        self.assertIn("isn't allowed", r["block"])

    def test_readonly_blocks_dangerous(self):
        self.write(readonly=True)
        for c in ["ls; rm -rf ~", "echo x > /tmp/f", "cat README | sh", "git push"]:
            self.assertIn("isn't allowed", self.proc("> " + c)["block"], c)

    def test_interactive_allowlisted_is_refused(self):
        self.write(allow=["vi"])
        self.assertIn("interactive", self.proc("> vi")["block"])

    def test_allowlist_no_pipe_injection(self):
        # Allowing `ls` must NOT permit `ls | rm -rf x` (the reported bug).
        self.write(allow=["ls"])
        self.assertIn("isn't allowed", self.proc("> ls | grep x | rm -rf x")["block"])
        self.assertIn("isn't allowed", self.proc("> ls; rm -rf x")["block"])
        self.assertIn("isn't allowed", self.proc("> ls && rm -rf x")["block"])
        self.assertIn("isn't allowed", self.proc("> ls $(rm)")["block"])
        # but plain args are still fine
        self.assertNotIn("isn't allowed", self.proc("> ls -la")["block"])

    def test_allowlist_no_newline_injection(self):
        self.write(allow=["ls"])
        self.assertIn("isn't allowed", self.proc("> ls\nrm -rf x")["block"])

    def test_quoted_metachars_are_allowed(self):
        # A `;`/`|` INSIDE quotes is argument text, not a command chain, so an
        # allowlisted interpreter with a `-c` one-liner is permitted.
        self.write(allow=["python3", "echo"])
        for c in ['python3 -c "import os; print(os.getpid())"',
                  "python3 -c 'a; b; c'",
                  'echo "a|b;c"']:
            self.assertNotIn("isn't allowed", self.proc("> " + c)["block"], c)

    def test_unquoted_ops_still_refused_with_interpreter(self):
        # But a real unquoted chain after the interpreter is still refused.
        self.write(allow=["python3"])
        for c in ['python3 -c "print(1)" ; rm -rf x',
                  "python3 -c \"print(1)\" | sh",
                  'python3 script.py > /etc/passwd',
                  'python3 -c "print(1)" && rm x']:
            self.assertIn("isn't allowed", self.proc("> " + c)["block"], c)

    def test_command_substitution_refused_even_quoted(self):
        # $( ), ${ }, backticks expand even inside double quotes → always refused.
        self.write(allow=["echo"])
        for c in ['echo "$(rm -rf x)"', 'echo "${HOME}"', 'echo "`rm`"']:
            self.assertIn("isn't allowed", self.proc("> " + c)["block"], c)

    def test_readonly_no_newline_injection(self):
        self.write(readonly=True)
        self.assertIn("isn't allowed", self.proc("> ls\nrm -rf x")["block"])

    def test_readonly_git_writes_refused(self):
        self.write(readonly=True)
        for c in ["git config user.name hacked", "git stash", "git branch -D main",
                  "git tag -d v1", "git remote add evil url"]:
            self.assertIn("isn't allowed", self.proc("> " + c)["block"], c)


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
                  "Read-only by default"]:
            self.assertIn(t, out, t)

    def test_runner_and_show_print_config(self):
        for flag in (["--runner"], ["--show"]):
            out = self._out(flag)
            self.assertIn("mode:", out, flag)
            self.assertIn("default", out, flag)   # shows each field's default

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

    def test_empty_arg_says_nothing_not_config_dump(self):
        # UX10: `--allow ""` must say so, not silently dump the whole config.
        self.write(allow=[])
        for flag in ("--allow", "--unallow", "--launch", "--unlaunch"):
            out = self._out([flag, ""])
            self.assertIn("nothing to", out, flag)
            self.assertNotIn("sethu config", out, flag)  # not the --runner view

    def test_readonly_list_prints_set_and_guards(self):
        out = self._out(["--readonly-list"])
        for t in ["ls", "git", "jq",                       # curated names shown
                  "--ext-diff", "git writes",              # flag guards explained
                  'sethu --allow "<command>"']:            # the escape hatch
            self.assertIn(t, out, t)
        # Sorted → stable output (set iteration order is not).
        self.assertEqual(out, self._out(["--readonly-list"]))

    def test_bad_arg_error_is_branded(self):
        # A bad flag gives a branded, concise error (icon + 'error:' + menu
        # pointer), not argparse's plain usage wall.
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), self.assertRaises(SystemExit):
            _engine.main(["--mode", "nope"])
        err = buf.getvalue()
        self.assertIn(_engine.ICON, err)
        self.assertIn("sethu: error:", err)
        self.assertIn("options menu", err)


class TestHeaderFormat(Base):
    """Pins the exact header across permutations (color off), so a spacing or
    separator regression fails here instead of by eye. Catches the class of bug
    where a part (e.g. ⚠trust) wasn't `·`-separated."""
    def test_run_header(self):
        self.write(readonly=True, color=False)
        h = self.proc("> ls")["block"].split("\n")[0]
        self.assertEqual(h, "|^=^| · [cwd] · ✓ exit 0 · $ ls")

    def test_refusal_header_omits_status(self):
        self.write(readonly=True, color=False)
        h = self.proc("> git branch")["block"].split("\n")[0]
        self.assertEqual(h, "|^=^| · [cwd] · $ git branch")

    def test_trust_segment_is_dot_separated(self):
        # regression: ⚠trust used to be space-glued to the [mode] tag.
        self.write(mode="shell", trust=True, readonly=False, color=False)
        h = self.proc("> claude")["block"].split("\n")[0]  # interactive refusal
        self.assertEqual(h, "|^=^| · [shell] · ⚠trust · $ claude")


class TestFullScreenTUI(Base):
    def test_known_tui_refused_as_interactive(self):
        # claude / lazygit / etc. are in the interactive list -> upfront --launch.
        self.write(readonly=True, color=False)
        self.assertIn("interactive", self.proc("> claude --plugin-dir ~/x")["block"])

    def test_unknown_tui_alt_screen_gets_hint(self):
        # A TUI captured mid-draw emits the alt-screen escape AND fails/times out;
        # sethu detects the escape (on a non-clean exit) and points at --launch.
        self.write(mode="stateless", trust=True, readonly=False, color=False)
        b = self.proc(r"> printf '\033[?1049hUI'; false")["block"]  # escape, exit 1
        self.assertIn("full-screen program", b)
        self.assertIn("--launch", b)

    def test_alt_screen_on_clean_exit_no_hint(self):
        # A command that legitimately prints those bytes and exits 0 must NOT trip
        # the hint (false-positive guard).
        self.write(mode="stateless", trust=True, readonly=False, color=False)
        self.assertNotIn("full-screen program",
                         self.proc(r"> printf '\033[?1049hUI'")["block"])

    def test_plain_output_gets_no_hint(self):
        self.write(readonly=True, color=False)
        self.assertNotIn("full-screen program", self.proc("> ls")["block"])

    def test_command_ansi_is_reset_to_prevent_bleed(self):
        # A command that leaves a colour/attribute open gets a trailing reset so it
        # doesn't bleed into the rest of the transcript. Plain output doesn't.
        self.write(trust=True, readonly=False, color=False)
        self.assertTrue(self.proc(r"> printf '\033[33mopen'")["block"].endswith("\x1b[0m"))
        self.assertFalse(self.proc("> printf plain")["block"].endswith("\x1b[0m"))


class TestRefusalMessages(Base):
    def test_interactive_leads_with_launch_not_allow(self):
        # Interactive commands point to --launch (allowlisting can't make them run).
        self.write(readonly=True, color=False)
        for c in ["vim", "python3", "top"]:
            b = self.proc("> " + c)["block"]
            self.assertIn("--launch", b, c)
            self.assertIn("interactive", b, c)
            self.assertNotIn('sethu --allow', b, c)   # allow is futile here

    def test_refusal_explains_why_and_still_offers_allow(self):
        self.write(readonly=True, color=False)
        cases = {
            "git branch": "change the repo",
            "sort -o out f": "writes a file",
            "npm test": "doesn't recognize `npm`",
            "ls; rm -rf ~": "joined by",
        }
        for cmd, why in cases.items():
            b = self.proc("> " + cmd)["block"]
            self.assertIn(why, b, cmd)
            self.assertIn('sethu --allow', b, cmd)   # still offered (user's call)

    def test_timeout_message_mentions_hook_budget(self):
        self.assertIn("hook budget", _engine._timeout_msg(20, "sleep 99"))

    def test_refusal_has_unified_header_without_status(self):
        # Every response shares the header format; a refusal echoes the command but
        # omits the exit-status slot (it never ran), so it can't be mislabelled.
        self.write(readonly=True, color=False)
        first = self.proc("> git branch")["block"].split("\n")[0]
        self.assertIn("[cwd]", first)          # mode tag
        self.assertIn("$ git branch", first)   # command echoed in the header
        self.assertNotIn("exit", first)        # but NO exit status
        # a real run DOES show a status
        self.assertIn("exit 0", self.proc("> ls")["block"].split("\n")[0])

    def test_refusal_offers_safer_path_when_one_exists(self):
        # Where a read-only way exists, the message points to it (not only --allow).
        self.write(readonly=True, color=False)
        self.assertIn("Drop the flag", self.proc("> sort -o out f")["block"])
        self.assertIn("separate", self.proc("> ls; rm -rf ~")["block"])


class TestTrust(Base):
    def test_trust_bypasses_allowlist(self):
        self.write(trust=True)  # nothing allowlisted
        r = self.proc("> echo trusted")
        self.assertNotIn("isn't allowed", r["block"])
        self.assertIn("trusted", r["block"])

    def test_trust_marker_in_header(self):
        self.write(trust=True)
        self.assertIn("trust", self.proc("> echo x")["block"])

    def test_trust_still_refuses_interactive(self):
        self.write(trust=True)
        self.assertIn("interactive", self.proc("> vim x")["block"])

    def test_readonly_clears_trust(self):
        self.write(trust=True)
        _engine.main(["--readonly", "on"])
        cfg = _engine.load_config()
        self.assertTrue(cfg["readonly"])
        self.assertFalse(cfg["trust"])

    def test_trust_clears_readonly(self):
        self.write(readonly=True)
        _engine.main(["--trust", "on"])
        cfg = _engine.load_config()
        self.assertTrue(cfg["trust"])
        self.assertFalse(cfg["readonly"])

    def test_readonly_wins_when_both_set(self):
        # Legacy config with both on → readonly behavior (a write is refused).
        self.write(readonly=True, trust=True)
        r = self.proc("> mkdir nope")
        self.assertIn("isn't allowed", r["block"])
        self.assertNotIn("trust", r["block"])


class TestRunner(Base):
    def test_batch_python_runs_when_allowed(self):
        # End-to-end: allowlisted `python <script>` runs captured (not refused as
        # interactive) — the refinement that lets scripts run in the runner.
        self.write(allow=["python3"])
        script = os.path.join(self.tmp, "s.py")
        with open(script, "w") as f:
            f.write("print('hi from script')")
        r = self.proc("> python3 " + script)["block"]
        self.assertNotIn("isn't allowed", r)
        self.assertNotIn("interactive", r)
        self.assertIn("hi from script", r)

    def test_bare_python_still_refused_as_interactive(self):
        self.write(allow=["python3"])
        self.assertIn("interactive", self.proc("> python3")["block"])

    def test_explicit_allow_runs(self):
        self.write(allow=["echo"])
        r = self.proc("> echo hello")
        self.assertNotIn("isn't allowed", r["block"])
        self.assertIn("hello", r["block"])

    def test_readonly_allows_inspection(self):
        self.write(readonly=True)
        r = self.proc("> ls")
        self.assertNotIn("isn't allowed", r["block"])

    def test_completion_header(self):
        self.write(readonly=True)
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
        self.write(readonly=True, color=False)
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
        self.write(readonly=True, color=False)
        self.assertIn(_engine.ICON + " · [cwd]", self.proc("> ls")["block"])


class TestColor(Base):
    def test_header_colored_by_default(self):
        os.environ.pop("NO_COLOR", None)
        self.write(readonly=True)
        self.assertIn("\033[", self.proc("> ls")["block"])  # ANSI present

    def test_color_off_strips_ansi(self):
        self.write(readonly=True, color=False)
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
        self.write(readonly=True)
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
        self.assertIn("full output:", r)        # points at the file
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
        os.utime(sentinel, (now - 10, now - 10))                  # swept 10s ago
        _engine._sweep_temp(now)                                  # throttled → skip
        self.assertTrue(os.path.exists(old), "recent sweep must skip the scan")
        _engine._sweep_temp(now, force=True)                      # forced → runs
        self.assertFalse(os.path.exists(old))


class TestLeadingWhitespace(Base):
    def test_space_before_prefix_still_intercepts(self):
        self.write(readonly=True)
        r = self.proc("   > pwd")            # stray leading spaces
        self.assertNotIn("passthrough", r)   # handled, not leaked to the model
        self.assertIn("pwd", r["block"])

    def test_plain_prompt_still_passes_through(self):
        self.assertEqual(self.proc("just talking to claude"), {"passthrough": True})

    def test_prefix_mid_prompt_does_not_trigger(self):
        # `>` only triggers at the START of a prompt — never mid-text, so prompts
        # that merely mention `>` are not intercepted.
        self.write(readonly=True)
        for p in ["compare a > b in the code", "if x > 0 then run it",
                  "note a>b matters", "use foo > bar as an example"]:
            self.assertEqual(self.proc(p), {"passthrough": True}, p)
            self.assertFalse(sethu_hook._maybe_sethu(p), p)


class TestCwdMode(Base):
    def test_cd_persists(self):
        self.write(readonly=True)
        self.proc("> cd /tmp")
        r = self.proc("> pwd")
        self.assertIn("tmp", r["block"])

    def test_stateless_cd_message(self):
        self.write(mode="stateless")
        self.assertIn("stateless", self.proc("> cd /tmp")["block"])


class TestModeSwitching(Base):
    def test_switch_cwd_to_stateless_changes_cd_behavior(self):
        sid = "ms-cwd"
        self.write(mode="cwd", readonly=True, color=False)
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

    def test_shell_disables_pager(self):
        # Regression: paged commands (git log/branch) must not hang under the PTY.
        sid = "test-shell-pager"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", allow=["echo"])
        r = self.proc("> echo PG=$GIT_PAGER", sid=sid)
        self.assertIn("PG=cat", r["block"])

    def test_real_uuid_session_id(self):
        # Regression: a full-length UUID must not overflow the AF_UNIX path.
        sid = "a253f39f-aecf-416f-b1f0-2702df515154"
        self.addCleanup(self._shutdown, sid)
        self.write(mode="shell", allow=["echo"])
        r = self.proc("> echo runs_ok", sid=sid)
        self.assertIn("runs_ok", r["block"])
        self.assertNotIn("path too long", r["block"])


class TestStateBuiltinHint(Base):
    def test_state_builtin_in_nonshell_hints_shell_mode(self):
        # export/source/alias/… only persist in shell mode; cwd/stateless should
        # proactively point there instead of silently no-op'ing or refusing.
        for m in ("cwd", "stateless"):
            self.write(mode=m, readonly=True, color=False)
            for c in ["export FOO=1", "source venv/bin/activate", "alias g=git",
                      ". env/bin/activate", "unset PATHX"]:
                b = self.proc("> " + c)["block"]
                self.assertIn("shell mode", b, f"{m}: {c}")
                self.assertIn("--mode shell", b, f"{m}: {c}")


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
        self.assertEqual(n(["readonly", "on"]), ["--readonly", "on"])
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


class TestConfig(Base):
    def test_defaults_when_missing(self):
        os.unlink(self.cfg)
        cfg = _engine.load_config()
        self.assertEqual(cfg["mode"], "cwd")
        self.assertEqual(cfg["allow"], [])
        self.assertTrue(cfg["readonly"])   # read-only mode is ON by default
        self.assertFalse(cfg["rc"])
        self.assertTrue(cfg["color"])

    def test_readonly_default_allows_inspection_refuses_writes(self):
        # With no config at all, read-only commands run and writes are refused.
        os.unlink(self.cfg)
        self.assertNotIn("isn't allowed", self.proc("> ls")["block"])
        self.assertIn("isn't allowed", self.proc("> rm -rf /tmp/x")["block"])

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

    def test_malformed_config_types_fall_back(self):
        # A hand-edited config with wrongly-typed values falls back per key
        # instead of crashing callers that index/append.
        with open(self.cfg, "w") as f:
            json.dump({"allow": "ls", "launch": 5, "readonly": "off",
                       "prefix": 9, "mode": ["x"]}, f)
        c = _engine.load_config()
        self.assertEqual(c["allow"], [])       # non-list -> default []
        self.assertEqual(c["launch"], [])
        self.assertIs(c["readonly"], True)     # "off" (str) isn't a bool -> default
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
        self.write(prefix="!!", readonly=True, color=False)
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
        self.write(readonly=True)
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
        self.assertIn("sethu: error:", out["reason"])      # matches the CLI error format
        self.assertNotIn('"oops', _engine.load_config()["allow"])

    def test_run_command_emits_block(self):
        self.write(readonly=True)
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
                       '{"other":"x",\n "prompt":"sethu x"}'):  # key not on line 1
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
