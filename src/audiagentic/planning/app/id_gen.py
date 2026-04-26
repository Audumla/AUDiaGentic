"""Thread-safe, process-safe sequential ID generation for planning items.

IDs are persisted in configured per-kind counter files.
Within a process, a threading.Lock prevents races.
Across processes, an exclusive lock file (O_CREAT|O_EXCL) serializes access.

ID format: ``{kind}-{n}`` where n is a raw integer with no zero-padding.
Example: task-1, task-42, task-346. Never task-0001 or task-0042.
This is the single source of truth for ID format.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

_process_lock = threading.Lock()
_LOCK_TIMEOUT = 10.0
_LOCK_POLL = 0.05


def _format_id(kind: str, n: int) -> str:
    """Single source of truth for ID format: kind-n, no padding, ever."""
    return f"{kind}-{n}"


def next_id(
    *,
    counter_path: Path,
    id_prefix: str,
) -> str:
    """Return next sequential ID using configured counter file/prefix.

    Guarantees uniqueness within a single process (threading.Lock) and across
    concurrent processes (exclusive lock file via O_CREAT | O_EXCL, which is
    atomic on both POSIX and NTFS).

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
    """Generate ID using config-defined counter file.

    Args:
        counter_path: Full path to counter file (e.g., .audiagentic/planning/meta/requests.json)
        id_prefix: ID prefix from config (e.g., 'req', 'task')

    Returns:
        Next ID string
    """
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
                        f"Could not acquire planning ID lock for {id_prefix!r} "
                        f"within {_LOCK_TIMEOUT:.0f}s — is another process stuck?"
                    )
                time.sleep(_LOCK_POLL)

        try:
            # Load counter from file
            if counter_path.exists():
                try:
                    data = json.loads(counter_path.read_text(encoding="utf-8"))
                    n = int(data.get("counter", 0))
                except (json.JSONDecodeError, OSError, ValueError):
                    n = 0
            else:
                n = 0

            # Increment and save
            n += 1
            counter_path.write_text(json.dumps({"counter": n}, indent=2), encoding="utf-8")

        finally:
            lock_file.unlink(missing_ok=True)

    return _format_id(id_prefix, n)


def sync_counter(root: Path, kind: str) -> None:
    """Advance the persisted counter to match the highest scanned ID for *kind*.

    Call this once after installing the planning component into a project that
    already has planning docs, to seed the counter from existing IDs.

    Also fixes corrupted counter values by syncing to actual highest ID.
    """
    from ..fs.scan import scan_items
    from .config import Config

    config = Config(root)
    counter_file = config.kind_counter_file(kind)
    counter_path = root / ".audiagentic" / "planning" / "meta" / counter_file
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    max_n = 0
    try:
        items = scan_items(root)
    except FileNotFoundError:
        items = []

    for item in items:
        if item.kind == kind:
            try:
                max_n = max(max_n, int(item.data["id"].split("-")[1]))
            except (IndexError, ValueError):
                pass

    # Always set counter to scanned max - this is the authoritative value.
    # A counter higher than scanned max means IDs were deleted or corrupted;
    # letting it persist causes runaway ID gaps (e.g. task-3000 after task-334).
    # Monotonicity is preserved because new IDs always increment from here.
    counter_path.write_text(json.dumps({"counter": max_n}, indent=2), encoding="utf-8")
