#!/usr/bin/env python3
"""Persistent-shell daemon for sethu's `shell` mode.

Holds one long-lived `bash` behind a PTY and serves commands over a Unix socket,
one command per connection. Because the same bash stays alive across commands,
state persists: `cd`, `export`, `source`, and venv activation all stick.

Usage (started automatically by _engine._spawn_daemon):
    _shelld.py <socket_path> <cwd> <use_rc:0|1> <shell>
where <use_rc> sources the user's shell rc (aliases/functions/env) and <shell>
is the shell to run when it does (else a clean `bash --norc`).

Protocol: client sends "<command>\\n"; daemon runs it, replies with the captured
output, closes the connection. On a command timeout the reply is
"TIMEOUT\\n<partial output>": the daemon Ctrl-C's the stuck command and VERIFIES the
shell recovered, escalating to SIGKILL of the foreground process group if the job
ignores Ctrl-C; if the shell can't be unstuck it exits so the next command respawns
a fresh daemon (never serving a command onto a wedged shell). The daemon exits after
IDLE_TIMEOUT seconds with no connections, and on the command "__SETHU_SHUTDOWN__".
"""
import os
import pty
import re
import select
import signal
import socket
import sys
import termios
import time

IDLE_TIMEOUT = 1800  # 30 minutes
# Max seconds to wait for a command's output — mirrors _engine.CMD_TIMEOUT (kept
# under Claude Code's UserPromptSubmit hook budget). Inherited SETHU_CMD_TIMEOUT
# overrides it (the engine passes it through when spawning the daemon).
try:
    CMD_TIMEOUT = int(os.environ.get("SETHU_CMD_TIMEOUT") or 20)
except ValueError:
    CMD_TIMEOUT = 20

# Byte ceiling on one command's captured output — mirrors _engine.MAX_CAPTURE_BYTES.
# A runaway (`yes`, `cat big.iso`) is stopped at the cap so it can't balloon the
# daemon's (or the client's) RAM.
MAX_OUTPUT = 8 * 1024 * 1024   # 8 MiB


def _perms_ok(mode):
    """True only if the socket's file mode grants no group/world access."""
    return not (mode & 0o077)


def _drain(master, seconds):
    end = time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select([master], [], [], 0.05)
        if not r:
            break
        try:
            if not os.read(master, 65536):
                break
        except OSError:
            break


def _probe(master):
    """Confirm bash is back at a prompt: ask it to echo a fresh token and see if
    the token comes back quickly. If bash is still blocked on a stuck foreground
    job, the printf bytes just queue in the PTY and never run, so this returns
    False. Also drains everything up to (and just past) the token, so the next
    command starts with a clean PTY (no bled-over output). Returns True if bash
    responded — i.e. it recovered."""
    token = "__SETHU_PROBE_%d__" % time.time_ns()
    try:
        os.write(master, ("printf '%%s\\n' %s\n" % token).encode("utf-8"))
    except OSError:
        return False
    end = time.time() + 0.5
    seen = ""
    while time.time() < end:
        r, _, _ = select.select([master], [], [], 0.05)
        if not r:
            continue
        try:
            chunk = os.read(master, 65536)
        except OSError:
            return False
        if not chunk:
            return False
        seen += chunk.decode("utf-8", "replace")
        if token in seen:
            _drain(master, 0.2)   # flush any trailing bytes so nothing bleeds
            return True
    return False


def _recover(master):
    """Try to unstick the shell after a timeout, and VERIFY it worked, escalating
    Ctrl-C → SIGKILL the foreground process group. Returns True if bash is back at
    a clean prompt, False if it's still wedged (caller then respawns the daemon).
    Never lets the next command run on a still-blocked shell (H3: that caused
    wedges, output bleed, and late execution of a 'timed-out' command)."""
    # 1) Ctrl-C the foreground job and check bash recovered.
    try:
        os.write(master, b"\x03")
    except OSError:
        return False
    _drain(master, 0.3)
    if _probe(master):
        return True
    # 2) Escalate: SIGKILL the terminal's foreground process group (the stuck job —
    #    NOT the daemon; the PTY's foreground group is in bash's own session). This
    #    kills a job that ignores/handles SIGINT (`trap '' INT`, a KeyboardInterrupt
    #    catcher). SIGKILL can't be trapped.
    try:
        pgrp = os.tcgetpgrp(master)
        if pgrp > 0 and pgrp != os.getpgrp():
            os.killpg(pgrp, signal.SIGKILL)
            _drain(master, 0.3)
            if _probe(master):
                return True
    except OSError:
        pass
    # 3) Still wedged (the stuck job WAS bash, or it won't die). Unrecoverable.
    return False


