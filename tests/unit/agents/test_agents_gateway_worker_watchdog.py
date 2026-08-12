"""Unit tests for SH22's provider-terminal wait policy in worker.py."""
from __future__ import annotations

import threading
import time

from audiagentic.components.agents.gateway.queue import worker as worker_module


class _FakeChild:
    """Emulates the subset of SupervisedProcess's interface the watchdog
    uses: .pid and .communicate(input_text) blocking for `run_seconds`."""

    def __init__(self, run_seconds: float) -> None:
        self.pid = 999999
        self._run_seconds = run_seconds
        self._done = threading.Event()

    def communicate(self, input_text: str) -> tuple[str, str]:
        del input_text
        time.sleep(self._run_seconds)
        self._done.set()
        return "stdout-payload", "stderr-payload"


def test_process_completes_before_timeout_returns_normally(monkeypatch) -> None:
    child = _FakeChild(run_seconds=0.1)
    stdout, stderr = worker_module._wait_for_provider_terminal(
        child, "input", timeout_seconds=5.0
    )
    assert stdout == "stdout-payload"
    assert stderr == "stderr-payload"


def test_elapsed_timeout_is_not_a_gateway_failure() -> None:
    """Quiet remote/tool work may outlive the request timeout without a kill."""
    child = _FakeChild(run_seconds=0.3)
    stdout, stderr = worker_module._wait_for_provider_terminal(
        child, "input", timeout_seconds=0.1
    )
    assert stdout == "stdout-payload"
    assert stderr == "stderr-payload"


def test_no_cpu_sampling_is_needed_for_provider_terminal() -> None:
    child = _FakeChild(run_seconds=0.15)
    stdout, stderr = worker_module._wait_for_provider_terminal(
        child, "input", timeout_seconds=0.05
    )
    assert stdout == "stdout-payload"
    assert stderr == "stderr-payload"
