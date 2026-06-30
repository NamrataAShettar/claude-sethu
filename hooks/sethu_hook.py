#!/usr/bin/env python3
"""UserPromptSubmit hook for sethu — intercepts `>`/`>>` command prompts.

All logic lives in _engine.py; this just adapts its result to the hook's JSON
output: block the prompt (free), inject context (pipe to Claude), or pass
through untouched.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _engine import process  # noqa: E402


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    result = process((data.get("prompt") or "").strip(), data)

    if "block" in result:
        print(json.dumps({"decision": "block", "reason": result["block"]}))
    elif "context" in result:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": result["context"],
            }
        }))
    # passthrough -> print nothing, prompt proceeds to the model
    sys.exit(0)


if __name__ == "__main__":
    main()
