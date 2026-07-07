"""Unit tests for agents_gateway_events — agents.llm.gateway.requested normalization,
rejection of malformed payloads, correlation_id/subject preservation through
to lifecycle events, and idempotent registration (AG12)."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from audiagentic.components.agents import agents_gateway_events as events
from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.components.agents.agents_api import create_profile
from audiagentic.foundation.event import get_bus, reset_bus
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state


@pytest.fixture(autouse=True)
def _fresh_event_bus():
    """The process-global event bus is not test-isolated by default —
    subscriptions and in-flight async dispatch from a previous test can leak
    into the next one. Reset and re-register cleanly around every test.

    On teardown the ORIGINAL bus instance is restored (not just reset): observer
    modules subscribe at import time, so leaving a fresh empty bus behind would
    silently drop every lifecycle observer for the rest of the session."""
    from audiagentic.foundation.event import event_bus as event_bus_mod

    saved_bus = event_bus_mod._bus_instance
    reset_bus()
    events._REGISTERED = False
    events.register()
    yield
    events._REGISTERED = False
    event_bus_mod._bus_instance = saved_bus


def _make_profile(project_root: Path, profile_id: str, provider_id: str, **params) -> None:
    create_profile(project_root, {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "model_id": "gpt-4o",
        "is_default": True,
        "params": params,
    })
    set_implementation_state(project_root, "providers", provider_id, ImplementationState(enabled=True))


def _collect(topic: str):
    """Collect every event on `topic`. Daemon worker threads from an earlier
    test can still be mid-flight when a later test's fixture resets the bus
    and subscribes fresh — a stray event from that older thread would land
    here too, so callers must filter `received` by their own request-id
    (from store.list_records(tmp_path), which is exclusive to this test)
    rather than trusting "the first event received" (this is what made
    test_requested_event_preserves_correlation_id_and_subject flaky)."""
    received = []
    done = threading.Event()

    def handler(event_type, payload, metadata):
        received.append((event_type, payload, metadata))
        done.set()

    get_bus().subscribe(topic, handler)
    return received, done


def _own_request_id(project_root: Path) -> str:
    records = store.list_records(project_root)
    assert len(records) == 1, f"expected exactly one record in {project_root}, found {len(records)}"
    return records[0]["request-id"]


def _wait_for_own_event(received: list, done: threading.Event, request_id: str, timeout: float = 5) -> tuple:
    """Poll until an event for `request_id` specifically appears in `received`,
    ignoring any stray events from other tests' leaked background threads."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for entry in received:
            if entry[1].get("request-id") == request_id:
                return entry
        done.wait(timeout=0.05)
        done.clear()
    raise AssertionError(f"no event for request-id={request_id} within {timeout}s; received={received}")


def test_register_is_idempotent():
    # The module already self-registered once at import time; register()
    # must be a no-op from here on (never touch the _REGISTERED flag directly
    # in a test — that would leave a real duplicate subscription on the
    # process-global event bus for the rest of the test session).
    subs_before = get_bus().subscription_count(events._REQUESTED_TOPIC)
    events.register()
    events.register()
    subs_after = get_bus().subscription_count(events._REQUESTED_TOPIC)
    assert subs_after == subs_before


def test_requested_event_creates_and_queues_request(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai")

    def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        return {"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "done"}

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider)

    received, done = _collect("agents.llm.completed")

    get_bus().publish("agents.llm.gateway.requested", {
        "project-root": str(tmp_path),
        "prompt-body": "do the thing",
    })

    request_id = _own_request_id(tmp_path)
    event_type, payload, metadata = _wait_for_own_event(received, done, request_id)
    assert payload["agent-profile-id"] == "default"
    assert payload["state"] == "completed"


def test_requested_event_defaults_to_async_not_blocking(tmp_path: Path, monkeypatch):
    """Publishing the event must return without waiting for a long-running request —
    async is the default per AG12's spec."""
    _make_profile(tmp_path, "default", "local-openai")
    hold = threading.Event()

    def slow_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        hold.wait(timeout=5)
        return {"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "done"}

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", slow_execute_provider)

    received, done = _collect("agents.llm.completed")

    import time
    start = time.monotonic()
    get_bus().publish("agents.llm.gateway.requested", {
        "project-root": str(tmp_path),
        "prompt-body": "do the thing",
    })
    elapsed = time.monotonic() - start
    assert elapsed < 2.0  # did not block waiting for the (5s-max) held request

    hold.set()
    assert done.wait(timeout=5)  # let the background worker finish before tmp_path teardown


def test_requested_event_missing_prompt_body_is_rejected(tmp_path: Path):
    received, done = _collect("agents.llm.rejected")
    get_bus().publish("agents.llm.gateway.requested", {"project-root": str(tmp_path)})
    assert done.wait(timeout=5)
    _, payload, _ = received[0]
    assert "prompt-body" in payload["error"]["message"]


def test_requested_event_missing_project_root_is_rejected():
    received, done = _collect("agents.llm.rejected")
    get_bus().publish("agents.llm.gateway.requested", {"prompt-body": "hi"})
    assert done.wait(timeout=5)
    _, payload, _ = received[0]
    assert "project-root" in payload["error"]["message"]


def test_requested_event_unexpected_exception_publishes_rejected_not_swallowed(tmp_path: Path, monkeypatch):
    """RV32: an unexpected (non-AudiaGenticError) exception during submission
    must still result in agents.llm.rejected — not silently vanish into
    EventBus's per-subscriber error isolation with no trace for the caller."""
    def boom(*args, **kwargs):
        raise RuntimeError("something broke")

    monkeypatch.setattr("audiagentic.components.agents.agents_gateway_api.submit_llm_request", boom)

    received, done = _collect("agents.llm.rejected")
    get_bus().publish("agents.llm.gateway.requested", {"project-root": str(tmp_path), "prompt-body": "hi"})
    assert done.wait(timeout=5)
    _, payload, _ = received[0]
    assert "unexpected error" in payload["error"]["message"]


def test_requested_event_preserves_correlation_id_and_subject(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai")

    def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        return {"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "done"}

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider)

    received, done = _collect("agents.llm.completed")

    get_bus().publish(
        "agents.llm.gateway.requested",
        {"project-root": str(tmp_path), "prompt-body": "hi"},
        metadata={"correlation_id": "corr-123", "subject": {"kind": "test"}},
    )

    request_id = _own_request_id(tmp_path)
    _, _, metadata = _wait_for_own_event(received, done, request_id)
    assert metadata.get("correlation_id") == "corr-123"
    assert metadata.get("subject") == {"kind": "test"}
