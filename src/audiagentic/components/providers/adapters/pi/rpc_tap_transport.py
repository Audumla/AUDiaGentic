"""AS40: cross-platform duplex IPC transport for the AG-bound Pi RPC tap.

Unix domain socket on POSIX, named pipe on Windows -- a duplex IPC endpoint
the tee shim connects out to and AG listens on, never a file being polled or
tailed. Built directly on `multiprocessing.connection` (stdlib), which already
provides the same Listener/Client API over AF_UNIX (POSIX) and AF_PIPE
(Windows) with per-connection HMAC authkey handshake for free.
"""
from __future__ import annotations

import hashlib
import os
import time
from multiprocessing import connection
from pathlib import Path

_CONNECT_POLL_INTERVAL = 0.05


def tap_family() -> str:
    return "AF_PIPE" if os.name == "nt" else "AF_UNIX"


def tap_address(runtime_root: Path) -> str:
    """Deterministic per-request tap address under runtime_root.

    POSIX: a socket file path under runtime_root (single-owner runtime
    artifact, removed with the request runtime). Windows: a
    ``\\\\.\\pipe\\`` name derived from a hash of runtime_root -- pipe names
    live in a global namespace and cannot contain arbitrary path separators,
    so the path itself cannot be used directly.
    """
    if os.name == "nt":
        digest = hashlib.sha256(str(runtime_root.resolve()).encode("utf-8")).hexdigest()[:32]
        return rf"\\.\pipe\audiagentic-pi-tap-{digest}"
    return str(runtime_root.resolve() / "pi" / "acp" / "tap.sock")


def open_tap_listener(address: str, *, authkey: bytes) -> connection.Listener:
    """AG side: start listening for the shim's outbound tap connection.

    Caller owns closing the returned Listener (and removing a POSIX socket
    file, which the Listener does on `close()`).
    """
    if os.name != "nt":
        socket_path = Path(address)
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        if socket_path.exists():
            socket_path.unlink()
    return connection.Listener(address, family=tap_family(), authkey=authkey)


def connect_tap(address: str, *, authkey: bytes, timeout: float = 5.0) -> connection.Connection:
    """Shim side: connect out to AG's tap listener.

    Raises the last OSError on timeout -- callers must treat this as
    fail-open (degrade to plain passthrough), never fatal to the underlying
    pi-acp session.
    """
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            return connection.Client(address, family=tap_family(), authkey=authkey)
        except OSError as exc:
            last_error = exc
            time.sleep(_CONNECT_POLL_INTERVAL)
    assert last_error is not None
    raise last_error


__all__ = ["connect_tap", "open_tap_listener", "tap_address", "tap_family"]
