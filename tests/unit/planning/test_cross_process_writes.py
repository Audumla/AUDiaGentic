"""Regression tests for planning writes from independent MCP processes."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from audiagentic.components.planning import item_store, planning_api

_ROOT = Path(__file__).parents[3]
_WORKER = """
from pathlib import Path
import sys
import time

from audiagentic.components.planning import item_store, planning_api

root = Path(sys.argv[1])
mode = sys.argv[2]
lock_kind = sys.argv[3]
item_id = sys.argv[4]
started = Path(sys.argv[5])
release = Path(sys.argv[6])
completed = Path(sys.argv[7])

if mode == "hold":
    lock = (
        item_store.planning_collection_write_lock(root)
        if lock_kind == "collection"
        else item_store.item_identity_write_lock(root, item_id)
    )
    with lock:
        started.write_text("started", encoding="utf-8")
        while not release.exists():
            time.sleep(0.01)
elif mode == "item-update":
    started.write_text("started", encoding="utf-8")
    planning_api.update_item(root, "TST01", {"notes": "written by another process"})
    completed.write_text("completed", encoding="utf-8")
elif mode == "review-update":
    started.write_text("started", encoding="utf-8")
    planning_api.update_review(root, "RV01", {"notes": "written by another process"})
    completed.write_text("completed", encoding="utf-8")
elif mode == "item-create":
    started.write_text("started", encoding="utf-8")
    planning_api.create_item(root, {"plan": "test-plan", "title": "created by another process"})
    completed.write_text("completed", encoding="utf-8")
else:
    raise ValueError(f"unknown worker mode: {mode}")
"""


def _start_worker(
    root: Path,
    mode: str,
    lock_kind: str,
    item_id: str,
    started: Path,
    release: Path,
    completed: Path,
) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(_ROOT / "src"), env.get("PYTHONPATH", "")])
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            _WORKER,
            str(root),
            mode,
            lock_kind,
            item_id,
            str(started),
            str(release),
            str(completed),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def _wait_for(path: Path, timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return path.exists()


def _mutate_in_current_process(root: Path, operation: str) -> None:
    if operation == "item-update":
        planning_api.update_item(root, "TST01", {"notes": "written by another thread"})
    elif operation == "review-update":
        planning_api.update_review(root, "RV01", {"notes": "written by another thread"})
    elif operation == "item-create":
        planning_api.create_item(root, {"plan": "test-plan", "title": "created by another thread"})
    else:  # pragma: no cover - protects the test protocol
        raise ValueError(f"unknown operation: {operation}")


@pytest.mark.parametrize(
    ("lock_kind", "item_id", "operation"),
    [
        ("identity", "tst01", "item-update"),
        ("identity", "RV01", "review-update"),
        ("collection", "", "item-create"),
    ],
)
def test_planning_mutations_wait_for_another_thread(
    tmp_path: Path,
    lock_kind: str,
    item_id: str,
    operation: str,
) -> None:
    """Thread-local and cross-process portions of each lock compose safely."""
    planning_api.create_item(
        tmp_path,
        {"id": "TST01", "plan": "test-plan", "title": "Test item", "created-by": "test"},
    )
    if operation == "review-update":
        planning_api.create_review(
            tmp_path, {"id": "RV01", "review-of": "TST01", "title": "Review"}
        )

    acquired = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    lock = (
        item_store.planning_collection_write_lock(tmp_path)
        if lock_kind == "collection"
        else item_store.item_identity_write_lock(tmp_path, item_id)
    )

    def hold_lock() -> None:
        with lock:
            acquired.set()
            assert release.wait(timeout=15), "thread lock release timed out"

    def mutate() -> None:
        _mutate_in_current_process(tmp_path, operation)
        completed.set()

    holder = threading.Thread(target=hold_lock)
    writer = threading.Thread(target=mutate)
    holder.start()
    assert acquired.wait(timeout=15), "lock holder did not start"
    writer.start()
    assert not completed.wait(timeout=1), "writer bypassed the planning thread lock"
    release.set()
    holder.join(timeout=15)
    writer.join(timeout=15)
    assert not holder.is_alive()
    assert not writer.is_alive()
    assert completed.is_set()


@pytest.mark.parametrize(
    ("lock_kind", "item_id", "operation"),
    [
        ("identity", "tst01", "item-update"),
        ("identity", "RV01", "review-update"),
        ("collection", "", "item-create"),
    ],
)
def test_planning_mutations_wait_for_another_process(
    tmp_path: Path,
    lock_kind: str,
    item_id: str,
    operation: str,
) -> None:
    """A separate process cannot enter the same planning write critical section."""
    planning_api.create_item(
        tmp_path,
        {"id": "TST01", "plan": "test-plan", "title": "Test item", "created-by": "test"},
    )
    if operation == "review-update":
        planning_api.create_review(
            tmp_path, {"id": "RV01", "review-of": "TST01", "title": "Review"}
        )

    holder_started = tmp_path / "holder-started"
    writer_started = tmp_path / "writer-started"
    release = tmp_path / "release"
    completed = tmp_path / "completed"
    holder = _start_worker(tmp_path, "hold", lock_kind, item_id, holder_started, release, completed)
    writer: subprocess.Popen[str] | None = None
    try:
        assert _wait_for(holder_started), "lock holder did not start"
        writer = _start_worker(
            tmp_path, operation, lock_kind, item_id, writer_started, release, completed
        )
        assert _wait_for(writer_started), "writer did not start"
        assert not _wait_for(completed, timeout=1), (
            "writer bypassed the cross-process planning lock"
        )
    finally:
        release.write_text("release", encoding="utf-8")

    holder_stdout, holder_stderr = holder.communicate(timeout=15)
    assert holder.returncode == 0, holder_stdout + holder_stderr
    assert writer is not None
    writer_stdout, writer_stderr = writer.communicate(timeout=15)
    assert writer.returncode == 0, writer_stdout + writer_stderr
    assert completed.exists()
