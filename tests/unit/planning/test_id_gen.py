"""Unit tests for planning thread-safe ID generation."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.id_gen import next_id, sync_counter


def test_sequential_ids(tmp_path: Path) -> None:
    ids = [next_id(tmp_path, "task") for _ in range(5)]
    assert ids == ["task-0001", "task-0002", "task-0003", "task-0004", "task-0005"]


def test_counter_persisted(tmp_path: Path) -> None:
    next_id(tmp_path, "spec")
    next_id(tmp_path, "spec")
    counter = (
        tmp_path / ".audiagentic" / "planning" / "ids" / "spec.counter"
    ).read_text()
    assert counter.strip() == "2"


def test_kinds_independent(tmp_path: Path) -> None:
    assert next_id(tmp_path, "task") == "task-0001"
    assert next_id(tmp_path, "wp") == "wp-0001"
    assert next_id(tmp_path, "task") == "task-0002"
    assert next_id(tmp_path, "wp") == "wp-0002"


def test_resumes_from_persisted_counter(tmp_path: Path) -> None:
    counter_dir = tmp_path / ".audiagentic" / "planning" / "ids"
    counter_dir.mkdir(parents=True)
    (counter_dir / "plan.counter").write_text("7")
    assert next_id(tmp_path, "plan") == "plan-0008"


def test_thread_safety(tmp_path: Path) -> None:
    results: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        id_ = next_id(tmp_path, "task")
        with lock:
            results.append(id_)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 20
    assert len(set(results)) == 20  # all unique


def test_sync_counter_seeds_from_docs(tmp_path: Path) -> None:
    # sync_counter should always create counter file (even if empty)
    # This ensures garbage values are fixed and counters are initialized
    sync_counter(tmp_path, "task")
    counter_file = tmp_path / ".audiagentic" / "planning" / "ids" / "task.counter"
    assert counter_file.exists()
    # Counter should be 0 when no docs exist
    assert int(counter_file.read_text().strip()) == 0


def test_sync_counter_never_moves_backwards(tmp_path: Path) -> None:
    counter_dir = tmp_path / ".audiagentic" / "planning" / "ids"
    counter_dir.mkdir(parents=True)
    counter_file = counter_dir / "task.counter"
    counter_file.write_text("8", encoding="utf-8")

    sync_counter(tmp_path, "task")

    assert int(counter_file.read_text().strip()) == 8
