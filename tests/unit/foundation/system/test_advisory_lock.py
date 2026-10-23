from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.advisory_lock import AdvisoryLock


def test_threads_share_fence_and_timeouts_leave_it_usable(tmp_path):
    path = tmp_path / "journal.lock"

    def try_lock():
        with AdvisoryLock(path, timeout=0.05):
            pytest.fail("another thread entered the held fence")

    with AdvisoryLock(path), ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(AudiaGenticError) as error:
            pool.submit(try_lock).result(timeout=2)
        assert error.value.code == "TO-PROC-002"
    with AdvisoryLock(path):
        assert path.is_file()


def test_body_failure_releases_fence_without_unlinking_lock_file(tmp_path):
    path = tmp_path / "journal.lock"
    with pytest.raises(RuntimeError):
        with AdvisoryLock(path):
            raise RuntimeError("writer failed")
    assert path.is_file()
    with AdvisoryLock(path):
        pass


def test_process_death_releases_os_lock(tmp_path):
    path = tmp_path / "journal.lock"
    code = """
import sys, time
from pathlib import Path
from audiagentic.foundation.system.advisory_lock import AdvisoryLock
with AdvisoryLock(Path(sys.argv[1])):
    print('READY', flush=True)
    time.sleep(60)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        assert child.stdout.readline().strip() == b"READY"
        with pytest.raises(AudiaGenticError):
            with AdvisoryLock(path, timeout=0.05):
                pytest.fail("another process entered the held fence")
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
    with AdvisoryLock(path):
        assert path.is_file()
