"""SH22 acceptance, non-destructive half: verified activity keeps work alive; nothing else does.

A fake clock stands in for wall time. Receipt time is the gateway's (``now_iso_z``) and expiry is
judged against ``datetime.now`` inside the store, so both are driven from one clock.
"""
from __future__ import annotations

import datetime as datetime_module
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.store import _transitions
from audiagentic.foundation.contracts.errors import AudiaGenticError

_BASE = datetime_module.datetime(2026, 10, 30, 12, 0, 0, tzinfo=datetime_module.timezone.utc)
LEASE = 300.0
_FENCED = "CON-AGW-07[23]|CON-AGW-083"  # worker / attempt / dispatch-owner fence
OLD_CEILING = 3900.0  # a live review actively streamed past this and was cancelled by the old fixed kill


class _Clock:
    def __init__(self) -> None:
        self.elapsed = 0.0

    def now(self) -> datetime_module.datetime:
        return _BASE + datetime_module.timedelta(seconds=self.elapsed)

    def advance(self, seconds: float) -> None:
        self.elapsed += seconds


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    fake = _Clock()
    real = datetime_module.datetime

    class FakeDatetime(real):
        @classmethod
        def now(cls, tz=None):
            return fake.now() if tz is not None else fake.now().replace(tzinfo=None)

    monkeypatch.setattr(datetime_module, "datetime", FakeDatetime)
    monkeypatch.setattr(_transitions, "now_iso_z", lambda: fake.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    return fake


def _running(root: Path, owner: str = "service-a", worker: str = "worker-a") -> tuple[dict, dict]:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(root, record)
    claimed = store.claim_dispatch(root, record["request-id"], owner_epoch=owner, expected_revision=0)
    running = store.start_owned_attempt(root, record["request-id"], owner_epoch=owner, worker_id=worker,
                                        expected_revision=claimed["revision"])
    return record, running


def _renew(root, record, running, *, seq, source="provider-progress", owner="service-a", worker="worker-a"):
    return store.renew_owned_activity(
        root, record["request-id"], owner_epoch=owner, worker_id=worker, attempt_epoch=running["attempt-epoch"],
        activity_seq=seq, activity_source=source, activity_lease_seconds=LEASE)


def _check(root, record, running, owner="service-a", worker="worker-a"):
    return store.mark_watchdog_intervention_if_expired(
        root, record["request-id"], owner_epoch=owner, worker_id=worker, attempt_epoch=running["attempt-epoch"])


def test_work_with_continuing_verified_activity_outlives_the_old_ceiling(tmp_path: Path, clock: _Clock) -> None:
    record, running = _running(tmp_path)
    _renew(tmp_path, record, running, seq=1)
    seq = 1
    while clock.elapsed <= OLD_CEILING + 600:
        clock.advance(LEASE / 2)  # always inside the lease
        seq += 1
        _renew(tmp_path, record, running, seq=seq)
        checked = _check(tmp_path, record, running)
        assert checked["state"] == "running" and checked["watchdog-state"] == "active"
    assert clock.elapsed > OLD_CEILING and store.read_record(tmp_path, record["request-id"])["state"] == "running"


def test_silence_past_the_lease_is_only_a_diagnostic_and_a_new_signal_clears_it(tmp_path: Path, clock: _Clock) -> None:
    record, running = _running(tmp_path)
    _renew(tmp_path, record, running, seq=1)
    clock.advance(LEASE + 1)
    flagged = _check(tmp_path, record, running)
    assert flagged["state"] == "running" and flagged["watchdog-state"] != "active"  # suspicion, never a failure
    assert flagged["watchdog-reason"] == "activity-lease-expired-diagnostic"
    clock.advance(10)
    recovered = _renew(tmp_path, record, running, seq=2)
    assert recovered["state"] == "running" and recovered["watchdog-state"] == "active"
    assert _check(tmp_path, record, running)["watchdog-state"] == "active"


def test_a_duplicate_or_stale_sequence_never_extends_the_lease(tmp_path: Path, clock: _Clock) -> None:
    record, running = _running(tmp_path)
    first = _renew(tmp_path, record, running, seq=5)
    deadline = first["activity-lease-expires-at"]
    clock.advance(LEASE - 50)
    for replayed in (5, 4, 1):
        again = _renew(tmp_path, record, running, seq=replayed)
        assert again["activity-lease-expires-at"] == deadline and again["activity-sequence"] == first["activity-sequence"]
    clock.advance(60)  # past the original deadline: replays bought no time
    assert _check(tmp_path, record, running)["watchdog-state"] != "active"


def test_owner_heartbeats_do_not_renew_the_lease(tmp_path: Path, clock: _Clock) -> None:
    record, running = _running(tmp_path)
    first = _renew(tmp_path, record, running, seq=1)
    for step in range(2, 8):
        clock.advance(LEASE / 3)
        _renew(tmp_path, record, running, seq=step, source="worker-heartbeat")
    assert clock.elapsed > LEASE
    checked = _check(tmp_path, record, running)
    assert checked["watchdog-state"] != "active" and checked["activity-lease-expires-at"] == first["activity-lease-expires-at"]


def test_one_requests_activity_never_renews_anothers_lease(tmp_path: Path, clock: _Clock) -> None:
    quiet, quiet_run = _running(tmp_path, owner="service-a", worker="worker-a")
    busy, busy_run = _running(tmp_path, owner="service-b", worker="worker-b")
    _renew(tmp_path, quiet, quiet_run, seq=1)
    _renew(tmp_path, busy, busy_run, seq=1, owner="service-b", worker="worker-b")
    seq = 1
    while clock.elapsed < LEASE * 3:
        clock.advance(LEASE / 2)
        seq += 1
        _renew(tmp_path, busy, busy_run, seq=seq, owner="service-b", worker="worker-b")
    assert _check(tmp_path, busy, busy_run, owner="service-b", worker="worker-b")["watchdog-state"] == "active"
    assert _check(tmp_path, quiet, quiet_run)["watchdog-state"] != "active"
    with pytest.raises(AudiaGenticError):  # one request's identity cannot renew the other's lease
        _renew(tmp_path, quiet, quiet_run, seq=99, owner="service-b", worker="worker-b")
    assert _check(tmp_path, quiet, quiet_run)["watchdog-state"] != "active"


def test_a_stale_owner_epoch_or_worker_cannot_renew_or_annotate(tmp_path: Path, clock: _Clock) -> None:
    record, running = _running(tmp_path)
    _renew(tmp_path, record, running, seq=1)
    with pytest.raises(AudiaGenticError, match=_FENCED):
        _renew(tmp_path, record, running, seq=2, owner="service-old")
    with pytest.raises(AudiaGenticError, match=_FENCED):
        _renew(tmp_path, record, running, seq=2, worker="worker-other")
    clock.advance(LEASE + 1)
    with pytest.raises(AudiaGenticError, match=_FENCED):
        _check(tmp_path, record, running, owner="service-old")
    assert store.read_record(tmp_path, record["request-id"])["watchdog-state"] == "active"  # nothing was annotated


def test_lease_expiry_alone_never_produces_a_terminal_state(tmp_path: Path, clock: _Clock) -> None:
    record, running = _running(tmp_path)
    _renew(tmp_path, record, running, seq=1)
    for _ in range(12):
        clock.advance(LEASE * 4)
        checked = _check(tmp_path, record, running)
        assert checked["state"] == "running"
    final = store.read_record(tmp_path, record["request-id"])
    assert final["state"] == "running" and not final.get("error")
