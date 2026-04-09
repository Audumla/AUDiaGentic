"""Thread-safe, process-safe sequential ID generation for planning items.

IDs are persisted as per-kind counters under .audiagentic/planning/ids/.
Within a process, a threading.Lock prevents races.
Across processes, an exclusive lock file (O_CREAT|O_EXCL) serializes access.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

_process_lock = threading.Lock()
_IDS_DIR = "ids"
_LOCK_TIMEOUT = 10.0
_LOCK_POLL = 0.05


def next_id(root: Path, kind: str) -> str:
    """Return the next sequential ID string for *kind* (e.g. ``task-0003``).

    Guarantees uniqueness within a single process (threading.Lock) and across
    concurrent processes (exclusive lock file via O_CREAT | O_EXCL, which is
    atomic on both POSIX and NTFS).

    Counter state is persisted to:
        ``{root}/.audiagentic/planning/ids/{kind}.counter``
    """
    ids_dir = root / ".audiagentic" / "planning" / _IDS_DIR
    ids_dir.mkdir(parents=True, exist_ok=True)
    counter_file = ids_dir / f"{kind}.counter"
    lock_file = ids_dir / f"{kind}.lock"

    with _process_lock:
        deadline = time.monotonic() + _LOCK_TIMEOUT
        while True:
            try:
                lock_file.touch(exist_ok=False)
                break
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"Could not acquire planning ID lock for {kind!r} "
                        f"within {_LOCK_TIMEOUT:.0f}s — is another process stuck?"
                    )
                time.sleep(_LOCK_POLL)
        try:
            n = (
                int(counter_file.read_text(encoding="utf-8").strip()) + 1
                if counter_file.exists()
                else 1
            )
            counter_file.write_text(str(n), encoding="utf-8")
        finally:
            lock_file.unlink(missing_ok=True)

    return f"{kind}-{n:04d}"


def sync_counter(root: Path, kind: str) -> None:
    """Advance the persisted counter to match the highest scanned ID for *kind*.

    Call this once after installing the planning component into a project that
    already has planning docs, to seed the counter from existing IDs.

    Also fixes corrupted counter values by syncing to actual highest ID.
    """
    from ..fs.scan import scan_items

    ids_dir = root / ".audiagentic" / "planning" / _IDS_DIR
    ids_dir.mkdir(parents=True, exist_ok=True)
    counter_file = ids_dir / f"{kind}.counter"

    max_n = 0
    for item in scan_items(root):
        if item.kind == kind:
            try:
                max_n = max(max_n, int(item.data["id"].split("-")[1]))
            except (IndexError, ValueError):
                pass

    # Always write counter file (create if missing, fix if corrupted)
    # Use max_n as authoritative value (from actual files)
    counter_file.write_text(str(max_n), encoding="utf-8")
