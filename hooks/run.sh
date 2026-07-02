#!/bin/sh
# sethu hook launcher.
#
# sethu's hooks are Python, so they need `python3` on PATH. Rather than let a
# missing interpreter surface as a cryptic Claude Code hook error, this tiny
# POSIX-sh shim checks first and degrades gracefully:
#   • python3 present  → exec it (this process is replaced — ~no overhead).
#   • python3 missing  → don't break the user. On a prompt, pass through silently
#                        (exit 0, no output); at session start, show ONE clear
#                        message telling them to install python3.
#
# Usage (from hooks.json):  run.sh <role: prompt|session> <script.py>
role="$1"
script="$2"

if command -v python3 >/dev/null 2>&1; then
    exec python3 "$script"
fi

# python3 not found. SessionStart fires once per session, so warn there (not on
# every prompt); on a prompt, passthrough silently so typing still works.
if [ "$role" = "session" ]; then
    printf '%s\n' '{"systemMessage":"sethu needs python3, which was not found on your PATH — so sethu is inactive (your prompts still work normally). Install it (e.g. \"brew install python\", \"xcode-select --install\", or python.org), then run /reload-plugins."}'
fi
exit 0
