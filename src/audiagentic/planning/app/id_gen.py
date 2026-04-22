"""Thread-safe, process-safe sequential ID generation for planning items.

IDs are persisted in a consolidated counters file under
``.audiagentic/planning/ids/counters.json``.
Within a process, a threading.Lock prevents races.
Across processes, an exclusive lock file (O_CREAT|O_EXCL) serializes access.

ID format: ``{kind}-{n}`` where n is a raw integer with no zero-padding.
Example: task-1, task-42, task-346. Never task-0001 or task-0042.
This is the single source of truth for ID format — both code paths use
``_format_id()`` so format cannot diverge.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

_process_lock = threading.Lock()
_IDS_DIR = "ids"
_COUNTERS_FILE = "counters.json"
_LOCK_TIMEOUT = 10.0
_LOCK_POLL = 0.05


def _format_id(kind: str, n: int) -> str:
    """Single source of truth for ID format: kind-n, no padding, ever."""
    return f"{kind}-{n}"


def _counters_path(root: Path, test_mode: bool = False) -> Path:
    if test_mode:
        ids_dir = root / "test" / ".audiagentic" / "planning" / _IDS_DIR
    else:
        ids_dir = root / ".audiagentic" / "planning" / _IDS_DIR
    ids_dir.mkdir(parents=True, exist_ok=True)
    return ids_dir / _COUNTERS_FILE


def _legacy_counter_path(root: Path, kind: str, test_mode: bool = False) -> Path:
    if test_mode:
        return root / "test" / ".audiagentic" / "planning" / _IDS_DIR / f"{kind}.counter"
    return root / ".audiagentic" / "planning" / _IDS_DIR / f"{kind}.counter"


def _load_counters(root: Path, test_mode: bool = False) -> dict[str, int]:
    counters_path = _counters_path(root, test_mode)
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


def _save_counters(root: Path, counters: dict[str, int], test_mode: bool = False) -> None:
    counters_path = _counters_path(root, test_mode)
    payload = {"version": 1, "counters": dict(sorted(counters.items()))}
    counters_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _counter_value(root: Path, kind: str, counters: dict[str, int], test_mode: bool = False) -> int:
    if kind in counters:
        return counters[kind]
    legacy_path = _legacy_counter_path(root, kind, test_mode)
    if not legacy_path.exists():
        return 0
    try:
        return int(legacy_path.read_text(encoding="utf-8").strip())
    except ValueError:
        return 0


def next_id(
    root: Path | None = None,
    kind: str = "",
    test_mode: bool = False,
    counter_path: Path | None = None,
    id_prefix: str = "",
) -> str:
    """Return the next sequential ID string for *kind* (e.g. ``task-0003``).

    Two modes of operation:
    1. Config-driven (preferred): counter_path and id_prefix provided
       - Uses per-kind counter file from config
       - ID format: {id_prefix}-{n:04d}
    2. Legacy: root and kind provided, counter_path and id_prefix not provided
       - Uses consolidated counters.json
       - ID format: {kind}-{n:04d}

    Guarantees uniqueness within a single process (threading.Lock) and across
    concurrent processes (exclusive lock file via O_CREAT | O_EXCL, which is
    atomic on both POSIX and NTFS).

    Args:
        root: Root directory (legacy mode)
        kind: Kind name (legacy mode)
        test_mode: Whether in test mode (legacy mode)
        counter_path: Path to counter file (config-driven mode)
        id_prefix: ID prefix from config (config-driven mode)

    Returns:
        Next ID string (e.g., 'req-0001', 'task-0001')
    """
    # Config-driven mode
    if counter_path is not None and id_prefix:
        return _next_id_config_mode(counter_path, id_prefix)

    # Legacy mode (backward compatible)
    if not root or not kind:
        raise ValueError("next_id requires either (root, kind) or (counter_path, id_prefix)")

    if test_mode:
        ids_dir = root / "test" / ".audiagentic" / "planning" / _IDS_DIR
    else:
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
            counters = _load_counters(root, test_mode)
            n = _counter_value(root, kind, counters, test_mode) + 1
            counters[kind] = n
            _save_counters(root, counters, test_mode)
        finally:
            lock_file.unlink(missing_ok=True)

    return _format_id(kind, n)


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


def sync_counter(root: Path, kind: str, test_mode: bool = False) -> None:
    """Advance the persisted counter to match the highest scanned ID for *kind*.

    Call this once after installing the planning component into a project that
    already has planning docs, to seed the counter from existing IDs.

    Also fixes corrupted counter values by syncing to actual highest ID.
    """
    from ..fs.scan import scan_items

    if test_mode:
        ids_dir = root / "test" / ".audiagentic" / "planning" / _IDS_DIR
    else:
        ids_dir = root / ".audiagentic" / "planning" / _IDS_DIR
    ids_dir.mkdir(parents=True, exist_ok=True)
    max_n = 0
    for item in scan_items(root):
        if item.kind == kind:
            try:
                max_n = max(max_n, int(item.data["id"].split("-")[1]))
            except (IndexError, ValueError):
                pass

    counters = _load_counters(root, test_mode)

    # Always set counter to scanned max — this is the authoritative value.
    # A counter higher than scanned max means IDs were deleted or corrupted;
    # letting it persist causes runaway ID gaps (e.g. task-3000 after task-334).
    # Monotonicity is preserved because new IDs always increment from here.
    counters[kind] = max_n
    _save_counters(root, counters, test_mode)
