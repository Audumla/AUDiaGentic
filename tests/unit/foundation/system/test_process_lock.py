from __future__ import annotations

import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system import process
from audiagentic.foundation.system.process import StartupLock


def _delayed_pid_claim(path, created, allow_write, entered, release):
    write = process.os.write
    def delayed_write(fd, data):
        created.set()
        if not allow_write.wait(10):
            raise RuntimeError("PID publication was not released")
        return write(fd, data)
    process.os.write = delayed_write
    with StartupLock(Path(path), timeout=5):
        entered.set()
        release.wait(10)


def _contend_for_pid_claim(path, result):
    try:
        with StartupLock(Path(path), timeout=0.2):
            result.put("entered")
    except AudiaGenticError as exc:
        result.put(exc.code)


def test_live_empty_pid_claim_cannot_be_reaped_by_another_process(tmp_path):
    context = multiprocessing.get_context("spawn")
    created, allow_write, entered, release = [context.Event() for _ in range(4)]
    result = context.Queue()
    path = tmp_path / "publication.lock"
    holder = context.Process(target=_delayed_pid_claim, args=(str(path), created, allow_write, entered, release))
    contender = context.Process(target=_contend_for_pid_claim, args=(str(path), result))
    holder.start()
    try:
        assert created.wait(10)
        assert path.read_text() == ""
        contender.start()
        assert result.get(timeout=10) == "TO-PROC-002"
        contender.join(timeout=10)
        assert contender.exitcode == 0
        allow_write.set()
        assert entered.wait(10)
    finally:
        allow_write.set()
        release.set()
        for child in (holder, contender):
            if child.pid is not None:
                child.join(timeout=10)
                if child.is_alive():
                    child.terminate()
                    child.join(timeout=5)
        result.close()
    assert holder.exitcode == 0
    assert not path.exists()


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
