#!/usr/bin/env python3
"""sethu (सेतु, "bridge") — run commands from Claude Code's prompt box.

Type a command prefixed with `>` as a normal message and the UserPromptSubmit
hook intercepts it, runs it locally, and blocks the prompt — so it costs zero
API tokens (the model never sees it). `>>` instead pipes the output into
Claude's context so it can act on the result.

Safety: commands run only if they're on your allowlist (empty by default).
`cd` is exempt (it just moves the working directory, runs nothing).

Statefulness has three selectable modes (`sethu --mode <mode>`):
  • stateless — each command is its own subprocess; cd doesn't persist
  • cwd       — a per-session working directory persists across commands (cd works)
  • shell     — a real persistent bash (PTY daemon); cd, export, source, venvs
                all persist

This file is both the importable engine (used by the hook) and the management
CLI (`sethu --allow ...`, `--mode ...`, `--runner`).
"""
import argparse
import glob
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time

DEFAULTS = {"prefix": ">", "mode": "cwd", "allow": [], "launch": [],
            "readonly": False, "trust": False, "rc": False, "color": True,
            "maxLines": 40}
MODES = ("stateless", "cwd", "shell")

# Max seconds a captured command may run before it's timed out and the user is
# pointed at `--launch`. Kept safely under Claude Code's UserPromptSubmit hook
# budget (~30s). Override with SETHU_CMD_TIMEOUT (the daemon inherits it too).
# _shelld.py mirrors this — keep the two in sync.
CMD_TIMEOUT = 20


def cmd_timeout():
    try:
        return int(os.environ.get("SETHU_CMD_TIMEOUT") or CMD_TIMEOUT)
    except ValueError:
        return CMD_TIMEOUT

# ANSI colors for the result header. Colorblind-safe (blue/orange, not green/red)
# per Okabe-Ito. Off via `sethu --color off` or the NO_COLOR env var. Only the
# header is colored — the command's own output is left untouched.
_ANSI = {
    "ok": "38;5;75",       # sky blue   — success (exit 0)
    "fail": "1;38;5;203",  # bold red   — nonzero exit (errors stand out)
    "warn": "38;5;214",    # amber      — no exit code (timeout/unknown)
    "tag": "38;5;37",      # teal       — the [mode] tag
    "trust": "38;5;208",   # orange     — the ⚠trust warning
    "cmd": "1",            # bold       — the command that ran
    "dim": "2",            # dim        — separators ( · $ )
}


# sethu's keyboard-key bridge icon: towers (|), cables dipping to the deck (^=^).
ICON = "|^=^|"


def _color_on(cfg):
    return bool(cfg.get("color", True)) and not os.environ.get("NO_COLOR")


def _c(text, key, on):
    return f"\033[{_ANSI[key]}m{text}\033[0m" if on else text


def _output_path(sid):
    """Stable per-session file holding the LAST command's full output. Reused
    (overwritten) each command, so a session never accumulates more than one."""
    h = hashlib.md5((sid or "default").encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"sethu-out-{h}.log")


# How long sethu's own temp files (saved output + launch scripts) live before the
# opportunistic sweep removes them. Stops storage bloat across many sessions
# without depending on the OS to purge the temp dir.
_TEMP_MAX_AGE = 7 * 24 * 3600  # 7 days


def _sweep_temp(now):
    """Best-effort: delete sethu's leftover temp files older than _TEMP_MAX_AGE.
    `now` is passed in (time.time()) so it's testable and side-effect-free here.
    Sockets are left alone — the daemon manages their lifecycle."""
    tmp = tempfile.gettempdir()
    for pat in ("sethu-out-*.log", "sethu-launch-*.command"):
        for p in glob.glob(os.path.join(tmp, pat)):
            try:
                if now - os.path.getmtime(p) > _TEMP_MAX_AGE:
                    os.unlink(p)
            except OSError:
                pass


