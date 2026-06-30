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
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time

DEFAULTS = {"prefix": ">", "mode": "cwd", "allow": [], "launch": [], "readonly": False}
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
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return ("timed out (20s). If it's interactive or long-running, open it in "
                f"a terminal instead: sethu --launch \"{cmd}\"")
    except Exception as e:
        return f"error: {e}"


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
def _sock_path(sid):
    safe = "".join(c for c in (sid or "default") if c.isalnum() or c in "-_")
    return os.path.join(tempfile.gettempdir(), f"sethu-shell-{safe}.sock")


def shell_run(sid, cmd, cwd_hint=None):
    sock = _sock_path(sid)
    if not os.path.exists(sock):
        shelld = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shelld.py")
        subprocess.Popen(
            [sys.executable, shelld, sock, cwd_hint or os.path.expanduser("~")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
        for _ in range(60):
            if os.path.exists(sock):
                break
            time.sleep(0.05)
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(65)
        s.connect(sock)
        s.sendall((cmd + "\n").encode("utf-8"))
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        s.close()
        return data.decode("utf-8", "replace").strip() or "(no output)"
    except Exception as e:
        return f"sethu shell error: {e}"


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

    allowed = _matches(cmd, cfg["allow"]) or (
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
        out = shell_run(sid, cmd, cwd_hint=data.get("cwd"))
    elif mode == "stateless":
        out = run_capture(cmd, cwd=data.get("cwd"))
    else:  # cwd
        out = run_capture(cmd, cwd=base)

    if pipe:
        return {"context": f"Output of `{cmd}`:\n{out}"}
    return {"block": out}


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
  sethu --mode {'|'.join(MODES)}
  sethu --prefix ">"         change the trigger
  sethu --help               full flag reference

Modes: stateless (no state) · cwd (cd persists — default) · shell (cd/export/venv persist)
Safety: the allowlist is empty by default; a command runs only if you allow it.
Config: {config_path()}   (now: mode={cfg['mode']}, {len(cfg['allow'])} allowed)"""


def main(argv=None):
    args_list = sys.argv[1:] if argv is None else argv
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
    p.add_argument("--runner", "--show", dest="show", action="store_true", help="show config")
    a = p.parse_args(argv)

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
        print(f"✔ mode: {a.mode}")
        changed = True
    if a.prefix:
        cfg["prefix"] = a.prefix
        print(f"✔ prefix: {a.prefix!r}")
        changed = True
    if a.readonly:
        cfg["readonly"] = (a.readonly == "on")
        print(f"✔ readonly: {a.readonly}")
        changed = True
    if changed:
        save_config(cfg)
        return
    # default / --runner: show config
    print(f"sethu config ({config_path()}):")
    print(f"  prefix: {cfg['prefix']!r}   (> run+block free, >> run+send to Claude)")
    print(f"  mode:     {cfg['mode']}   (one of: {', '.join(MODES)})")
    print(f"  readonly: {'on' if cfg.get('readonly') else 'off'}   (auto-allow read-only cmds)")
    print(f"  allow:    {cfg['allow']}")
    print(f"  launch:   {cfg['launch']}")


if __name__ == "__main__":
    main()
