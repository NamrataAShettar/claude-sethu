#!/usr/bin/env python3
"""Tests for sethu's engine. Stdlib only — run with:

    python3 -m unittest discover -s tests -v
    # or: python3 tests/test_sethu.py
"""
import json
import os
import socket
import sys
import tempfile
import unittest

HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
sys.path.insert(0, HOOKS)
import _engine  # noqa: E402
import _shelld  # noqa: E402


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


class TestInteractiveFn(unittest.TestCase):
    def test(self):
        self.assertTrue(_engine.is_interactive("vim file"))
        self.assertTrue(_engine.is_interactive("top"))
        self.assertFalse(_engine.is_interactive("ls -la"))
        self.assertFalse(_engine.is_interactive(""))


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
    def _big(self, n):
        # `seq N` prints 1..N, one per line — a cheap large output.
        return "; ".join(["seq %d" % n])

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


class TestLeadingWhitespace(Base):
    def test_space_before_prefix_still_intercepts(self):
        self.write(readonly=True)
        r = self.proc("   > pwd")            # stray leading spaces
        self.assertNotIn("passthrough", r)   # handled, not leaked to the model
        self.assertIn("pwd", r["block"])

    def test_plain_prompt_still_passes_through(self):
        self.assertEqual(self.proc("just talking to claude"), {"passthrough": True})


class TestCwdMode(Base):
    def test_cd_persists(self):
        self.write(readonly=True)
        self.proc("> cd /tmp")
        r = self.proc("> pwd")
        self.assertIn("tmp", r["block"])

    def test_stateless_cd_message(self):
        self.write(mode="stateless")
        self.assertIn("stateless", self.proc("> cd /tmp")["block"])


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
        self.assertFalse(cfg["readonly"])
        self.assertFalse(cfg["rc"])
        self.assertTrue(cfg["color"])

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
