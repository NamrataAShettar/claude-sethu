#!/usr/bin/env python3
"""SessionStart hook: show a one-time welcome the first time sethu ever runs, so
new users discover `>`/`>>` without knowing to type `sethu`. The hint is shown
once per machine (a marker next to the config) and as a `systemMessage`, so it
costs zero API tokens. See _engine.first_run_hint for the logic + marker."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _engine  # noqa: E402


def main():
    try:
        json.load(sys.stdin)  # drain stdin; we don't need its fields
    except Exception:
        pass
    out = _engine.first_run_hint()
    if out:
        print(json.dumps(out))
    sys.exit(0)


if __name__ == "__main__":
    main()
