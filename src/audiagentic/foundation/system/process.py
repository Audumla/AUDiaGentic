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
import threading
import time
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error

_thread_lock_guard = threading.Lock()
_thread_locks: dict[str, tuple[threading.Lock, int]] = {}


def _claim_thread_lock(path: Path) -> threading.Lock:
    """Return a ref-counted in-process lock for one filesystem lock path."""
    key = os.path.normcase(os.path.abspath(path))
    with _thread_lock_guard:
        lock, users = _thread_locks.get(key, (threading.Lock(), 0))
        _thread_locks[key] = (lock, users + 1)
    return lock


def _release_thread_lock(path: Path, lock: threading.Lock) -> None:
    key = os.path.normcase(os.path.abspath(path))
    lock.release()
    with _thread_lock_guard:
        current, users = _thread_locks[key]
        if users == 1:
            del _thread_locks[key]
        else:
            _thread_locks[key] = (current, users - 1)


def _process_error(prefix: str, code_number: int, message: str, **details: object) -> AudiaGenticError:
    return make_error(
        prefix=prefix,
        component="PROC",
        number=code_number,
        kind="system-process",
        message=message,
        details=details,
    )


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
    raise _process_error("RES", 1, f"Unable to find free port on {host}", host=host)


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
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    if os.name != "nt":
        try:
            state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
        except (OSError, IndexError):
            return True
        if state in {"Z", "X"}:
            return False
    return True


def _windows_pid_alive(pid: int) -> bool:
    """Query process exit state instead of treating a retained handle as live."""
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # ERROR_ACCESS_DENIED means the process exists but is not openable
        # (other user / elevated). Treating it as dead lets stale-lock
        # breakers steal locks from live holders (RV681) — stay conservative.
        error_access_denied = 5
        return ctypes.get_last_error() == error_access_denied
    exit_code = wintypes.DWORD()
    try:
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and (
            exit_code.value == still_active
        )
    finally:
        kernel32.CloseHandle(handle)


class StartupLock:
    """Exclusive startup lock backed by an atomic file.

    Uses ``O_CREAT|O_EXCL`` which is atomic on NTFS and POSIX.  Stale locks
    (holder PID dead) are automatically cleared and retried.

    Parameters
    ----------
    lock_path:
        Full path to the lock file.  The parent directory is created if absent.
    timeout:
        Seconds to wait before raising ``AudiaGenticError``.
    """

    def __init__(self, lock_path: Path, timeout: float = 30.0) -> None:
        self._path = lock_path
        self._timeout = timeout
        self._fd: int | None = None
        self._thread_lock: threading.Lock | None = None

    def __enter__(self) -> StartupLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout
        self._thread_lock = _claim_thread_lock(self._path)
        if not self._thread_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            _release_thread_lock(self._path, self._thread_lock)
            self._thread_lock = None
            raise self._timeout_error()
        try:
            while time.monotonic() < deadline:
                try:
                    self._fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(self._fd, str(os.getpid()).encode())
                    return self
                except (FileExistsError, PermissionError):
                    # On Windows, an existing lock file can surface as
                    # PermissionError while another process owns an open
                    # handle to it. Treat that case as contention; do not
                    # unlink a file we have not established to be stale.
                    if isinstance(sys.exc_info()[1], PermissionError):
                        time.sleep(0.01)
                        continue
                    try:
                        holder = int(self._path.read_text(encoding="utf-8"))
                        if pid_alive(holder):
                            time.sleep(0.1)
                            continue
                        self._unlink()
                    except (ValueError, OSError):
                        self._unlink()
        except BaseException:
            _release_thread_lock(self._path, self._thread_lock)
            self._thread_lock = None
            raise
        _release_thread_lock(self._path, self._thread_lock)
        self._thread_lock = None
        raise self._timeout_error()

    def _timeout_error(self) -> AudiaGenticError:
        return _process_error(
            "TO",
            2,
            f"Timed out waiting for startup lock: {self._path}",
            path=str(self._path),
            timeout=self._timeout,
        )

    def _unlink(self) -> None:
        """Remove the lock, tolerating short-lived Windows reader handles."""
        deadline = time.monotonic() + min(1.0, self._timeout)
        while True:
            try:
                self._path.unlink(missing_ok=True)
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)

    def __exit__(self, *_: object) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self._unlink()
        if self._thread_lock is not None:
            _release_thread_lock(self._path, self._thread_lock)
            self._thread_lock = None


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


def _descendant_pids_posix(root: int) -> list[int]:
    """Return all transitive child PIDs of *root* (deepest first), via ``ps``."""
    result = subprocess.run(
        ["ps", "-A", "-o", "pid=,ppid="],
        capture_output=True, text=True, check=False,
    )
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)

    ordered: list[int] = []
    stack = [root]
    while stack:
        current = stack.pop()
        for child in children.get(current, ()):
            ordered.append(child)
            stack.append(child)
    ordered.reverse()  # deepest descendants first
    return ordered


def kill_process_tree(pid: int) -> None:
    """Force-kill *pid* and all its descendants (taskkill /T /F on Windows).

    On POSIX the kernel offers no built-in tree kill, so descendants are
    enumerated via ``ps`` and SIGKILLed deepest-first before the root — this is
    what actually reaps orphaned MCP/LSP grandchildren, not just the host.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        return
    for target in (*_descendant_pids_posix(pid), pid):
        try:
            os.kill(target, signal.SIGKILL)
        except OSError:
            pass
