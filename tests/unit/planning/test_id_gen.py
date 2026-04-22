"""Unit tests for planning ID generation.

Enforces the single invariant: IDs are always kind-{n} with no zero-padding.
Both code paths (legacy mode and config-driven mode) must use _format_id().
"""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.id_gen import (
    _format_id,
    _next_id_config_mode,
    next_id,
    sync_counter,
)

ID_PATTERN = re.compile(r'^[a-z]+-([1-9]\d*|0)$')


# --- _format_id: single source of truth ---

def test_format_id_raw_single_digit():
    assert _format_id("task", 1) == "task-1"


def test_format_id_raw_large():
    assert _format_id("task", 9999) == "task-9999"


def test_format_id_no_padding():
    for n in (1, 2, 9, 10, 99, 100):
        result = _format_id("task", n)
        numeric = result.split("-")[1]
        assert not (len(numeric) > 1 and numeric[0] == "0"), f"Padded: {result!r}"


# --- legacy next_id mode ---

def test_sequential_ids(tmp_path: Path) -> None:
    ids = [next_id(tmp_path, "task") for _ in range(5)]
    assert ids == ["task-1", "task-2", "task-3", "task-4", "task-5"]


def test_counter_persisted(tmp_path: Path) -> None:
    next_id(tmp_path, "spec")
    next_id(tmp_path, "spec")
    counters = json.loads(
        (tmp_path / ".audiagentic" / "planning" / "ids" / "counters.json").read_text()
    )
    assert counters["counters"]["spec"] == 2


def test_kinds_independent(tmp_path: Path) -> None:
    assert next_id(tmp_path, "task") == "task-1"
    assert next_id(tmp_path, "wp") == "wp-1"
    assert next_id(tmp_path, "task") == "task-2"
    assert next_id(tmp_path, "wp") == "wp-2"


def test_resumes_from_persisted_counter(tmp_path: Path) -> None:
    counter_dir = tmp_path / ".audiagentic" / "planning" / "ids"
    counter_dir.mkdir(parents=True)
    counters_file = counter_dir / "counters.json"
    counters_file.write_text(
        json.dumps({"version": 1, "counters": {"plan": 7}}), encoding="utf-8"
    )
    assert next_id(tmp_path, "plan") == "plan-8"


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
    assert len(set(results)) == 20


# --- config-driven mode ---

def test_config_mode_raw_format(tmp_path: Path) -> None:
    counter_path = tmp_path / "task.json"
    id1 = _next_id_config_mode(counter_path, "task")
    assert id1 == "task-1"
    assert ID_PATTERN.match(id1)


def test_config_mode_increments(tmp_path: Path) -> None:
    counter_path = tmp_path / "task.json"
    ids = [_next_id_config_mode(counter_path, "task") for _ in range(5)]
    assert ids == ["task-1", "task-2", "task-3", "task-4", "task-5"]


def test_config_mode_resumes_from_seeded_counter(tmp_path: Path) -> None:
    counter_path = tmp_path / "task.json"
    counter_path.write_text(json.dumps({"counter": 345}), encoding="utf-8")
    assert _next_id_config_mode(counter_path, "task") == "task-346"


# --- both modes produce identical format ---

def test_both_modes_agree_at_n1(tmp_path: Path) -> None:
    legacy = next_id(root=tmp_path / "a", kind="task")
    config = _next_id_config_mode(tmp_path / "task.json", "task")
    assert legacy == config == "task-1"


def test_both_modes_agree_at_large_n(tmp_path: Path) -> None:
    counter_path = tmp_path / "task.json"
    counter_path.write_text(json.dumps({"counter": 345}), encoding="utf-8")
    config_id = _next_id_config_mode(counter_path, "task")

    counter_dir = (tmp_path / "b") / ".audiagentic" / "planning" / "ids"
    counter_dir.mkdir(parents=True)
    (counter_dir / "counters.json").write_text(
        json.dumps({"version": 1, "counters": {"task": 345}}), encoding="utf-8"
    )
    legacy_id = next_id(root=tmp_path / "b", kind="task")

    assert config_id == legacy_id == "task-346"


# --- ID pattern: rejects padded, accepts raw ---

@pytest.mark.parametrize("bad_id", [
    "task-0001", "task-001", "task-01",
    "spec-0080", "wp-0028", "request-0021",
])
def test_pattern_rejects_padded(bad_id: str) -> None:
    assert not ID_PATTERN.match(bad_id), f"Should reject padded ID: {bad_id!r}"


@pytest.mark.parametrize("good_id", [
    "task-1", "task-42", "task-346", "task-9999",
    "spec-80", "wp-28", "request-21", "plan-23",
])
def test_pattern_accepts_raw(good_id: str) -> None:
    assert ID_PATTERN.match(good_id), f"Should accept raw ID: {good_id!r}"


# --- sync_counter resets to scanned max ---

def test_sync_counter_seeds_from_zero_when_no_docs(tmp_path: Path) -> None:
    sync_counter(tmp_path, "task")
    counter_file = tmp_path / ".audiagentic" / "planning" / "ids" / "counters.json"
    assert counter_file.exists()
    counters = json.loads(counter_file.read_text())
    assert counters["counters"]["task"] == 0


def test_sync_counter_corrects_inflated_counter(tmp_path: Path) -> None:
    """Counter inflated above scanned max must be corrected downward.

    This is the root cause of the task-3000 gap: a counter of 3264 with
    only 316 tasks caused next_id to skip ~2950 IDs. sync_counter must
    set the counter to the actual scanned max, not preserve the high value.
    """
    counter_dir = tmp_path / ".audiagentic" / "planning" / "ids"
    counter_dir.mkdir(parents=True)
    counter_file = counter_dir / "counters.json"
    # Simulate the corrupted state: counter says 3264, but no docs exist
    counter_file.write_text(
        json.dumps({"version": 1, "counters": {"task": 3264}}), encoding="utf-8"
    )

    sync_counter(tmp_path, "task")

    counters = json.loads(counter_file.read_text())
    # Must reset to 0 (scanned max), not preserve 3264
    assert counters["counters"]["task"] == 0, (
        f"sync_counter preserved inflated counter {counters['counters']['task']}, "
        "expected 0 (scanned max with no docs)"
    )
