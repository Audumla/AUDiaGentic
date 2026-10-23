from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system import process
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


def test_timed_out_waiter_preserves_holder_lock_and_reference(tmp_path: Path) -> None:
    lock_path = tmp_path / "contended.lock"
    key = process.os.path.normcase(process.os.path.abspath(lock_path))

    def timeout_waiter() -> AudiaGenticError:
        with pytest.raises(AudiaGenticError) as caught:
            with StartupLock(lock_path, timeout=0.03):
                pytest.fail("waiter entered while the holder was active")
        return caught.value

    with ThreadPoolExecutor(max_workers=1) as pool:
        with StartupLock(lock_path, timeout=1):
            holder_lock, _ = process._thread_locks[key]
            error = pool.submit(timeout_waiter).result(timeout=2)
            assert error.code == "TO-PROC-002"
            assert holder_lock.locked(), "timed-out waiter released the holder's mutex"
            assert process._thread_locks[key] == (holder_lock, 1)
            assert lock_path.exists()

    assert key not in process._thread_locks
    with StartupLock(lock_path, timeout=1):
        assert lock_path.exists()


def test_filesystem_unlock_failure_does_not_leak_thread_mutex(tmp_path: Path, monkeypatch) -> None:
    lock_path = tmp_path / "unlink-fails.lock"
    key = process.os.path.normcase(process.os.path.abspath(lock_path))
    lock = StartupLock(lock_path, timeout=1)

    def fail_unlink() -> None:
        raise PermissionError("lock file is temporarily held open")

    monkeypatch.setattr(lock, "_unlink", fail_unlink)
    with pytest.raises(PermissionError):
        with lock:
            pass
    assert key not in process._thread_locks
