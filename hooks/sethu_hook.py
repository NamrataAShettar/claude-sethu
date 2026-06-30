#!/usr/bin/env python3
"""UserPromptSubmit hook for sethu.

Two jobs:
1. `sethu …` (bare, or `sethu -<flag>`) — runs the sethu management CLI locally
   and blocks the prompt (zero tokens). Bare `sethu` shows help/options.
2. `>`/`>>` command prompts — handled by _engine.process().

Anything else passes through to the model untouched.
"""
import json
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _engine import process, SUBCOMMANDS  # noqa: E402

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_engine.py")


def is_sethu_command(prompt):
    """`sethu`, `sethu -<flag>`, or `sethu <subcommand> …` — but not natural
    language like "sethu is great"."""
    if prompt == "sethu":
        return True
    if not prompt.startswith("sethu "):
        return False
    rest = prompt[len("sethu "):].lstrip()
    if not rest or rest[0] == "-":
        return True
    return rest.split()[0] in SUBCOMMANDS


def _block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    prompt = (data.get("prompt") or "").strip()

    # `sethu …` → run the management CLI locally, block the model.
    if is_sethu_command(prompt):
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
