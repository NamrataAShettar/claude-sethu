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
# stays silent. Parse with builtins only (no python3/grep), tolerating the JSON
# formatting variations Claude Code may use — pretty-printed / multi-line, and
# spaces around the colon — and matching the engine's prompt.lstrip() on the
# value (the shim sees raw bytes, so leading whitespace can be real spaces OR
# JSON escapes like \t/\n). Getting this wrong silently leaks a `>` command to
# the model instead of blocking it.
ws=$(printf ' \t\r')                              # whitespace to strip

input=
while IFS= read -r line || [ -n "$line" ]; do     # read ALL of stdin, not line 1
    input="$input$line"
done

work=$input
while :; do
    case "$work" in
        *'"prompt"'*) ;;
        *) break ;;                               # no (more) "prompt" → nothing to block
    esac
    rest=${work#*'"prompt"'}                       # after this "prompt" occurrence
    work=$rest                                     # advance, in case it's a decoy
    rest=${rest#"${rest%%[!$ws]*}"}               # strip ws after the key name
    case "$rest" in
        :*) ;;                                     # a colon follows → this is the key
        *) continue ;;                             # not a key (e.g. a value == "prompt") → keep scanning
    esac
    rest=${rest#:}                                # drop the colon
    rest=${rest#"${rest%%[!$ws]*}"}               # strip ws after the colon
    rest=${rest#\"}                               # drop the value's opening quote
    rest=${rest#"${rest%%[!$ws]*}"}               # strip real leading ws in the value
    while :; do                                   # …and leading JSON ws escapes
        case "$rest" in
            '\t'*|'\n'*|'\r'*|'\f'*)
                rest=${rest#??}
                rest=${rest#"${rest%%[!$ws]*}"} ;;
            *) break ;;
        esac
    done
    case "$rest" in
        '>'*|sethu*) printf '{"decision":"block","reason":"%s"}\n' "$msg" ;;
    esac
    break                                          # handled the real prompt key
done
exit 0
