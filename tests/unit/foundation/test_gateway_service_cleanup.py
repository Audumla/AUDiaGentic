"""The test-suite guard that stops leaked gateway services touches only the test's own home."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psutil
import pytest

from tests.helpers.gateway_service_cleanup import _SERVICE_MODULE, stop_gateway_services


def _stand_in_service(home: Path) -> subprocess.Popen:
    """A process that looks like a gateway service to the cleanup (module name in argv)."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", _SERVICE_MODULE],
        env={**os.environ, "AUDIAGENTIC_HOME": str(home)},
    )


@pytest.fixture
def started(tmp_path: Path):
    processes: list[subprocess.Popen] = []
    yield processes
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait()


def test_stops_a_service_started_under_the_given_home(tmp_path: Path, started: list) -> None:
    mine = _stand_in_service(tmp_path / "home")
    started.append(mine)
    assert psutil.pid_exists(mine.pid)
    assert stop_gateway_services(tmp_path / "home") == [mine.pid]
    mine.wait(timeout=5)
    assert mine.poll() is not None


def test_leaves_a_service_with_another_home_alone(tmp_path: Path, started: list) -> None:
    other = _stand_in_service(tmp_path / "someone-elses-home")
    started.append(other)
    assert stop_gateway_services(tmp_path / "home") == []
    assert other.poll() is None  # still running


def test_leaves_unrelated_processes_with_the_same_home_alone(tmp_path: Path, started: list) -> None:
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        env={**os.environ, "AUDIAGENTIC_HOME": str(tmp_path / "home")},
    )
    started.append(unrelated)
    assert stop_gateway_services(tmp_path / "home") == []
    assert unrelated.poll() is None
