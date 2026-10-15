#!/usr/bin/env python3
"""sethu auto-quiet — PostToolUse hook.

Shrinks the output of verbose SUCCESSFUL Bash commands Claude runs through its own
Bash tool, before it enters the model's context (fewer tokens). Only acts on
allowlisted, non-inspection, un-chained commands with large output, and only when
auto-quiet is turned on. See docs / FEATURE-EXPLORATION-auto-quiet.md for the full
behavior matrix.

Hot-path discipline (like `sethu_hook._maybe_sethu`): decide with `json`/`os` only and
return WITHOUT importing `_engine` when auto-quiet is off or this is not a Bash call —
so the common case costs almost nothing. The engine is imported only when the hook will
actually do work.

FAIL-OPEN everywhere: on any error, or when nothing should change, emit nothing and the
ORIGINAL tool output stands (the platform passes it through unchanged).
"""
import json
import os
import sys


def _autoquiet_on():
    """Cheap gate: is auto-quiet turned on? stdlib only, default OFF on any problem
    (missing/malformed config), so the hot path never imports the engine when off."""
    path = os.environ.get("SETHU_CONFIG") or os.path.expanduser("~/.claude/sethu.json")
    try:
        with open(path) as f:
            c = json.load(f)
        return isinstance(c, dict) and c.get("autoquiet") is True
    except Exception:
        return False


def main():
    try:
        ev = json.loads(sys.stdin.read())
    except Exception:
        return  # malformed hook input -> passthrough
    if not isinstance(ev, dict) or ev.get("tool_name") != "Bash":
        return  # only Bash; no engine import for anything else
    if not _autoquiet_on():
        return  # off -> passthrough, without importing the engine (hot path)
    # It is an on, Bash call: hand off to the engine, which does the real gating + shrink.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import _engine
        out = _engine.autoquiet_process(ev)
    except Exception:
        return  # fail-open
    if out:
        sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
