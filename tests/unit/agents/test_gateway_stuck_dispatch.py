"""Stuck dispatch is detected from the work index without mistaking a queue for a fault."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from audiagentic.components.agents.gateway import stuck

NOW = datetime(2026, 11, 2, 7, 0, 0, tzinfo=UTC)


def _entry(request_id: str, phase: str, *, admitted: int = 0, claimed: int | None = None) -> dict:
    stamp = lambda seconds: (NOW - timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")  # noqa: E731
    return {"request-id": request_id, "phase": phase, "admitted-at": stamp(admitted),
            "claimed-at": None if claimed is None else stamp(claimed)}


def test_a_request_waiting_behind_a_running_one_is_queued_not_stuck() -> None:
    report = stuck.classify([_entry("req_a", "running", admitted=3000, claimed=3000),
                             _entry("req_b", "admitted", admitted=1500)], NOW.timestamp())
    assert report.findings == () and report.queued_behind == 1 and report.running == 1


def test_an_idle_lane_with_an_unclaimed_request_is_stuck_after_the_admission_threshold() -> None:
    fresh = stuck.classify([_entry("req_b", "admitted", admitted=30)], NOW.timestamp())
    assert fresh.findings == ()
    old = stuck.classify([_entry("req_b", "admitted", admitted=600)], NOW.timestamp())
    assert [f.code for f in old.findings] == ["admission-stalled"] and old.findings[0].request_id == "req_b"


def test_a_cold_start_may_take_minutes_but_not_forever() -> None:
    cold = stuck.classify([_entry("req_c", "claimed", admitted=300, claimed=300)], NOW.timestamp())
    assert cold.findings == ()  # opening a browser tab after a restart takes minutes
    wedged = stuck.classify([_entry("req_c", "claimed", admitted=1200, claimed=1200)], NOW.timestamp())
    assert [f.code for f in wedged.findings] == ["start-stalled"]


def test_reading_skips_garbage_and_never_writes(tmp_path: Path) -> None:
    folder = tmp_path / "active-work"
    folder.mkdir()
    (folder / "req_ok.json").write_text(json.dumps(_entry("req_ok", "admitted")))
    (folder / "req_bad.json").write_text("{not json")
    (folder / "req_list.json").write_text("[]")
    (folder / "other.json").write_text(json.dumps(_entry("other", "admitted")))
    before = sorted(p.name for p in folder.iterdir())
    entries = stuck.read_entries(tmp_path)
    assert [e["request-id"] for e in entries] == ["req_ok"]
    assert sorted(p.name for p in folder.iterdir()) == before


def test_doctor_reports_a_gateway_runtime_missing_a_provider_module(monkeypatch, tmp_path: Path) -> None:
    import subprocess
    from types import SimpleNamespace

    from audiagentic.components.agents.configuration import doctor_checks

    process = SimpleNamespace(pid=4242)
    store = SimpleNamespace(read=lambda: SimpleNamespace(state="running", process=process))
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"/rt/bin/python\0-m\0x\0")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **_k: subprocess.CompletedProcess(cmd, 1, "", "No module"))
    [result] = doctor_checks._gateway_runtime_modules(store)
    assert result.status == doctor_checks.WARN and "websockets" in result.message
    monkeypatch.setattr(subprocess, "run", lambda cmd, **_k: subprocess.CompletedProcess(cmd, 0, "", ""))
    [result] = doctor_checks._gateway_runtime_modules(store)
    assert result.status == doctor_checks.OK


def test_the_watchdog_records_suspicion_once_and_clears_it_on_recovery(tmp_path: Path) -> None:
    from audiagentic.components.agents.gateway.health import QUEUE, DispatchHealth

    changes = []
    health = DispatchHealth(finder=lambda name: object(), on_change=changes.append)
    folder = tmp_path / "active-work"
    folder.mkdir()
    (folder / "req_a.json").write_text(json.dumps(_entry("req_a", "admitted", admitted=600)))
    stuck.scan_once(tmp_path, health, NOW.timestamp())
    stuck.scan_once(tmp_path, health, NOW.timestamp())  # unchanged verdict: no second event
    snapshot = health.snapshot()
    assert snapshot["suspected"] == [QUEUE] and snapshot["ready"] is True  # suspicion warns, never refuses
    assert [c.status for c in changes] == ["suspected"]
    (folder / "req_a.json").unlink()
    stuck.scan_once(tmp_path, health, NOW.timestamp())
    assert health.snapshot()["suspected"] == [] and [c.status for c in changes] == ["suspected", "available"]


def test_a_failing_listener_or_pass_never_stops_the_watchdog(tmp_path: Path) -> None:
    import threading

    from audiagentic.components.agents.gateway.health import DispatchHealth

    def boom(_change):
        raise RuntimeError("subscriber down")

    health = DispatchHealth(finder=lambda name: object(), on_change=boom)
    (tmp_path / "active-work").mkdir()
    stuck.scan_once(tmp_path, health, NOW.timestamp())  # the listener fault is swallowed

    calls = []
    stop = threading.Event()

    class Flaky:
        def observe_queue(self, findings):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("first pass fails")
            if len(calls) >= 3:
                stop.set()

    stuck.run_watchdog(tmp_path, Flaky(), stop, interval_seconds=0.01)
    assert len(calls) >= 3
