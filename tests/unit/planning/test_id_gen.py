"""Unit tests for config-driven planning ID generation."""

from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.planning_testkit import seed_planning_config

from audiagentic.planning.app.id_gen import _format_id, _next_id_config_mode, next_id, sync_counter

ID_PATTERN = re.compile(r"^[a-z]+-([1-9]\d*|0)$")


def _seed_root(tmp_path: Path) -> Path:
    seed_planning_config(tmp_path)
    return tmp_path


def test_format_id_raw_single_digit() -> None:
    assert _format_id("task", 1) == "task-1"


def test_format_id_raw_large() -> None:
    assert _format_id("task", 9999) == "task-9999"


def test_format_id_no_padding() -> None:
    for n in (1, 2, 9, 10, 99, 100):
        result = _format_id("task", n)
        numeric = result.split("-")[1]
        assert not (len(numeric) > 1 and numeric[0] == "0"), f"Padded: {result!r}"


def test_next_id_requires_prefix(tmp_path: Path) -> None:
    counter_path = tmp_path / "task.json"
    try:
        next_id(counter_path=counter_path, id_prefix="")
    except ValueError as exc:
        assert "id_prefix" in str(exc)
    else:
        raise AssertionError("next_id accepted empty id_prefix")


def test_config_mode_raw_format(tmp_path: Path) -> None:
    counter_path = tmp_path / "task.json"
    id1 = next_id(counter_path=counter_path, id_prefix="task")
    assert id1 == "task-1"
    assert ID_PATTERN.match(id1)


def test_config_mode_increments(tmp_path: Path) -> None:
    counter_path = tmp_path / "task.json"
    ids = [next_id(counter_path=counter_path, id_prefix="task") for _ in range(5)]
    assert ids == ["task-1", "task-2", "task-3", "task-4", "task-5"]


def test_config_mode_resumes_from_seeded_counter(tmp_path: Path) -> None:
    counter_path = tmp_path / "task.json"
    counter_path.write_text(json.dumps({"counter": 345}), encoding="utf-8")
    assert _next_id_config_mode(counter_path, "task") == "task-346"


def test_config_mode_thread_safety(tmp_path: Path) -> None:
    counter_path = tmp_path / "task.json"
    results: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        id_ = next_id(counter_path=counter_path, id_prefix="task")
        with lock:
            results.append(id_)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 20
    assert len(set(results)) == 20


def test_pattern_rejects_padded() -> None:
    for bad_id in ("task-0001", "task-001", "task-01", "spec-0080"):
        assert not ID_PATTERN.match(bad_id), f"Should reject padded ID: {bad_id!r}"


def test_pattern_accepts_raw() -> None:
    for good_id in ("task-1", "task-42", "task-346", "spec-80", "request-21"):
        assert ID_PATTERN.match(good_id), f"Should accept raw ID: {good_id!r}"


def test_sync_counter_seeds_configured_counter_file(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    sync_counter(root, "task")
    counter_file = root / ".audiagentic" / "planning" / "meta" / "tasks.json"
    assert counter_file.exists()
    assert json.loads(counter_file.read_text())["counter"] == 0


def test_sync_counter_corrects_inflated_configured_counter(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    counter_file = root / ".audiagentic" / "planning" / "meta" / "tasks.json"
    counter_file.parent.mkdir(parents=True, exist_ok=True)
    counter_file.write_text(json.dumps({"counter": 3264}), encoding="utf-8")

    sync_counter(root, "task")

    assert json.loads(counter_file.read_text())["counter"] == 0