def _truncate(out, sid, max_lines, on):
    """If `out` exceeds max_lines, keep the first max_lines and write the full
    text to the per-session file, returning (display, note). Otherwise return
    (out, ""). max_lines <= 0 disables truncation. note is a short pointer at
    the full output for the caller to place (colored for display, plain for the
    pipe-to-Claude path)."""
    if max_lines <= 0:
        return out, ""
    lines = out.split("\n")
    if len(lines) <= max_lines:
        return out, ""
    path = _output_path(sid)
    try:
        with open(path, "w") as f:
            f.write(out)
    except Exception:
        path = None
    hidden = len(lines) - max_lines
    shown = "\n".join(lines[:max_lines])
    where = (f"full output: {path}  (open it, or `sethu --launch \"less {path}\"`)"
             if path else "full output unavailable (couldn't write temp file)")
    note = f"… {hidden} more line{'s' if hidden != 1 else ''} truncated · {where}"
    return shown, note


# ── config ───────────────────────────────────────────────────────────────────
def config_path():
    return os.environ.get("SETHU_CONFIG") or os.path.expanduser("~/.claude/sethu.json")


def _welcome_marker():
    return os.path.join(os.path.dirname(config_path()), ".sethu-welcomed")


FIRST_RUN_HINT = (
    f"{ICON} sethu is installed — run terminal commands free from this box. "
    "`> git status` shows output to you only (zero tokens); `>> git status` "
    "sends it to Claude. Nothing runs until you allow it — try "
    "`sethu --readonly on`, then type `sethu` for a \"when to use what\" guide."
)


def first_run_hint():
    """Return {'systemMessage': ...} the first time sethu ever runs, else None.

    Shown once per machine (a marker file next to the config), so new users
    discover `>`/`>>` without knowing to type `sethu`. systemMessage is shown to
    the user, not added to the model context, so it costs zero API tokens."""
    marker = _welcome_marker()
    if os.path.exists(marker):
        return None
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        open(marker, "w").close()
    except Exception:
        pass
    return {"systemMessage": FIRST_RUN_HINT}


def load_config():
    cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    try:
        with open(config_path()) as f:
            user = json.load(f)
        if isinstance(user, dict):
            for k in DEFAULTS:
                if k in user:
                    cfg[k] = user[k]
    except Exception:
        pass
    return cfg


def save_config(cfg):
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({k: cfg[k] for k in DEFAULTS}, f, indent=2)
        f.write("\n")


# ── allow / launch matching ───────────────────────────────────────────────────
# Shell metacharacters that chain to *another* command (pipe, redirect, &&/;,
# substitution, backtick). An allowlisted command may be followed by plain
# arguments only — NOT a pipe/redirect to something unallowed. Without this,
# allowing `ls` would also allow `ls | rm -rf x` via prefix matching.
_ALLOW_META = re.compile(r"[;&|<>`\n\r]|\$\(")


def _matches(cmd, entries):
    cmd = cmd.strip()
    for e in entries:
        if cmd == e:
            return True
        if cmd.startswith(e + " ") and not _ALLOW_META.search(cmd):
            return True
    return False


def is_cd(cmd):
    return cmd == "cd" or cmd.startswith("cd ")


# ── per-session working directory (cwd mode) ──────────────────────────────────
def _cwd_file(sid):
    safe = "".join(c for c in (sid or "default") if c.isalnum() or c in "-_")
    return os.path.join(tempfile.gettempdir(), f"sethu-cwd-{safe}")


def get_cwd(sid, default):
    try:
        with open(_cwd_file(sid)) as f:
            p = f.read().strip()
        if p and os.path.isdir(p):
            return p
    except Exception:
        pass
    return default if (default and os.path.isdir(default)) else os.path.expanduser("~")


def set_cwd(sid, path):
    try:
        with open(_cwd_file(sid), "w") as f:
            f.write(path)
    except Exception:
        pass


def resolve_cd(arg, base):
    arg = (arg or "").strip().strip('"').strip("'")
    if not arg or arg == "~":
        return os.path.expanduser("~")
    arg = os.path.expanduser(arg)
    if not os.path.isabs(arg):
        arg = os.path.join(base, arg)
    return os.path.normpath(arg)


