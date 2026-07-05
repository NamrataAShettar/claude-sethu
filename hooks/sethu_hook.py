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
    # The literal ">" mirrors _engine.DEFAULTS["prefix"] — kept here (not imported)
    # so the common non-sethu prompt never pays for importing the engine. If the
    # default prefix ever changes in DEFAULTS, update it here too.
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
    from _engine import (process, SUBCOMMANDS, ICON,  # noqa: E402
                         _c, _color_on, load_config)

    on = _color_on(load_config())

    def _lead(text):
        """The ONE guarantee that every sethu response the user sees opens with the
        |^=^| icon + `·` separator, so it's instantly recognizable as sethu (not
        their own shell or Claude). Skips when the text already leads with the icon
        (a header/help/error already embeds it), so it's never doubled. Every
        user-facing emission below routes through this."""
        if ICON in text.split("\n", 1)[0]:
            return text
        return f"{_c(ICON, 'icon', on)} {_c('·', 'dim', on)} {text}"

    # `sethu …` → run the management CLI locally, block the model.
    if is_sethu_command(prompt, SUBCOMMANDS):
        import shlex
        import subprocess
        args = prompt[len("sethu"):].strip()
        try:
            argv = shlex.split(args)
        except ValueError:
            # Unbalanced quotes: refuse rather than run with a broken argv that
            # would persist a garbage token (e.g. `sethu allow "oops`).
            _block(_lead(_c("sethu: error: mismatched quotes in that command. "
                            "Check your quoting and try again.", "fail", on)))
        try:
            run = subprocess.run(
                [sys.executable, ENGINE, *argv],
                capture_output=True, text=True, timeout=15,
            )
            text = (run.stdout or "") + (("\n" + run.stderr) if run.stderr else "")
        except Exception as e:
            text = f"sethu error: {e}"
        _block(_lead(text.strip() or "(no output)"))

    # `>`/`>>` command runner.
    result = process(prompt, data)
    if "block" in result:
        print(json.dumps({"decision": "block", "reason": _lead(result["block"])}))
    elif "context" in result:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": result["context"],
            }
        }
        # `>>` sends output to the model (costs tokens) but can't block, so the
        # user would otherwise see nothing. systemMessage shows the local
        # confirmation so the token cost is visible at the moment it's incurred.
        if result.get("note"):
            out["systemMessage"] = _lead(result["note"])
        print(json.dumps(out))
    # passthrough -> print nothing
    sys.exit(0)


if __name__ == "__main__":
    main()