def _run(master, cmd):
    """Run one command in the persistent shell. Returns (response, recovered):
    recovered is False only when a timed-out command left the shell wedged, in
    which case the caller kills this daemon so the next command respawns a fresh
    one (losing shell state on a wedge is acceptable — the alternative is a stuck
    shell that bleeds output and runs 'timed-out' commands late)."""
    marker = "__SETHU_END_%d__" % time.time_ns()
    os.write(master, (cmd + "\n").encode("utf-8"))
    # Emit the marker followed by the exit code so the client can report status.
    os.write(master, ("printf '\\n%s %%s\\n' \"$?\"\n" % marker).encode("utf-8"))
    buf = ""
    end = time.time() + CMD_TIMEOUT
    done = capped = False
    while time.time() < end:
        # Short poll interval: select() returns immediately when output is ready,
        # so this only bounds the worst-case slack when a command finishes right
        # after an empty poll. 0.05s keeps that floor low at negligible CPU cost.
        r, _, _ = select.select([master], [], [], 0.05)
        if r:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk.decode("utf-8", "replace")
            if marker in buf:
                done = True
                break
            if len(buf) > MAX_OUTPUT:
                capped = True   # runaway output — stop it, don't balloon RAM (ST7)
                break
    if capped:
        # Interrupt the runaway (like a timeout) so it stops flooding the PTY, then
        # return the capped partial. recovered=False → the daemon respawns.
        partial = buf.split(marker, 1)[0][:MAX_OUTPUT].strip()
        recovered = _recover(master)
        return "CAPPED\n" + partial, recovered
    if not done:
        # The command outran the timeout and is still executing (waiting on input,
        # long-running, or ignoring Ctrl-C). Interrupt AND verify recovery before
        # this daemon serves the next command — otherwise the next command's bytes
        # queue behind the stuck job and run whenever bash unblocks (H3).
        partial = buf.split(marker, 1)[0].strip()
        recovered = _recover(master)
        return "TIMEOUT\n" + partial, recovered
    out = buf.split(marker, 1)[0].strip() or "(no output)"
    after = buf.split(marker, 1)[1] if marker in buf else ""
    m = re.search(r"-?\d+", after)
    code = m.group() if m else ""
    return f"{code}\n{out}", True


def main():
    sock_path = sys.argv[1]
    start_cwd = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~")
    use_rc = len(sys.argv) > 3 and sys.argv[3] == "1"
    shell = sys.argv[4] if len(sys.argv) > 4 else "/bin/bash"

    pid, master = pty.fork()
    if pid == 0:
        os.chdir(start_cwd if os.path.isdir(start_cwd) else os.path.expanduser("~"))
        if use_rc:
            os.execvp(shell, [os.path.basename(shell)])   # your shell; rc sourced below
        else:
            os.execvp("bash", ["bash", "--norc", "--noprofile"])
        os._exit(1)

    # Disable echo so the typed command isn't mirrored back into the output.
    try:
        attrs = termios.tcgetattr(master)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(master, termios.TCSANOW, attrs)
    except Exception:
        pass
    # Optionally source your shell rc so aliases/functions/env are available.
    if use_rc:
        base = os.path.basename(shell)
        if "zsh" in base:
            os.write(master, b"source ~/.zshrc 2>/dev/null; "
                             b"precmd() {}; PROMPT='' RPROMPT=''\n")
        elif "bash" in base:
            os.write(master, b"shopt -s expand_aliases 2>/dev/null; "
                             b"source ~/.bashrc 2>/dev/null\n")
        else:
            os.write(master, b"source ~/.profile 2>/dev/null\n")

    # GIT_PAGER/PAGER=cat so git (log/branch/diff) and other paged commands don't
    # launch `less` under the PTY and hang. NO_COLOR keeps output clean. Set
    # AFTER sourcing rc so the rc can't re-enable a prompt/pager.
    os.write(master, b"export PS1='' PS2='' GIT_PAGER=cat PAGER=cat NO_COLOR=1 ; "
                     b"stty -echo 2>/dev/null\n")
    _drain(master, 0.8 if use_rc else 0.4)

    try:
        os.unlink(sock_path)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o077)  # socket file created 0600 — owner-only
    try:
        srv.bind(sock_path)
    finally:
        os.umask(old_umask)
    try:
        os.chmod(sock_path, 0o600)
    except OSError:
        pass
    # Defence in depth: AF_UNIX sockets are gated by filesystem permissions, so
    # refuse to serve if the socket ended up group/world-accessible (e.g. a tmp
    # filesystem that honours neither umask nor chmod). Better to fail closed —
    # the client surfaces "could not start the shell daemon" — than to expose a
    # live shell to other local users.
    try:
        mode = os.stat(sock_path).st_mode
    except OSError:
        mode = 0o077  # can't verify → treat as unsafe
    if not _perms_ok(mode):
        try:
            os.unlink(sock_path)
        except OSError:
            pass
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        os._exit(1)
    srv.listen(8)
    srv.settimeout(IDLE_TIMEOUT)

    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                break  # idle — shut down
            try:
                conn.settimeout(5)
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                cmd = data.decode("utf-8", "replace").rstrip("\n")
                if cmd == "__SETHU_SHUTDOWN__":
                    conn.close()
                    break
                resp, recovered = _run(master, cmd)
                conn.sendall(resp.encode("utf-8", "replace"))
                if not recovered:
                    # A timed-out command left the shell wedged and couldn't be
                    # killed. Don't serve another command on a stuck bash (it would
                    # queue behind the dead job) — exit so the next request spawns a
                    # fresh daemon (the client's connect-refused path handles that).
                    conn.close()
                    break
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
    finally:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            os.unlink(sock_path)
        except Exception:
            pass


if __name__ == "__main__":
    main()
