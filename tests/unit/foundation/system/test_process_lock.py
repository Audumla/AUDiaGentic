from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from audiagentic.foundation.system.process import StartupLock


def test_startup_lock_serializes_threads_before_filesystem_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "shared.lock"
    entered: list[int] = []
    active = 0
    overlap = False
    state_guard = threading.Lock()

    def use_lock(index: int) -> None:
        nonlocal active, overlap
        with StartupLock(lock_path, timeout=2):
            with state_guard:
                active += 1
                overlap = overlap or active > 1
            entered.append(index)
            time.sleep(0.01)
            with state_guard:
                active -= 1

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(use_lock, range(8)))

    assert sorted(entered) == list(range(8))
    assert overlap is False
    assert not lock_path.exists()
