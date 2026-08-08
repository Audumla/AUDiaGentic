"""Unit tests for SH22's activity-verified watchdog in worker.py.

Uses a fake child object and a monkeypatched CPU-time reader for fast,
deterministic coverage of the actual decision logic -- genuine CPU-consuming
progress extends the wait, flat CPU after the grace period is a verified
stall, and the absolute ceiling always wins. Real subprocess/OS-signal
proof of the same behavior lives in
tests/integration/agents/test_sh06_worker_isolation.py.
"""
from __future__ import annotations

import threading
import time

import pytest

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
    monkeypatch.setattr(worker_module, "_STALL_POLL_INTERVAL_SECONDS", 0.05)
    child = _FakeChild(run_seconds=0.1)
    stdout, stderr = worker_module._wait_with_activity_watchdog(
        child, "input", timeout_seconds=5.0
    )
    assert stdout == "stdout-payload"
    assert stderr == "stderr-payload"


def test_genuine_activity_extends_past_timeout_seconds(monkeypatch) -> None:
    """The core SH22 fix: a worker that is genuinely still consuming CPU
    past timeout_seconds is NOT killed -- it completes normally. This is
    exactly the false-positive class the fixed 180s ceiling produced."""
    monkeypatch.setattr(worker_module, "_STALL_POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "_ABSOLUTE_SAFETY_CEILING_SECONDS", 10.0)

    cpu_time = [0.0]

    def _fake_cpu_time(pid: int) -> float:
        del pid
        cpu_time[0] += 0.02  # always ticking up -- genuine, verified progress
        return cpu_time[0]

    monkeypatch.setattr(worker_module, "process_cpu_time_seconds", _fake_cpu_time)

    # timeout_seconds is deliberately shorter than the fake child's real
    # runtime -- the old fixed-ceiling code would have killed this.
    child = _FakeChild(run_seconds=0.3)
    stdout, stderr = worker_module._wait_with_activity_watchdog(
        child, "input", timeout_seconds=0.1
    )
    assert stdout == "stdout-payload"
    assert stderr == "stderr-payload"


def test_flat_cpu_after_timeout_raises_verified_stall(monkeypatch) -> None:
    """A worker with zero CPU activity past timeout_seconds is a genuine
    stall and must still be caught promptly -- this is what keeps the
    existing hung-worker regression test (SH06) fast."""
    monkeypatch.setattr(worker_module, "_STALL_POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "_STALL_GRACE_POLLS", 2)
    monkeypatch.setattr(worker_module, "_ABSOLUTE_SAFETY_CEILING_SECONDS", 10.0)
    monkeypatch.setattr(worker_module, "process_cpu_time_seconds", lambda pid: 1.0)

    # The fake child never completes within the test's patience -- it is a
    # stand-in for a truly hung process.
    child = _FakeChild(run_seconds=5.0)
    with pytest.raises(worker_module._WatchdogStall) as exc_info:
        worker_module._wait_with_activity_watchdog(child, "input", timeout_seconds=0.05)
    assert exc_info.value.classification == "verified-stall"


def test_absolute_ceiling_wins_even_with_activity(monkeypatch) -> None:
    """Genuine progress extends the wait, but never past the absolute
    safety ceiling -- there is always a real upper bound."""
    monkeypatch.setattr(worker_module, "_STALL_POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "_ABSOLUTE_SAFETY_CEILING_SECONDS", 0.2)

    cpu_time = [0.0]

    def _fake_cpu_time(pid: int) -> float:
        del pid
        cpu_time[0] += 0.02
        return cpu_time[0]

    monkeypatch.setattr(worker_module, "process_cpu_time_seconds", _fake_cpu_time)

    child = _FakeChild(run_seconds=5.0)  # never completes within the ceiling
    with pytest.raises(worker_module._WatchdogStall) as exc_info:
        worker_module._wait_with_activity_watchdog(child, "input", timeout_seconds=0.01)
    assert exc_info.value.classification == "absolute-safety-ceiling"


def test_unreadable_cpu_time_does_not_crash_the_watchdog(monkeypatch) -> None:
    """process_cpu_time_seconds returning None (e.g. a fact-read race with
    process exit) must not raise -- the loop keeps polling and lets the
    next join() observe the real state."""
    monkeypatch.setattr(worker_module, "_STALL_POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "process_cpu_time_seconds", lambda pid: None)

    child = _FakeChild(run_seconds=0.15)
    stdout, stderr = worker_module._wait_with_activity_watchdog(
        child, "input", timeout_seconds=0.05
    )
    assert stdout == "stdout-payload"
    assert stderr == "stderr-payload"