# ── command execution ─────────────────────────────────────────────────────────
# Programs that take over the terminal — they can't run captured (they'd hang),
# so the runner refuses them and points you at `--launch` (a real terminal).
INTERACTIVE = {
    "vi", "vim", "nvim", "nano", "emacs", "pico", "less", "more", "most", "man",
    "top", "htop", "btop", "ssh", "telnet", "tmux", "screen", "watch", "fg",
    "python", "python3", "node", "irb", "psql", "mysql", "sqlite3", "ipython",
}

# Interpreters/REPLs that are only interactive when launched *bare* (or `-i`).
# With a script, `-c CODE`, or `-m MODULE` they run to completion and return, so
# they're fine for the captured runner. `python script.py` is batch; `python` is
# a REPL. `-i` forces the prompt open, so it stays interactive.
_REPL = {"python", "python3", "node", "irb", "ipython"}


def is_interactive(cmd):
    toks = cmd.split()
    if not toks:
        return False
    prog = os.path.basename(toks[0])
    if prog in _REPL:
        args = toks[1:]
        if "-i" in args:
            return True  # explicit interactive flag
        # Any non-flag argument (a script path) or -c/-m means batch mode.
        for i, a in enumerate(args):
            if a in ("-c", "-m"):
                return False
            if not a.startswith("-"):
                return False  # a script path → runs and exits
        return True  # bare `python`, or only passive flags → REPL
    return prog in INTERACTIVE


# Read-only inspection programs auto-allowed when `readonly` mode is on. Kept
# conservative on purpose — no sed/awk/xargs/tee (they can write or exec).
READONLY = {
    "ls", "cat", "head", "tail", "wc", "pwd", "echo", "printf", "stat", "file",
    "tree", "which", "type", "command", "date", "whoami", "id", "uname",
    "hostname", "uptime", "df", "du", "ps", "env", "printenv", "grep", "egrep",
    "fgrep", "rg", "ag", "cut", "sort", "uniq", "tr", "column", "jq", "yq",
    "basename", "dirname", "realpath", "readlink", "nl", "tac", "comm", "diff",
    "cmp", "shasum", "md5", "sha256sum", "cksum", "hexdump", "xxd", "strings",
    "cal", "look", "fold", "fmt", "rev", "find", "fd", "git",
}
# Only unambiguously read-only git subcommands. Excluded: branch/tag/remote
# (delete/create with flags), stash (mutates), config (writes with `key value`).
# Allowlist those explicitly if you need them.
READONLY_GIT = {
    "status", "log", "diff", "show", "describe", "blame", "ls-files",
    "rev-parse", "shortlog", "rev-list", "cat-file", "reflog",
}
# Shell metacharacters that enable writes / chaining / substitution / background
# (newlines included — a multi-line prompt is multiple commands).
_DANGER = re.compile(r"[;&`<>\n\r]|\$\(")


def is_readonly_safe(cmd):
    """True only if `cmd` is a pipeline of read-only programs with no
    redirection, chaining, command substitution, or backgrounding."""
    if _DANGER.search(cmd):
        return False
    for seg in cmd.split("|"):
        toks = seg.split()
        if not toks:                      # empty segment ⇒ `||`, trailing `|`, etc.
            return False
        prog = os.path.basename(toks[0])
        if prog == "git":
            sub = toks[1] if len(toks) > 1 else ""
            if sub not in READONLY_GIT:
                return False
        elif prog == "find":
            if any(t in ("-exec", "-execdir", "-delete", "-ok", "-fprint",
                         "-fprintf") for t in toks):
                return False
        elif prog not in READONLY:
            return False
    return True


def run_capture(cmd, cwd=None):
    """Run `cmd`, return (output, exit_code). exit_code is None on timeout/error."""
    # GIT_PAGER/PAGER=cat so paged commands (git log, etc.) never block on a pager.
    env = dict(os.environ, NO_COLOR="1", PAGER="cat", GIT_PAGER="cat")
    try:
        # stdin=DEVNULL so a program waiting on input gets EOF instead of
        # hanging; timeout kept under the UserPromptSubmit hook budget.
        t = cmd_timeout()
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=t,
            env=env, stdin=subprocess.DEVNULL,
            cwd=cwd if (cwd and os.path.isdir(cwd)) else None,
        )
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        return (out.strip() or "(no output)", r.returncode)
    except subprocess.TimeoutExpired:
        return (f"timed out ({cmd_timeout()}s). If it's interactive or long-running, "
                f"open it in a terminal instead: sethu --launch \"{cmd}\"", None)
    except Exception as e:
        return (f"error: {e}", None)


