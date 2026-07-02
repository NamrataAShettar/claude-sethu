#!/usr/bin/env python3
"""Tests for sethu's engine. Stdlib only — run with:

    python3 -m unittest discover -s tests -v
    # or: python3 tests/test_sethu.py
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


class TestInteractiveFn(unittest.TestCase):
    def test(self):
        self.assertTrue(_engine.is_interactive("vim file"))
        self.assertTrue(_engine.is_interactive("top"))
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
        fresh = os.path.join(tmp, "sethu-out-deadbeef0003.log")
        for p in (old, cmd, fresh):
            open(p, "w").close()
        self.addCleanup(lambda: [os.path.exists(p) and os.unlink(p)
                                 for p in (old, cmd, fresh)])
        now = os.path.getmtime(fresh) + 100
        # Backdate two files well past the max age.
        stale = now - _engine._TEMP_MAX_AGE - 1000
        os.utime(old, (stale, stale))
        os.utime(cmd, (stale, stale))
        _engine._sweep_temp(now, force=True)   # bypass the once-an-hour throttle
        self.assertFalse(os.path.exists(old), "stale .log should be swept")
        self.assertFalse(os.path.exists(cmd), "stale .command should be swept")
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
        self.assertIn("timed out (2s)", r)
        self.assertIn("--launch", r)

    def test_config_timeout_used(self):
        # With the env override cleared, the config `timeout` drives it.
        os.environ.pop("SETHU_CMD_TIMEOUT", None)
        self.write(allow=["sleep"], timeout=1, color=False)
        cfg = _engine.load_config()
        self.assertEqual(_engine.cmd_timeout(cfg), 1)
        r = self.proc("> sleep 5")["block"]
        self.assertIn("timed out (1s)", r)

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
        self.assertIn("timed out (2s)", r)
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
        # No python3 → a prompt passes through silently (typing still works).
        r = self._run("prompt", "sethu_hook.py", {"PATH": "/nonexistent"},
                      stdin='{"prompt":"hello"}')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_present_python3_runs_hook(self):
        # With python3, the shim execs it — session_start emits the first-run
        # hint when the welcome marker is absent (fresh config dir).
        d = tempfile.mkdtemp()
        env = dict(os.environ, SETHU_CONFIG=os.path.join(d, "sethu.json"))
        r = self._run("session", "session_start.py", env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("sethu is installed", r.stdout)


class TestQuiet(unittest.TestCase):
    """bin/quiet — shrink a command's output to a tail + errors + exit code."""
    QUIET = os.path.join(os.path.dirname(HOOKS), "bin", "quiet")

    def _run(self, *args):
        return subprocess.run([sys.executable, self.QUIET, *args],
                              capture_output=True, text=True)

    def test_tail_and_hidden_counts(self):
        r = self._run("seq", "100")               # default keeps last 20
        self.assertEqual(r.returncode, 0)
        self.assertIn("100 line(s)", r.stdout)
        self.assertIn("80 hidden", r.stdout)
        self.assertTrue(r.stdout.rstrip().endswith("100"))  # last line shown
        self.assertNotIn("\n5\n", r.stdout)                 # an early line hidden

    def test_lines_flag(self):
        r = self._run("--lines", "5", "seq", "100")
        self.assertIn("95 hidden", r.stdout)

    def test_exit_code_preserved_on_failure(self):
        r = self._run("false")
        self.assertEqual(r.returncode, 1)
        self.assertIn("✗", r.stdout)
        self.assertIn("exit 1", r.stdout)

    def test_ansi_is_stripped(self):
        # ANSI in the command's OUTPUT is stripped (via a script so the ANSI is in
        # the output, not the echoed command line).
        d = tempfile.mkdtemp()
        script = os.path.join(d, "a.sh")
        with open(script, "w") as f:
            f.write(r"printf 'a\033[31mRED\033[0mb\n'" + "\n")
        r = self._run("bash", script)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("\x1b", r.stdout)
        self.assertIn("aREDb", r.stdout)

    def test_error_lines_surfaced_from_above(self):
        d = tempfile.mkdtemp()
        script = os.path.join(d, "s.sh")
        with open(script, "w") as f:
            f.write('echo "ERROR: something broke"\n'
                    'for i in $(seq 1 10); do echo "noise $i"; done\n'
                    'exit 1\n')
        r = self._run("--lines", "2", "bash", script)
        self.assertEqual(r.returncode, 1)
        self.assertIn("error lines from above", r.stdout)
        self.assertIn("ERROR: something broke", r.stdout)

    def test_no_args_usage(self):
        r = self._run()
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stdout.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
