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


class TestConfig(Base):
    def test_defaults_when_missing(self):
        os.unlink(self.cfg)
        cfg = _engine.load_config()
        self.assertEqual(cfg["mode"], "cwd")
        self.assertEqual(cfg["allow"], [])
        self.assertFalse(cfg["readonly"])

    def test_roundtrip(self):
        c = _engine.load_config()
        c["allow"].append("git status")
        c["mode"] = "shell"
        _engine.save_config(c)
        self.assertEqual(_engine.load_config()["allow"], ["git status"])
        self.assertEqual(_engine.load_config()["mode"], "shell")


if __name__ == "__main__":
    unittest.main(verbosity=2)
