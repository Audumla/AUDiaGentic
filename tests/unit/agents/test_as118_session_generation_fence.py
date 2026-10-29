"""AS118: the session generation fence, durable retention claims and the accepted-turn clock."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _session(root: Path, *, state: str = "active") -> str:
    record = sessions_store.build_session_record(execution_profile_id="default", provider_id="local")
    record["state"] = state
    sessions_store.write_session_record(root, record)
    return record["session-id"]


def test_retention_claim_needs_a_terminal_session_and_is_idempotent_per_operation(tmp_path: Path) -> None:
    active = _session(tmp_path)
    with pytest.raises(AudiaGenticError) as raised:
        sessions_store.claim_retention(tmp_path, active, operation_id="op_1")
    assert raised.value.code == "CON-AGW-159"

    closed = _session(tmp_path, state="closed")
    claimed = sessions_store.claim_retention(tmp_path, closed, operation_id="op_1")
    assert claimed["retention-claim"]["operation-id"] == "op_1"
    assert sessions_store.claim_retention(tmp_path, closed, operation_id="op_1") == claimed
    with pytest.raises(AudiaGenticError) as raised:
        sessions_store.claim_retention(tmp_path, closed, operation_id="op_2")
    assert raised.value.code == "CON-AGW-158"


def test_only_the_claiming_operation_releases(tmp_path: Path) -> None:
    session_id = _session(tmp_path, state="closed")
    sessions_store.claim_retention(tmp_path, session_id, operation_id="op_1")
    with pytest.raises(AudiaGenticError) as raised:
        sessions_store.release_retention_claim(tmp_path, session_id, operation_id="op_2")
    assert raised.value.code == "CON-AGW-158"
    released = sessions_store.release_retention_claim(tmp_path, session_id, operation_id="op_1")
    assert "retention-claim" not in released
    # Releasing nothing is a no-op.
    assert sessions_store.release_retention_claim(tmp_path, session_id, operation_id="op_1") == released


def test_claim_survives_rereads_and_blocks_accepted_turns(tmp_path: Path) -> None:
    session_id = _session(tmp_path, state="closed")
    sessions_store.claim_retention(tmp_path, session_id, operation_id="op_1")
    # The claim is durable record state (it outlives the process), not a lock.
    assert sessions_store.read_session_record(tmp_path, session_id)["retention-claim"]["operation-id"] == "op_1"
    for refuse in (sessions_store.assert_no_retention_claim, sessions_store.record_accepted_turn):
        with pytest.raises(AudiaGenticError) as raised:
            refuse(tmp_path, session_id)
        assert raised.value.code == "CON-AGW-158"


def test_accepted_turn_stamps_only_the_accepted_turn_clock(tmp_path: Path) -> None:
    session_id = _session(tmp_path)
    before = sessions_store.read_session_record(tmp_path, session_id)
    updated = sessions_store.record_accepted_turn(tmp_path, session_id)
    assert updated["timing"]["last-accepted-turn-at"] >= before["timing"]["updated-at"]
    # No turn is counted: that stays with finalization (record_session_turn).
    assert updated["activity"] == before["activity"]
    assert sessions_store.read_session_record(tmp_path, session_id)["timing"]["last-accepted-turn-at"]


def test_claim_waits_for_a_fence_holder_and_then_sees_its_commit(tmp_path: Path) -> None:
    """Resume/admission holding the fence wins; the claim rereads the committed state."""
    session_id = _session(tmp_path, state="closed")
    holding = threading.Event()
    outcome: list[object] = []

    def admit_under_fence() -> None:
        with sessions_store.session_generation_fence(tmp_path, session_id):
            holding.set()
            time.sleep(0.3)
            sessions_store.record_accepted_turn(tmp_path, session_id)

    def claim() -> None:
        holding.wait(5)
        started = time.monotonic()
        record = sessions_store.claim_retention(tmp_path, session_id, operation_id="op_1")
        outcome.append((time.monotonic() - started, record))

    threads = [threading.Thread(target=admit_under_fence), threading.Thread(target=claim)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    waited, record = outcome[0]
    assert waited >= 0.2  # the claim waited for the fence
    assert record["timing"]["last-accepted-turn-at"]  # and committed after the accepted turn


def test_schema_accepts_and_bounds_the_new_fields(tmp_path: Path) -> None:
    session_id = _session(tmp_path, state="closed")
    record = sessions_store.read_session_record(tmp_path, session_id)
    record["retention-claim"] = {"operation-id": "op_1", "claimed-at": "2026-10-29T00:00:00Z", "extra": 1}
    with pytest.raises(AudiaGenticError):
        sessions_store.write_session_record(tmp_path, record)


def test_resume_of_a_claimed_source_is_refused_before_any_provider_call(tmp_path: Path) -> None:
    from audiagentic.components.agents.gateway.session.sessions import SessionRuntime

    calls: list[object] = []
    runtime = SessionRuntime(provider_prepare_fn=lambda *args, **kwargs: calls.append(args))
    try:
        source = _session(tmp_path, state="closed")
        sessions_store.claim_retention(tmp_path, source, operation_id="op_1")
        with pytest.raises(AudiaGenticError) as raised:
            runtime.resume_session(tmp_path, source, control_id="ctl_1")
        assert raised.value.code == "CON-AGW-158"
        assert calls == []
    finally:
        runtime.shutdown()


def _default_profile(root: Path) -> None:
    from audiagentic.components.agents.configuration.management import create_execution_profile
    from audiagentic.foundation.features.base import ImplementationState
    from audiagentic.foundation.features.state import set_implementation_state

    create_execution_profile(root, {
        "profile_id": "default", "provider_id": "local-openai", "instances": ["gpt-4o"],
        "model_id": "gpt-4o", "is_default": True, "params": {},
    })
    set_implementation_state(root, "providers", "local-openai", ImplementationState(enabled=True))


def test_continuation_admission_refuses_a_claimed_session_and_stamps_an_accepted_one(
    tmp_path: Path, monkeypatch
) -> None:
    from audiagentic.components.agents.gateway import api as gateway

    claimed = sessions_store.build_session_record(
        execution_profile_id="default", provider_id="local-openai", provider_transport_kind="provider-session")
    claimed["state"] = "closed"
    claimed["retention-claim"] = {"operation-id": "op_1", "claimed-at": "2026-10-29T00:00:00Z"}
    sessions_store.write_session_record(tmp_path, claimed)
    reached: list[str] = []

    real_admit = gateway.store.admit_record

    def admit(project_root, record, **kwargs):
        reached.append(record["request-id"])
        return real_admit(project_root, record, **kwargs)

    monkeypatch.setattr(gateway.store, "admit_record", admit)
    _default_profile(tmp_path)
    with pytest.raises(AudiaGenticError) as raised:
        gateway.submit_execution_request(tmp_path, prompt_body="next", session_id=claimed["session-id"])
    assert raised.value.code == "CON-AGW-158"
    assert reached == []  # refused under the fence, before admission

    accepted = sessions_store.build_session_record(
        execution_profile_id="default", provider_id="local-openai", provider_transport_kind="provider-session")
    sessions_store.write_session_record(tmp_path, accepted)
    gateway.submit_execution_request(tmp_path, prompt_body="next", session_id=accepted["session-id"], mode="async")
    assert len(reached) == 1
    assert sessions_store.read_session_record(tmp_path, accepted["session-id"])["timing"]["last-accepted-turn-at"]
