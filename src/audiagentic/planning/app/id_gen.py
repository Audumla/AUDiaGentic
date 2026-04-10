"""Thread-safe, process-safe sequential ID generation for planning items.

IDs are persisted in a consolidated counters file under
``.audiagentic/planning/ids/counters.json``.
Within a process, a threading.Lock prevents races.
Across processes, an exclusive lock file (O_CREAT|O_EXCL) serializes access.
"""

from __future__ import annotations

import threading
import time
import json
from pathlib import Path

_process_lock = threading.Lock()
_IDS_DIR = "ids"
_COUNTERS_FILE = "counters.json"
_LOCK_TIMEOUT = 10.0
_LOCK_POLL = 0.05


def _counters_path(root: Path) -> Path:
    ids_dir = root / ".audiagentic" / "planning" / _IDS_DIR
    ids_dir.mkdir(parents=True, exist_ok=True)
    return ids_dir / _COUNTERS_FILE


def _legacy_counter_path(root: Path, kind: str) -> Path:
    return root / ".audiagentic" / "planning" / _IDS_DIR / f"{kind}.counter"


def _load_counters(root: Path) -> dict[str, int]:
    counters_path = _counters_path(root)
    if not counters_path.exists():
        return {}
    try:
        data = json.loads(counters_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    counters = data.get("counters", {})
    if not isinstance(counters, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in counters.items():
        try:
            out[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def _save_counters(root: Path, counters: dict[str, int]) -> None:
    counters_path = _counters_path(root)
    payload = {"version": 1, "counters": dict(sorted(counters.items()))}
    counters_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _counter_value(root: Path, kind: str, counters: dict[str, int]) -> int:
    if kind in counters:
        return counters[kind]
    legacy_path = _legacy_counter_path(root, kind)
    if not legacy_path.exists():
        return 0
    try:
        return int(legacy_path.read_text(encoding="utf-8").strip())
    except ValueError:
        return 0


def next_id(root: Path, kind: str) -> str:
    """Return the next sequential ID string for *kind* (e.g. ``task-0003``).

    Guarantees uniqueness within a single process (threading.Lock) and across
    concurrent processes (exclusive lock file via O_CREAT | O_EXCL, which is
    atomic on both POSIX and NTFS).

    Counter state is persisted to:
        ``{root}/.audiagentic/planning/ids/counters.json``
    """
    ids_dir = root / ".audiagentic" / "planning" / _IDS_DIR
    ids_dir.mkdir(parents=True, exist_ok=True)
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
            counters = _load_counters(root)
            n = _counter_value(root, kind, counters) + 1
            counters[kind] = n
            _save_counters(root, counters)
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
    max_n = 0
    for item in scan_items(root):
        if item.kind == kind:
            try:
                max_n = max(max_n, int(item.data["id"].split("-")[1]))
            except (IndexError, ValueError):
                pass

    counters = _load_counters(root)
    current_n = _counter_value(root, kind, counters)

    # Always write counter file (create if missing, fix if corrupted)
    # Never move the counter backwards; IDs stay monotonic even after deletes.
    counters[kind] = max(max_n, current_n)
    _save_counters(root, counters)
