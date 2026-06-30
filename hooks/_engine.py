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
            "readonly": False, "trust": False}
MODES = ("stateless", "cwd", "shell")


# ── config ───────────────────────────────────────────────────────────────────
def config_path():
    return os.environ.get("SETHU_CONFIG") or os.path.expanduser("~/.claude/sethu.json")


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
def _matches(cmd, entries):
    cmd = cmd.strip()
    return any(cmd == e or cmd.startswith(e + " ") for e in entries)


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


def is_interactive(cmd):
    toks = cmd.split()
    return bool(toks) and os.path.basename(toks[0]) in INTERACTIVE


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
READONLY_GIT = {
    "status", "log", "diff", "show", "branch", "remote", "tag", "describe",
    "blame", "ls-files", "rev-parse", "shortlog", "stash", "config",
}
# Shell metacharacters that enable writes / chaining / substitution / background.
_DANGER = re.compile(r"[;&`<>]|\$\(")


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
        # hanging; timeout well under the 30s UserPromptSubmit hook limit.
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=20, env=env,
            stdin=subprocess.DEVNULL,
            cwd=cwd if (cwd and os.path.isdir(cwd)) else None,
        )
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        return (out.strip() or "(no output)", r.returncode)
    except subprocess.TimeoutExpired:
        return ("timed out (20s). If it's interactive or long-running, open it in "
                f"a terminal instead: sethu --launch \"{cmd}\"", None)
    except Exception as e:
        return (f"error: {e}", None)


def launch_in_terminal(cmd):
    if os.environ.get("TMUX"):
        try:
            subprocess.run(["tmux", "split-window", "-h", cmd], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "↗ opened in a new tmux pane"
        except Exception:
            pass
    if sys.platform == "darwin":
        try:
            fd, path = tempfile.mkstemp(suffix=".command")
            with os.fdopen(fd, "w") as f:
                f.write("#!/bin/bash\n" + cmd + "\n")
            os.chmod(path, 0o755)
            subprocess.run(["open", path], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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


def _spawn_daemon(sock, cwd_hint):
    shelld = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shelld.py")
    subprocess.Popen(
        [sys.executable, shelld, sock, cwd_hint or os.path.expanduser("~")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )


def shell_run(sid, cmd, cwd_hint=None):
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
            _spawn_daemon(sock, cwd_hint)
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
        # daemon replies "<exit_code>\n<output>"
        text = data.decode("utf-8", "replace")
        first, _, rest = text.partition("\n")
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
    if not prefix or not prompt.startswith(prefix):
        return {"passthrough": True}

    pipe = prompt.startswith(prefix * 2)
    cmd = prompt[len(prefix) * (2 if pipe else 1):].strip()
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

    allowed = cfg.get("trust") or _matches(cmd, cfg["allow"]) or (
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
        out, code = shell_run(sid, cmd, cwd_hint=data.get("cwd"))
    elif mode == "stateless":
        out, code = run_capture(cmd, cwd=data.get("cwd"))
    else:  # cwd
        out, code = run_capture(cmd, cwd=base)

    # Completion header: which mode (+ trust warning) + done/failed + exit code.
    mark = "✓" if code == 0 else ("✗" if code is not None else "⚠")
    status = f"exit {code}" if code is not None else "no exit code"
    tag = mode + (" ⚠trust" if cfg.get("trust") else "")
    header = f"[{tag}] {mark} {status} · $ {cmd}"
    body = f"{header}\n{out}"

    if pipe:
        return {"context": f"Output of `{cmd}` ({status}):\n{out}"}
    return {"block": body}


# ── management CLI ─────────────────────────────────────────────────────────────
def help_text():
    cfg = load_config()
    return f"""sethu सेतु — run terminal commands from Claude's prompt box.

In the prompt (no `!` needed — costs zero tokens):
  > <cmd>        run an allowlisted command; output shown to you, model blocked
  >> <cmd>       run it AND send the output to Claude (this costs tokens)

Manage it (type `sethu …` in the prompt or a terminal):
  sethu                      show this help
  sethu --runner             show current config
  sethu --allow "<cmd>"      allow a command      sethu --unallow "<cmd>"
  sethu --launch "<cmd>"     open in a terminal   sethu --unlaunch "<cmd>"
  sethu --readonly on        auto-allow read-only commands (ls, cat, git log…)
  sethu --trust on           bypass the allowlist — run ANY command (footgun)
  sethu --mode {'|'.join(MODES)}
  sethu --restart            restart the persistent shell(s) (clear shell state)
  sethu --prefix ">"         change the trigger
  sethu --help               full flag reference

Modes: stateless (no state) · cwd (cd persists — default) · shell (cd/export/venv persist)
Safety: the allowlist is empty by default; a command runs only if you allow it.
Config: {config_path()}   (now: mode={cfg['mode']}, {len(cfg['allow'])} allowed)"""


SUBCOMMANDS = {"mode", "allow", "unallow", "launch", "unlaunch", "readonly",
               "trust", "prefix", "restart", "runner", "show", "help"}


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
    p.add_argument("--restart", action="store_true",
                   help="restart the persistent shell(s) (clears shell-mode state)")
    p.add_argument("--runner", "--show", dest="show", action="store_true", help="show config")
    a = p.parse_args(args_list)

    if a.restart:
        print(f"✔ restarted {kill_daemons()} shell daemon(s) — fresh state next command")
        return

    cfg = load_config()
    changed = False
    for field, key in (("allow", "allow"), ("launch", "launch")):
        val = getattr(a, field)
        if val:
            if val not in cfg[key]:
                cfg[key].append(val)
            print(f"✔ added to {key}: {val!r}")
            changed = True
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
    print(f"  readonly: {'on' if cfg.get('readonly') else 'off'}   (auto-allow read-only cmds)")
    print(f"  trust:    {'ON ⚠ allowlist bypassed' if cfg.get('trust') else 'off'}")
    print(f"  allow:    {cfg['allow']}")
    print(f"  launch:   {cfg['launch']}")


if __name__ == "__main__":
    main()
