"""Thread-safe, process-safe sequential ID generation.

IDs are persisted in configured per-kind counter files.
ID format: ``{prefix}-{n}`` where n is a raw integer with no zero-padding.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

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
        raise ValueError("next_id requires id_prefix")
    return _next_id_config_mode(counter_path, id_prefix)


def _next_id_config_mode(counter_path: Path, id_prefix: str) -> str:
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = counter_path.parent / f"{counter_path.stem}.lock"

    with _process_lock:
        deadline = time.monotonic() + _LOCK_TIMEOUT
        while True:
            try:
                lock_file.touch(exist_ok=False)
                break
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"Could not acquire ID lock for {id_prefix!r} within {_LOCK_TIMEOUT:.0f}s"
                    )
                time.sleep(_LOCK_POLL)

        try:
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

        finally:
            lock_file.unlink(missing_ok=True)

    return _format_id(id_prefix, n)
