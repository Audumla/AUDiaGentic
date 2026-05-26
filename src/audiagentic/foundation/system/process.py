"""Generic process and port utilities.

Shared by the embedded rig, LSP component, and any other code that needs to
locate free ports, wrap platform binaries, check PID liveness, coordinate
exclusive process startup, or discover/terminate processes.
"""
from __future__ import annotations

import os
import random
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def choose_free_port(host: str) -> int:
    """Return a free TCP port on *host* chosen from the ephemeral range."""
    candidates = list(range(30000, 61000))
    random.shuffle(candidates)
    for port in candidates[:64]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise SystemExit(f"Unable to find free port on {host}")


def candidate_ports(host: str, requested_port: int) -> list[int]:
    """Return ports to try when launching a server.

    If *requested_port* is non-zero, returns that single port.
    Otherwise returns a primary free port plus seven extras so the caller
    can retry on collision.
    """
    if requested_port != 0:
        return [requested_port]
    primary = choose_free_port(host)
    extras: list[int] = []
    seen = {primary}
    while len(extras) < 7:
        port = choose_free_port(host)
        if port in seen:
            continue
        seen.add(port)
        extras.append(port)
    return [primary, *extras]


def executable_command(binary: Path) -> list[str]:
    """Return the command prefix needed to run *binary* on the current platform.

    On Windows, native executables are called directly.  On POSIX, PE binaries
    (MZ magic bytes) are wrapped with ``sh`` so Wine-style loaders work.
    """
    if sys.platform == "win32":
        return [str(binary)]
    try:
        if binary.read_bytes()[:2] == b"MZ":
            return ["sh", str(binary)]
    except OSError:
        pass
    return [str(binary)]


def pid_alive(pid: int) -> bool:
    """Return True if *pid* names a live process, False if dead or unknown."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class StartupLock:
    """Exclusive startup lock backed by an atomic file.

    Uses ``O_CREAT|O_EXCL`` which is atomic on NTFS and POSIX.  Stale locks
    (holder PID dead) are automatically cleared and retried.

    Parameters
    ----------
    lock_path:
        Full path to the lock file.  The parent directory is created if absent.
    timeout:
        Seconds to wait before raising ``SystemExit``.
    """

    def __init__(self, lock_path: Path, timeout: float = 30.0) -> None:
        self._path = lock_path
        self._timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> StartupLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            try:
                self._fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    holder = int(self._path.read_text(encoding="utf-8"))
                    if pid_alive(holder):
                        time.sleep(0.1)
                        continue
                    self._path.unlink(missing_ok=True)
                except (ValueError, OSError):
                    self._path.unlink(missing_ok=True)
        raise SystemExit(
            f"Timed out waiting for startup lock: {self._path}"
        )

    def __exit__(self, *_: object) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self._path.unlink(missing_ok=True)


def find_pid_on_port(port: int) -> int | None:
    """Return the PID of the process listening on *port*, or None."""
    if os.name == "nt":
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True, text=True, check=False,
        )
        needle = f":{port}"
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if "LISTENING" not in stripped or needle not in stripped:
                continue
            parts = stripped.split()
            if len(parts) < 5:
                continue
            if not parts[1].endswith(needle) or parts[3] != "LISTENING":
                continue
            try:
                return int(parts[4])
            except ValueError:
                continue
        return None

    for command in (
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        ["ss", "-ltnp"],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            continue
        if command[0] == "lsof":
            for line in result.stdout.splitlines():
                try:
                    return int(line.strip())
                except ValueError:
                    continue
            continue
        needle = f":{port} "
        for line in result.stdout.splitlines():
            if needle not in line:
                continue
            idx = line.find("pid=")
            if idx == -1:
                continue
            try:
                return int(line[idx + 4:].split(",", 1)[0])
            except ValueError:
                continue
    return None


def kill_pid(pid: int) -> None:
    """Send SIGTERM (Windows: taskkill) to *pid*. Ignores already-dead processes."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def kill_process_tree(pid: int) -> None:
    """Force-kill *pid* and all its children (SIGKILL / taskkill /T /F)."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
