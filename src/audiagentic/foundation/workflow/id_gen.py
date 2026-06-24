"""Thread-safe, process-safe sequential ID generation.

IDs are persisted in configured per-kind counter files.
ID format: ``{prefix}-{n}`` where n is a raw integer with no zero-padding.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.system.process import pid_alive

_process_lock = threading.Lock()
_LOCK_TIMEOUT = 10.0
_LOCK_POLL = 0.05


def _format_id(prefix: str, n: int) -> str:
    return f"{prefix}-{n}"


def next_id(*, counter_path: Path, id_prefix: str) -> str:
    """Return next sequential ID using configured counter file/prefix.

    Args:
        counter_path: Path to counter file from config.
        id_prefix: ID prefix from config.

    Returns:
        Next ID string (e.g., 'request-1', 'task-1')
    """
    if not id_prefix:
        raise make_error(
            prefix="VAL",
            component="WFID",
            number=1,
            kind="workflow",
            message="next_id requires id_prefix",
        )
    return _next_id_config_mode(counter_path, id_prefix)


def _next_id_config_mode(counter_path: Path, id_prefix: str) -> str:
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = counter_path.parent / f"{counter_path.stem}.lock"

    with _process_lock:
        with _IdLock(lock_file, timeout=_LOCK_TIMEOUT):
            if counter_path.exists():
                try:
                    data = json.loads(counter_path.read_text(encoding="utf-8"))
                    n = int(data.get("counter", 0))
                except (json.JSONDecodeError, OSError, ValueError):
                    n = 0
            else:
                n = 0

            n += 1
            counter_path.write_text(json.dumps({"counter": n}, indent=2), encoding="utf-8")

    return _format_id(id_prefix, n)


class _IdLock:
    """Atomic PID lock for workflow counter files."""

    def __init__(self, path: Path, timeout: float) -> None:
        self._path = path
        self._timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> _IdLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            try:
                self._fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                if self._clear_if_stale():
                    continue
                time.sleep(_LOCK_POLL)
        raise TimeoutError(f"Could not acquire ID lock: {self._path}")

    def __exit__(self, *_: object) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self._path.unlink(missing_ok=True)

    def _clear_if_stale(self) -> bool:
        try:
            holder = int(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._path.unlink(missing_ok=True)
            return True
        if pid_alive(holder):
            return False
        self._path.unlink(missing_ok=True)
        return True

