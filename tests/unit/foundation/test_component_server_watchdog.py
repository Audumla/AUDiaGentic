from __future__ import annotations

import os
import subprocess
import sys
import time

import mcp.types as mcp_types
import pytest
from mcp.server.fastmcp import FastMCP

from audiagentic.foundation.mcp.component_server import (
    _capture_parent_liveness,
    _install_activity_tracking,
    _parent_is_live,
    _RequestActivityTracker,
    _watchdog_tick,
)


class _FakeClock:
    """Manually-advanced clock so idle-timeout tests never sleep real time."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_activity_tracker_idle_seconds_with_fake_clock() -> None:
    clock = _FakeClock()
    tracker = _RequestActivityTracker(clock=clock)

    clock.advance(5.0)
    assert tracker.idle_seconds() == pytest.approx(5.0)

    tracker.mark()
    assert tracker.idle_seconds() == pytest.approx(0.0)

    clock.advance(3.0)
    assert tracker.idle_seconds() == pytest.approx(3.0)


def test_watchdog_tick_fires_idle_timeout_only_after_threshold() -> None:
    clock = _FakeClock()
    tracker = _RequestActivityTracker(clock=clock)
    # Use this test process itself as the "parent" -- guaranteed alive, and
    # its creation identity trivially matches itself, so this exercises the
    # idle branch without touching the parent-liveness branch.
    parent = _capture_parent_liveness(pid=os.getpid())

    clock.advance(10.0)
    assert _watchdog_tick(tracker, parent, idle_timeout_seconds=12.0) is None

    clock.advance(5.0)  # total idle 15s >= 12s threshold
    assert _watchdog_tick(tracker, parent, idle_timeout_seconds=12.0) == "idle-timeout"


def test_watchdog_tick_does_not_fire_on_normal_activity() -> None:
    clock = _FakeClock()
    tracker = _RequestActivityTracker(clock=clock)
    parent = _capture_parent_liveness(pid=os.getpid())

    # Simulate periodic genuine requests resetting idleness before the
    # timeout would ever be reached.
    for _ in range(20):
        clock.advance(5.0)
        tracker.mark()
        assert _watchdog_tick(tracker, parent, idle_timeout_seconds=12.0) is None


def test_parent_is_live_true_for_running_process_then_false_after_exit() -> None:
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(5)"],
    )
    try:
        parent = _capture_parent_liveness(pid=proc.pid)
        assert parent.creation_identity is not None
        assert _parent_is_live(parent) is True

        proc.terminate()
        proc.wait(timeout=10)

        assert _parent_is_live(parent) is False
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_parent_is_live_detects_pid_reuse_by_a_different_process(monkeypatch: pytest.MonkeyPatch) -> None:
    # Guard against the false-positive trap explicitly called out by the
    # user: a dead parent's pid can be recycled by an unrelated live
    # process. A bare pid_alive() check would wrongly call that "live";
    # the creation-identity comparison must not.
    parent = _capture_parent_liveness(pid=os.getpid())
    assert parent.creation_identity is not None

    monkeypatch.setattr(
        "audiagentic.foundation.system.managed_process.process_creation_identity",
        lambda pid: "a-completely-different-identity",
    )

    assert _parent_is_live(parent) is False


def test_watchdog_tick_fires_parent_exited_before_idle_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()
    tracker = _RequestActivityTracker(clock=clock)
    parent = _capture_parent_liveness(pid=os.getpid())

    monkeypatch.setattr(
        "audiagentic.foundation.mcp.component_server._parent_is_live",
        lambda _parent: False,
    )

    # Idle timeout threshold not reached -- parent-exited must still fire.
    assert _watchdog_tick(tracker, parent, idle_timeout_seconds=_very_large()) == "parent-exited"


def _very_large() -> float:
    return 10**9


@pytest.mark.asyncio
async def test_install_activity_tracking_marks_on_real_request() -> None:
    server = FastMCP("watchdog-test-server")

    @server.tool()
    def noop() -> str:
        return "ok"

    tracker = _install_activity_tracking(server)

    # Let real idle time build up, then drive an actual request through the
    # wrapped handler and confirm it resets idleness -- proof the wrapping
    # observes genuine protocol traffic, not just construction time.
    time.sleep(0.2)
    assert tracker.idle_seconds() >= 0.2

    mcp_server = server._mcp_server  # type: ignore[attr-defined]
    handler = mcp_server.request_handlers[mcp_types.ListToolsRequest]
    await handler(mcp_types.ListToolsRequest())

    assert tracker.idle_seconds() < 0.2
