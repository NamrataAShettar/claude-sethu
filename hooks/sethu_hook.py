#!/usr/bin/env python3
"""UserPromptSubmit hook for sethu.

Two jobs:
1. `sethu …` (bare, or `sethu -<flag>`) — runs the sethu management CLI locally
   and blocks the prompt (zero tokens). Bare `sethu` shows help/options.
2. `>`/`>>` command prompts — handled by _engine.process().

Anything else passes through to the model untouched.

PERF: this runs as a fresh python3 process on EVERY prompt the user submits. So
the common case — a normal message that isn't for sethu — is kept as cheap as
possible: we decide with only json/os/sys and DON'T import _engine (which pulls
in argparse/hashlib/socket/shlex) unless the prompt is actually a sethu command.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "_engine.py")


def _maybe_sethu(prompt):
    """Cheap gate: could this prompt be for sethu? Uses only json/os so a normal
    message returns fast without importing the engine. The default prefix is `>`;
    a custom prefix is read from config (still no _engine import)."""
    s = prompt.lstrip()
    if s.startswith("sethu") or s.startswith(">"):
        return True
    # A non-default prefix is the only other way it could be ours — read config
    # cheaply (a tiny JSON file) rather than importing _engine to find out.
    try:
        path = os.environ.get("SETHU_CONFIG") or \
            os.path.expanduser("~/.claude/sethu.json")
        with open(path) as f:
            prefix = (json.load(f) or {}).get("prefix") or ">"
        return prefix != ">" and s.startswith(prefix)
    except Exception:
        return False


def is_sethu_command(prompt, subcommands):
    """`sethu`, `sethu -<flag>`, or `sethu <subcommand> …` — but not natural
    language like "sethu is great"."""
    if prompt == "sethu":
        return True
    if not prompt.startswith("sethu "):
        return False
    rest = prompt[len("sethu "):].lstrip()
    if not rest or rest[0] == "-":
        return True
    return rest.split()[0] in subcommands


def _block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    prompt = (data.get("prompt") or "").strip()

    # Common path: not a sethu prompt → exit without importing the engine.
    if not _maybe_sethu(prompt):
        sys.exit(0)

    # It's (probably) for sethu — now pay for the heavier imports.
    sys.path.insert(0, HERE)
    from _engine import process, SUBCOMMANDS  # noqa: E402

    # `sethu …` → run the management CLI locally, block the model.
    if is_sethu_command(prompt, SUBCOMMANDS):
        import shlex
        import subprocess
        args = prompt[len("sethu"):].strip()
        try:
            argv = shlex.split(args)
        except ValueError:
            argv = args.split()
        env = dict(os.environ, NO_COLOR="1")
        try:
            run = subprocess.run(
                [sys.executable, ENGINE, *argv],
                capture_output=True, text=True, timeout=15, env=env,
            )
            text = (run.stdout or "") + (("\n" + run.stderr) if run.stderr else "")
        except Exception as e:
            text = f"sethu error: {e}"
        _block(text.strip() or "(no output)")

    # `>`/`>>` command runner.
    result = process(prompt, data)
    if "block" in result:
        print(json.dumps({"decision": "block", "reason": result["block"]}))
    elif "context" in result:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": result["context"],
            }
        }))
    # passthrough -> print nothing
    sys.exit(0)


if __name__ == "__main__":
    main()