def _run_quiet(argv):
    subprocess.run(argv, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _osa_str(s):
    """Escape a string for embedding in an AppleScript double-quoted literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def launch_in_terminal(cmd):
    """Open `cmd` in a *usable* shell next to the current one. Prefers a split
    pane in whatever you're using (tmux, then iTerm2), then a Terminal.app
    window. The command runs inside a real interactive shell, so the pane stays
    open and usable after the command exits. Returns a status string, or None if
    nothing could be opened (e.g. a plain SSH session with no GUI / multiplexer)."""
    shell = os.environ.get("SHELL", "/bin/bash")
    term = os.environ.get("TERM_PROGRAM", "")

    # 1) Inside tmux → split the current window. `exec $SHELL` after the command
    #    keeps the pane alive as a normal shell instead of closing on exit.
    if os.environ.get("TMUX"):
        try:
            _run_quiet(["tmux", "split-window", "-h", f"{cmd}; exec {shell}"])
            return "↗ opened in a new tmux pane"
        except Exception:
            pass

    # 2) iTerm2 → split the current session into a pane and type the command into
    #    its shell (so it's a real, reusable shell, not a one-shot).
    if term == "iTerm.app" and sys.platform == "darwin":
        script = ('tell application "iTerm2"\n'
                  '  tell current session of current window\n'
                  '    set s to (split vertically with default profile)\n'
                  '  end tell\n'
                  f'  tell s to write text "{_osa_str(cmd)}"\n'
                  'end tell')
        try:
            _run_quiet(["osascript", "-e", script])
            return "↗ opened in a new iTerm pane"
        except Exception:
            pass

    # 3) macOS fallback → a Terminal.app window. `do script` runs the command in a
    #    fresh interactive shell, so the window stays usable afterwards.
    if sys.platform == "darwin":
        script = ('tell application "Terminal"\n'
                  '  activate\n'
                  f'  do script "{_osa_str(cmd)}"\n'
                  'end tell')
        try:
            _run_quiet(["osascript", "-e", script])
            return "↗ opened in a new Terminal window"
        except Exception:
            pass
        # Last resort if Automation permission is denied: a .command file that
        # drops into a login shell after the command, so it isn't a one-shot.
        try:
            fd, path = tempfile.mkstemp(prefix="sethu-launch-", suffix=".command")
            with os.fdopen(fd, "w") as f:
                f.write(f"#!/bin/bash\n{cmd}\nexec {shell} -l\n")
            os.chmod(path, 0o755)
            _run_quiet(["open", path])
            return "↗ opened in a new Terminal window"
        except Exception:
            pass
    return None


# ── persistent shell (shell mode) ─────────────────────────────────────────────
# Bump when the daemon wire protocol changes, so a new client never talks to an
# old daemon left running from a previous version (it just idles out).
_PROTO = 2


def _sock_path(sid):
    # Hash the session id so the socket path stays short — AF_UNIX paths are
    # capped (~104 bytes on macOS), and temp dirs + a UUID session id overflow.
    h = hashlib.md5((sid or "default").encode()).hexdigest()[:12]
    name = f"sethu-{h}-p{_PROTO}.sock"
    path = os.path.join(tempfile.gettempdir(), name)
    if len(path) > 100:  # leave margin under the limit
        path = os.path.join("/tmp", name)
    return path


def kill_daemons():
    """Gracefully shut down all sethu shell daemons and remove their sockets.
    Each session respawns a fresh daemon on its next command. Returns the count."""
    n = 0
    for sock in glob.glob(os.path.join(tempfile.gettempdir(), "sethu-shell-*.sock")):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(sock)
            s.sendall(b"__SETHU_SHUTDOWN__\n")
            s.close()
            n += 1
        except Exception:
            pass
        try:
            os.unlink(sock)
        except OSError:
            pass
    return n


def _connect(sock):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(65)
    s.connect(sock)
    return s


def _spawn_daemon(sock, cwd_hint, use_rc=False):
    shelld = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shelld.py")
    shell = os.environ.get("SHELL", "/bin/bash")
    subprocess.Popen(
        [sys.executable, shelld, sock, cwd_hint or os.path.expanduser("~"),
         "1" if use_rc else "0", shell],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )


def shell_run(sid, cmd, cwd_hint=None, use_rc=False):
    sock = _sock_path(sid)
    s = None
    try:
        try:
            s = _connect(sock)  # an existing, live daemon
        except OSError:
            # socket missing, or stale (daemon gone → "connection refused").
            # Remove it and spawn a fresh daemon, then connect once it's up.
            try:
                os.unlink(sock)
            except OSError:
                pass
            _spawn_daemon(sock, cwd_hint, use_rc)
            for _ in range(80):
                try:
                    s = _connect(sock)
                    break
                except OSError:
                    time.sleep(0.05)
            if s is None:
                return ("sethu shell error: could not start the shell daemon", None)
        s.sendall((cmd + "\n").encode("utf-8"))
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        # daemon replies "<exit_code>\n<output>", or "TIMEOUT\n<partial output>"
        # when the command outran CMD_TIMEOUT (the daemon interrupts it so the
        # shell recovers).
        text = data.decode("utf-8", "replace")
        first, _, rest = text.partition("\n")
        if first.strip() == "TIMEOUT":
            partial = (rest.strip() + "\n") if rest.strip() else ""
            return (f"{partial}timed out ({cmd_timeout()}s). If it's interactive or "
                    f"waiting for input, open it in a terminal instead: "
                    f"sethu --launch \"{cmd}\"", None)
        if first.strip().lstrip("-").isdigit():
            return (rest.strip() or "(no output)", int(first))
        # No exit-code line (e.g. an older daemon) — show the whole reply rather
        # than swallowing it.
        return (text.strip() or "(no output)", None)
    except Exception as e:
        return (f"sethu shell error: {e}", None)
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


# ── the core: process one submitted prompt ────────────────────────────────────
HELP = ("sethu: type `> <command>` to run an allowlisted command (free), or "
        "`>> <command>` to also send its output to Claude.\n"
        "Manage it: `sethu --allow \"<cmd>\"`, `sethu --mode cwd|shell|stateless`, "
        "`sethu --runner`.")


def process(prompt, data):
    """Return one of: {'passthrough':True} | {'block':text} | {'context':text}."""
    cfg = load_config()
    prefix = cfg["prefix"]
    # Tolerate leading whitespace so " > date" works like "> date" — a stray
    # space before the prefix used to fall through to the model unintercepted.
    stripped = prompt.lstrip()
    if not prefix or not stripped.startswith(prefix):
        return {"passthrough": True}

    # Opportunistically clear sethu's own stale temp files (saved output, launch
    # scripts) so storage doesn't bloat. Cheap, best-effort, only on our prompts.
    try:
        _sweep_temp(time.time())
    except Exception:
        pass

    pipe = stripped.startswith(prefix * 2)
    cmd = stripped[len(prefix) * (2 if pipe else 1):].strip()
    if not cmd:
        return {"block": HELP}

    if _matches(cmd, cfg["launch"]):
        status = launch_in_terminal(cmd)
        return {"block": status or f"Couldn't open a terminal — run `{cmd}` yourself."}

    mode = cfg.get("mode", "cwd")
    sid = data.get("session_id")
    base = get_cwd(sid, data.get("cwd"))

    # cd is exempt from the allowlist (it runs nothing); behavior depends on mode.
    if is_cd(cmd) and mode != "shell":
        if mode == "cwd":
            target = resolve_cd(cmd[2:], base)
            if os.path.isdir(target):
                set_cwd(sid, target)
                return {"block": f"→ {target}"}
            return {"block": f"cd: not a directory: {target}"}
        return {"block": "stateless mode — cd doesn't persist. Use an inline path "
                         "(`> ls ..`), or switch: `sethu --mode cwd` (or `shell`)."}

    # readonly wins if a legacy config somehow has both on (safe default).
    trust_on = cfg.get("trust") and not cfg.get("readonly")
    allowed = trust_on or _matches(cmd, cfg["allow"]) or (
        cfg.get("readonly") and is_readonly_safe(cmd)
    )
    if not is_cd(cmd) and not allowed:
        ro = "" if cfg.get("readonly") else \
            "  • Auto-allow read-only cmds: sethu --readonly on\n"
        return {"block":
                f"`{cmd}` isn't allowed (nothing runs unless you allow it).\n"
                f"  • Allow it:        sethu --allow \"{cmd}\"\n"
                f"{ro}"
                f"  • Open a terminal: sethu --launch \"{cmd}\"\n"
                f"  • See config:      sethu --runner"}

    # Interactive programs would hang the captured runner — send them to a real
    # terminal instead (in any mode).
    if is_interactive(cmd):
        first = os.path.basename(cmd.split()[0])
        return {"block":
                f"`{first}` is interactive — the runner has no terminal, so it would "
                f"hang. Open it in a real terminal instead:\n"
                f"  sethu --launch \"{cmd}\"\n"
                f"then run `> {cmd}` (or just run it in your terminal)."}

    if mode == "shell":
        out, code = shell_run(sid, cmd, cwd_hint=data.get("cwd"), use_rc=cfg.get("rc"))
    elif mode == "stateless":
        out, code = run_capture(cmd, cwd=data.get("cwd"))
    else:  # cwd
        out, code = run_capture(cmd, cwd=base)

    # Completion header: which mode (+ trust warning) + done/failed + exit code.
    # Each part is colored distinctly (colorblind-safe) so the status, command,
    # and output read apart at a glance.
    on = _color_on(cfg)
    state = "ok" if code == 0 else ("fail" if code is not None else "warn")
    mark = {"ok": "✓", "fail": "✗", "warn": "⚠"}[state]
    status = f"exit {code}" if code is not None else "no exit code"
    tag = _c(f"[{mode}]", "tag", on)
    if trust_on:
        tag += " " + _c("⚠trust", "trust", on)
    mark_status = _c(f"{mark} {status}", state, on)
    icon = _c(ICON, "tag", on)
    header = f"{icon} {tag} {mark_status} {_c('·', 'dim', on)} {_c('$', 'dim', on)} {_c(cmd, 'cmd', on)}"

    # Cap long output so it doesn't flood the chat (`>`) or burn tokens (`>>`).
    # The full text is written to a per-session file; the note points at it.
    shown, note = _truncate(out, sid, int(cfg.get("maxLines", 40) or 0), on)

    if pipe:
        ctx = f"Output of `{cmd}` ({status}):\n{shown}"
        if note:
            ctx += f"\n[{note} — read that file if you need the rest.]"
        return {"context": ctx}
    body = f"{header}\n{shown}"
    if note:
        body += "\n" + _c(note, "dim", on)
    return {"block": body}


# ── management CLI ─────────────────────────────────────────────────────────────
def help_text():
    cfg = load_config()
    return f"""{ICON} sethu सेतु — run terminal commands from Claude's prompt box.

In the prompt (no `!` needed — costs zero tokens):
  > <cmd>        run an allowlisted command; output shown to you, model blocked
  >> <cmd>       run it AND send the output to Claude (this costs tokens)

When to use what:
  > cmd                 just inspect something yourself — free, stays out of context
  >> cmd                you want Claude to act on the output (costs tokens)
  --launch  <cmd>       the command is interactive (vim, top, ssh) — pop a real terminal
  --readonly on         tired of allowing ls / cat / git log one by one
  --mode shell          you need cd / export / venv to persist across commands
  --trust on            you want > to run anything, no allowlist (footgun)

Manage it (type `sethu …` in the prompt or a terminal):
  sethu                      show this help
  sethu --runner             show current config
  sethu --allow "<cmd>"      allow a command      sethu --unallow "<cmd>"
  sethu --launch "<cmd>"     open in a terminal   sethu --unlaunch "<cmd>"
  sethu --readonly on        auto-allow read-only commands (ls, cat, git log…)
  sethu --trust on           bypass the allowlist — run ANY command (footgun)
  sethu --mode {'|'.join(MODES)}
  sethu --rc on              shell mode: source your shell rc (aliases/functions/env)
  sethu --color off          turn off the colored result header (or NO_COLOR=1)
  sethu --maxlines 40        cap long output (full output saved to a file); 0 = unlimited
  sethu --restart            restart the persistent shell(s) (clear shell state)
  sethu --prefix ">"         change the trigger
  sethu --help               full flag reference

Modes: stateless (no state) · cwd (cd persists — default) · shell (cd/export/venv persist)
Safety: the allowlist is empty by default; a command runs only if you allow it.
Config: {config_path()}   (now: mode={cfg['mode']}, {len(cfg['allow'])} allowed)"""


SUBCOMMANDS = {"mode", "allow", "unallow", "launch", "unlaunch", "readonly",
               "trust", "rc", "color", "maxlines", "prefix", "restart", "runner",
               "show", "help"}


def normalize_argv(argv):
    """Accept subcommand style (`mode shell`) as an alias for flag style
    (`--mode shell`). For command-taking subcommands the remaining words are
    joined, so `allow git status` works without quoting. `help` → help screen."""
    if argv and not argv[0].startswith("-") and argv[0] in SUBCOMMANDS:
        sub, rest = argv[0], argv[1:]
        if sub == "help":
            return []
        if sub in ("allow", "unallow", "launch", "unlaunch") and rest:
            return ["--" + sub, " ".join(rest)]
        return ["--" + sub] + rest
    return argv


def main(argv=None):
    args_list = normalize_argv(sys.argv[1:] if argv is None else argv)
    if not args_list:
        print(help_text())
        return

    p = argparse.ArgumentParser(
        prog="sethu", description="sethu — run commands from Claude's prompt box",
        epilog=help_text(), formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--allow", metavar="CMD", help="allow a command for the runner")
    p.add_argument("--unallow", metavar="CMD", help="remove a command from the allowlist")
    p.add_argument("--launch", metavar="CMD", help="add a command to open in a terminal")
    p.add_argument("--unlaunch", metavar="CMD", help="remove a command from the launch list")
    p.add_argument("--mode", choices=MODES, help="set statefulness mode")
    p.add_argument("--prefix", help="set the trigger prefix (default '>')")
    p.add_argument("--readonly", choices=["on", "off"],
                   help="auto-allow a curated set of read-only commands")
    p.add_argument("--trust", choices=["on", "off"],
                   help="bypass the allowlist — run ANY command (footgun)")
    p.add_argument("--rc", choices=["on", "off"],
                   help="in shell mode, source your shell rc (aliases/functions/env)")
    p.add_argument("--color", choices=["on", "off"],
                   help="color the result header (default on; NO_COLOR also disables)")
    p.add_argument("--maxlines", metavar="N", type=int,
                   help="truncate output beyond N lines (full output saved to a file); 0 = unlimited")
    p.add_argument("--restart", action="store_true",
                   help="restart the persistent shell(s) (clears shell-mode state)")
    p.add_argument("--runner", "--show", dest="show", action="store_true", help="show config")
    a = p.parse_args(args_list)

    if a.restart:
        print(f"✔ restarted {kill_daemons()} shell daemon(s) — fresh state next command")
        return
    if a.rc:
        cfg = load_config()
        cfg["rc"] = (a.rc == "on")
        save_config(cfg)
        kill_daemons()  # restart so the new shell takes effect
        extra = (" — your shell's aliases/functions/env now load in shell mode"
                 if cfg["rc"] else "")
        print(f"✔ rc: {a.rc} (shell restarted){extra}")
        return

    cfg = load_config()
    changed = False
    if a.allow:
        if a.allow not in cfg["allow"]:
            cfg["allow"].append(a.allow)
        print(f"✔ added to allow: {a.allow!r}")
        changed = True
    if a.launch:
        val = a.launch
        if val not in cfg["launch"]:
            cfg["launch"].append(val)
        changed = True
        # "launch" is a verb — open it now, not just register it. From here on
        # `> <val>` opens a terminal too (that's what the launch list is for).
        status = launch_in_terminal(val)
        if status:
            print(f"✔ {status} — opened {val!r}. From now on `> {val}` opens a "
                  f"terminal too.")
        else:
            print(f"✔ added {val!r} to the launch list — `> {val}` will open it in a "
                  f"terminal. (Couldn't open one now — no tmux pane, and auto-open "
                  f"is macOS/tmux only; run `{val}` in your terminal.)")
    for field, key in (("unallow", "allow"), ("unlaunch", "launch")):
        val = getattr(a, field)
        if val:
            if val in cfg[key]:
                cfg[key].remove(val)
            print(f"✔ removed from {key}: {val!r}")
            changed = True
    if a.mode:
        cfg["mode"] = a.mode
        killed = kill_daemons()  # start the new mode from a clean slate
        note = f" (restarted {killed} shell daemon(s))" if killed else ""
        print(f"✔ mode: {a.mode}{note}")
        changed = True
    if a.prefix:
        cfg["prefix"] = a.prefix
        print(f"✔ prefix: {a.prefix!r}")
        changed = True
    if a.color:
        cfg["color"] = (a.color == "on")
        print(f"✔ color: {a.color}")
        changed = True
    if a.maxlines is not None:
        cfg["maxLines"] = max(0, a.maxlines)
        disp = "unlimited" if cfg["maxLines"] == 0 else f"{cfg['maxLines']} lines"
        print(f"✔ maxLines: {disp}")
        changed = True
    if a.readonly:
        cfg["readonly"] = (a.readonly == "on")
        note = ""
        if cfg["readonly"] and cfg.get("trust"):
            cfg["trust"] = False          # mutually exclusive with trust
            note = " (trust turned OFF)"
        print(f"✔ readonly: {a.readonly}{note}")
        changed = True
    if a.trust:
        cfg["trust"] = (a.trust == "on")
        if cfg["trust"]:
            ro = ""
            if cfg.get("readonly"):
                cfg["readonly"] = False   # mutually exclusive with readonly
                ro = " (readonly turned OFF.)"
            print("⚠ trust ON — the allowlist is bypassed; ANY `>` command will run, "
                  f"with no permission prompt.{ro} Turn it off with `sethu --trust off`.")
        else:
            print("✔ trust: off (allowlist enforced again)")
        changed = True
    if changed:
        save_config(cfg)
        return
    # default / --runner: show config
    print(f"sethu config ({config_path()}):")
    print(f"  prefix: {cfg['prefix']!r}   (> run+block free, >> run+send to Claude)")
    print(f"  mode:     {cfg['mode']}   (one of: {', '.join(MODES)})")
    both = cfg.get("readonly") and cfg.get("trust")
    print(f"  readonly: {'on' if cfg.get('readonly') else 'off'}   (auto-allow read-only cmds)")
    trust_disp = "off"
    if cfg.get("trust"):
        trust_disp = "set but OVERRIDDEN by readonly ⚠" if both else "ON ⚠ allowlist bypassed"
    print(f"  trust:    {trust_disp}")
    print(f"  rc:       {'on' if cfg.get('rc') else 'off'}   (shell mode sources your shell rc)")
    print(f"  color:    {'on' if cfg.get('color', True) else 'off'}   (colored result header)")
    ml = int(cfg.get("maxLines", 40) or 0)
    print(f"  maxLines: {'unlimited' if ml == 0 else ml}   (truncate long output; full saved to a file)")
    if both:
        print("  ⚠ both readonly and trust are set (legacy) — readonly wins. "
              "Run `sethu --readonly on` or `sethu --trust off` to clean up.")
    print(f"  allow:    {cfg['allow']}")
    print(f"  launch:   {cfg['launch']}")


if __name__ == "__main__":
    main()
