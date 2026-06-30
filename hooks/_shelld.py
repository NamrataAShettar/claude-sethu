#!/usr/bin/env python3
"""Persistent-shell daemon for sethu's `shell` mode.

Holds one long-lived `bash` behind a PTY and serves commands over a Unix socket,
one command per connection. Because the same bash stays alive across commands,
state persists: `cd`, `export`, `source`, and venv activation all stick.

Usage (started automatically by the engine):  _shelld.py <socket_path> <cwd>

Protocol: client sends "<command>\\n"; daemon runs it, replies with the captured
output, closes the connection. The daemon exits after IDLE_TIMEOUT seconds with
no connections, and on the special command "__SETHU_SHUTDOWN__".
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
CMD_TIMEOUT = 60      # max seconds to wait for a command's output


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


def _run(master, cmd):
    marker = "__SETHU_END_%d__" % time.time_ns()
    os.write(master, (cmd + "\n").encode("utf-8"))
    # Emit the marker followed by the exit code so the client can report status.
    os.write(master, ("printf '\\n%s %%s\\n' \"$?\"\n" % marker).encode("utf-8"))
    buf = ""
    end = time.time() + CMD_TIMEOUT
    while time.time() < end:
        r, _, _ = select.select([master], [], [], 0.2)
        if r:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk.decode("utf-8", "replace")
            if marker in buf:
                break
    out = buf.split(marker, 1)[0].strip() or "(no output)"
    after = buf.split(marker, 1)[1] if marker in buf else ""
    m = re.search(r"-?\d+", after)
    code = m.group() if m else ""
    return f"{code}\n{out}"


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
                conn.sendall(_run(master, cmd).encode("utf-8", "replace"))
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
