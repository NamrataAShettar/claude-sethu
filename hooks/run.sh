#!/bin/sh
# sethu hook launcher.
#
# sethu's hooks are Python, so they need `python3` on PATH. Rather than let a
# missing interpreter surface as a cryptic Claude Code hook error, this tiny
# POSIX-sh shim checks first and degrades gracefully:
#   • python3 present → exec it (this process is replaced, ~no overhead).
#   • python3 missing → don't break the user:
#       - session start                       → one clear systemMessage.
#       - a sethu-looking prompt (> … / sethu) → block it with the same guidance,
#         so the user isn't left wondering why nothing ran (and the command
#         doesn't silently leak to the model).
#       - any other prompt                    → pass through silently (typing works).
# The degraded path uses only shell builtins (no cat/grep), so it still works when
# PATH is minimal or broken, which is exactly when python3 tends to be missing.
#
# Usage (from hooks.json):  run.sh <role: prompt|session> <script.py>
role="$1"
script="$2"

if command -v python3 >/dev/null 2>&1; then
    exec python3 "$script"
fi

# python3 not found. Message uses no double quotes so it is safe to embed in JSON.
msg='sethu needs python3, which was not found on your PATH, so sethu is inactive. Install it (brew install python, xcode-select --install, or python.org), then run /reload-plugins.'

if [ "$role" = "session" ]; then
    printf '{"systemMessage":"%s"}\n' "$msg"
    exit 0
fi

# Prompt role: only speak up if this looks like a sethu command, so normal typing
# stays silent. Parse with builtins only.
IFS= read -r input
case "$input" in
    *'"prompt":"'*)
        rest=${input#*'"prompt":"'}          # text after the prompt key
        while [ "${rest# }" != "$rest" ]; do rest=${rest# }; done  # strip spaces
        case "$rest" in
            '>'*|sethu*) printf '{"decision":"block","reason":"%s"}\n' "$msg" ;;
        esac
        ;;
esac
exit 0
