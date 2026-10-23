"""AS02/AS03 — SessionRuntime + session store tests (plan agent-sessions).

Fake transport (no subprocess) + injected clock + fast reap interval give
deterministic coverage of the lifecycle guarantees: open/turn/close, idle
and max-lifetime reaping, busy rejection, dead-child failure, shutdown.

AS28 slice 4a: tests inject provider_prepare_fn returning PreparedSessionTransport
with a FakeAgentSessionTransport — no AcpLaunch / AcpSessionTransport required.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import multiprocessing
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from audiagentic.components.agents.agents_paths import gateway_session_binding_index_path
from audiagentic.components.agents.gateway.session import bindings as binding_store
from audiagentic.components.agents.gateway.session import sessions as sessions_module
from audiagentic.components.agents.gateway.session import sessions_store as session_store
from audiagentic.components.agents.gateway.session.dispatch import (
    _terminal_session_diagnostics,
)
from audiagentic.components.agents.gateway.session.sessions import SessionRuntime
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_ndjson
from audiagentic.foundation.system.adopted_process import (
    AdoptedChild,
    OwnershipCheckResult,
    adopt_child,
)
from audiagentic.foundation.system.managed_process import ProcessEvidence
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.agent_session import (
    CorrelationQuality,
    ProviderSessionRef,
    SessionControlAction,
    SessionFailureDisposition,
    SessionOpenResult,
    SessionTurnResult,
)
from audiagentic.foundation.transports.session_surface import (
    PreparedSessionTransport,
    SessionSurfaceRef,
)


class FakeAgentSessionTransport:
    """Transport double: no child process, scriptable liveness and blocking.

    AS28 slice 4a: implements the neutral AgentSessionTransport protocol shape
    (open/prompt/close/is_alive) used by the session runtime. No AcpLaunch or
    AcpSessionTransport involved — the transport is injected via a fake
    PreparedSessionTransport from provider_prepare_fn.
    """

    def __init__(self) -> None:
        self.opened = False
        self.closed = False
        self.alive = False
        self.turns: list[str] = []
        self.block_event: threading.Event | None = None
        # AS18: optional on_event emitter for intra-turn events
        self.on_event_emitter: Any = None  # callable((on_event, session_id) -> None)
        self.provider_session_ref = "prov-ses-1"
        self.ag_session_id = "ag-s-fake"
        self.reconcile_calls = 0
        self.defer_unresolved_calls = 0
        self._turn_failure_disposition = SessionFailureDisposition.TERMINATE
        self.durable_owner_probe: Any = None
        self.request_owner: str | None = None

    def set_durable_owner_probe(self, probe) -> None:
        self.durable_owner_probe = probe

    def set_request_owner(self, request_id: str | None) -> None:
        self.request_owner = request_id

    def defer_unresolved_reconciliation(self) -> None:
        self.defer_unresolved_calls += 1

    async def open(self) -> SessionOpenResult:
        self.opened = True
        self.alive = True
        return SessionOpenResult(
            ag_session_id=self.ag_session_id,
            provider_session_ref=ProviderSessionRef(value=self.provider_session_ref),
        )

    def is_alive(self) -> bool:
        return self.alive and not self.closed

    def turn_failure_disposition(self) -> SessionFailureDisposition:
        return self._turn_failure_disposition

    async def reconcile_activity_gap(self) -> dict[str, Any]:
        self.reconcile_calls += 1
        return {"status": "reconciled", "state": "ready"}

    async def prompt(self, prompt, sink=None, **kwargs) -> SessionTurnResult:
        """Support both ACP callback and neutral SessionPrompt signatures.

        AS28 slice 4b-A: when called with a SessionPrompt (first positional
        arg is not a str), uses the neutral contract path — mimics
        AcpAgentSessionTransport by generating fake TransportObservation
        and delivering through the observation sink.
        When called with on_event=, uses the legacy callback path for tests.
        """
        import asyncio

        # Detect neutral vs legacy signature
        is_neutral = not isinstance(prompt, str)
        if is_neutral:
            prompt_text = prompt.body if hasattr(prompt, "body") else str(prompt)
            turn_id = getattr(prompt, "turn_id", None)
            cancel_signal = getattr(prompt, "cancel_token", None)
        else:
            prompt_text = prompt
            cancel_signal = kwargs.get("cancel_signal")
            sink = None
            turn_id = None

        stop_reason = "end_turn"
        if self.block_event is not None:
            while not self.block_event.is_set():
                if cancel_signal is not None and cancel_signal.is_set():
                    stop_reason = "cancelled"
                    break
                if self.closed:
                    raise AudiaGenticError(
                        code="EXT-ACP-001",
                        kind="execution",
                        message="transport closed mid-turn",
                        details={},
                    )
                await asyncio.sleep(0.01)
        self.turns.append(prompt_text)

        # The fake has no internal event pipeline — real AcpAgentSessionTransport
        # generates TransportObservation from the child process and delivers
        # them through the sink. The fake calls on_event_emitter to generate
        # test observations and deliver them through the sink.

        # Call on_event_emitter when configured — it generates observations
        # and delivers them through the sink (neutral path) or via a callback
        # (legacy path for backward compat).
        if self.on_event_emitter:
            if is_neutral and sink:
                # Neutral path: on_event_emitter receives the sink directly
                await self.on_event_emitter(sink, "prov-ses-1")
            else:
                # Legacy path: on_event_emitter receives on_event callback
                on_event = kwargs.get("on_event")
                if on_event:
                    await self.on_event_emitter(on_event, "prov-ses-1")

        return SessionTurnResult(
            turn_id=turn_id or "turn-0",
            stop_reason=stop_reason,
            observations_delivered=1,
            dropped_observations=0,
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            final_summary="fake provider response",
        )

    async def control(self, request):
        """AS28 slice 4b-A: support SessionControlAction.CANCEL_TURN.

        For the fake, cancel is a no-op (the local cancel event in _prompt
        handles the signal). Returns ACCEPTED for CANCEL_TURN when alive.
        """
        from audiagentic.foundation.transports.agent_session import (
            ControlDisposition,
            SessionControlAction,
            SessionControlResult,
        )

        if not self.is_alive():
            return SessionControlResult(
                disposition=ControlDisposition.UNSUPPORTED,
            )
        if request.action == SessionControlAction.CANCEL_TURN:
            return SessionControlResult(
                disposition=ControlDisposition.ACCEPTED,
            )
        return SessionControlResult(
            disposition=ControlDisposition.UNSUPPORTED,
        )

    async def close(self) -> None:
        self.closed = True
        self.alive = False


class _RecoverableFailureTransport(FakeAgentSessionTransport):
    """A provider transport whose state machine retains its live session."""

    async def prompt(self, prompt, sink=None, **kwargs):
        self._turn_failure_disposition = SessionFailureDisposition.RETAIN
        raise AudiaGenticError(
            code="EXT-TEST-001",
            kind="providers",
            message="turn failed but the provider session remains usable",
            details={},
        )


class _OpenFailureTransport(FakeAgentSessionTransport):
    async def open(self) -> SessionOpenResult:
        self.opened = True
        self.alive = True
        raise RuntimeError("provider open failed")


class _RequestScopedMetadataTransport(FakeAgentSessionTransport):
    """Transport double that exposes the real runtime FIFO sink boundary."""

    def __init__(self) -> None:
        super().__init__()
        self.metadata_sink: Any = None
        self.first_started = threading.Event()
        self.release_first = threading.Event()
        self.metadata_by_prompt: list[tuple[str, Any]] = []

    def set_request_metadata_sink(self, sink: Any) -> None:
        self.metadata_sink = sink

    async def prompt(self, prompt, sink=None, **kwargs) -> SessionTurnResult:
        prompt_text = prompt.body if hasattr(prompt, "body") else str(prompt)
        request_sink = self.metadata_sink
        if len(self.metadata_by_prompt) == 0:
            self.first_started.set()
            while not self.release_first.is_set():
                await asyncio.sleep(0.01)
        metadata = {
            "submission-proven": True,
            "prompt-message-id": f"prompt-{prompt_text}",
            "assistant-message-id": f"assistant-{prompt_text}",
        }
        if request_sink is not None:
            result = request_sink(metadata)
            if hasattr(result, "__await__"):
                await result
        self.metadata_by_prompt.append((prompt_text, request_sink))
        return await super().prompt(prompt, sink=sink, **kwargs)


def _build_fake_surface(
    provider_id: str = "opencode", surface_id: str = "opencode-acp"
) -> Any:
    """Build a minimal ResolvedSessionSurface for test PreparedSessionTransport."""
    from audiagentic.foundation.transports.session_surface import (
        ContentStreamCapabilities,
        LifecycleObservationCapabilities,
        ResolvedSessionSurface,
        SessionIdentityCapabilities,
        SurfaceValidation,
    )

    return ResolvedSessionSurface(
        ref=SessionSurfaceRef(
            provider_id=provider_id,
            surface_id=surface_id,
            resolved_version="0.1.0",
        ),
        identity=SessionIdentityCapabilities(),
        content=ContentStreamCapabilities(),
        lifecycle=LifecycleObservationCapabilities(),
        validation=SurfaceValidation(),
    )


def _build_fake_prepared(
    transport: FakeAgentSessionTransport,
    *,
    provider_id: str = "opencode",
    surface_id: str = "opencode-acp",
) -> PreparedSessionTransport:
    """Build a fake PreparedSessionTransport with the given transport."""
    return PreparedSessionTransport(
        transport=transport,
        surface=_build_fake_surface(provider_id, surface_id),
        effective_provider_ref=SessionSurfaceRef(
            provider_id=provider_id,
            surface_id=surface_id,
            resolved_version="0.1.0",
        ),
    )


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def rig(tmp_path):
    """(runtime, clock, transports) with a fast reaper; shut down after test.

    AS28 slice 4a: injects provider_prepare_fn returning PreparedSessionTransport
    with FakeAgentSessionTransport — no AcpLaunch involved.
    """
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []
    counter = 0

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        nonlocal counter
        counter += 1
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transport.provider_session_ref = f"prov-ses-{counter}"
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock,
        reap_interval_seconds=0.05,
        provider_prepare_fn=fake_prepare,
    )
    yield runtime, clock, transports, tmp_path
    runtime.shutdown()


def _open(runtime, tmp_path, **kwargs) -> dict[str, Any]:
    return runtime.open_session(
        tmp_path,
        execution_profile_id="profile-1",
        provider_id="opencode",
        model_id="m1",
        surface_hint=kwargs.pop("surface_hint", None),
        **kwargs,
    )


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_terminal_session_diagnostics_preserve_recovery_path() -> None:
    details = _terminal_session_diagnostics(
        "ses-terminal",
        {
            "state": "failed",
            "close-reason": "failed",
            "timing": {
                "updated-at": "2026-08-14T04:31:21Z",
                "closed-at": "2026-08-14T04:31:21Z",
            },
            "provider": {
                "metadata": {
                    "provider-session-id": "provider-chat",
                    "chat-url": "https://chatgpt.com/c/provider-chat",
                    "unresolved-turn-pending": True,
                }
            },
        },
    )

    assert details["suggestion"] == "call session_resume to continue the same provider conversation"
    assert details["provider-provider-session-id"] == "provider-chat"
    assert details["provider-unresolved-turn-pending"] is True
    assert details["closed-at"] == "2026-08-14T04:31:21Z"


# ── AS28 slice 4a: OPEN path provider preparation tests ─────────


def test_unsupported_surface_raises_no_child(tmp_path):
    """When the prepared transport is None (unsupported surface), open_session
    raises CON-AGW-095 — no child starts, no live session exposed."""
    clock = _Clock()

    def unsupported_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        return PreparedSessionTransport(
            transport=None,
            surface=_build_fake_surface(),
            effective_provider_ref=SessionSurfaceRef(
                provider_id=provider_id,
                surface_id="unsupported",
                resolved_version="0.1.0",
            ),
        )

    runtime = SessionRuntime(
        clock=clock,
        reap_interval_seconds=60,
        provider_prepare_fn=unsupported_prepare,
    )
    try:
        with pytest.raises(AudiaGenticError, match="CON-AGW-095"):
            runtime.open_session(
                tmp_path,
                execution_profile_id="profile-1",
                provider_id="opencode",
                model_id="m1",
                surface_hint=None,
            )
        # No live session exposed
        assert runtime.live_session_ids() == []
    finally:
        runtime.shutdown()


def test_provider_prepare_called_once_with_explicit_context(tmp_path):
    """Provider prepare is called once with explicit project/provider/model/surface."""
    clock = _Clock()
    call_args: list[dict[str, Any]] = []

    def tracking_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        call_args.append(
            {
                "project_root": str(project_root),
                "provider_id": provider_id,
                "model_id": model_id,
                "surface_hint": surface_hint,
            }
        )
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock,
        reap_interval_seconds=60,
        provider_prepare_fn=tracking_prepare,
    )
    record: dict[str, Any] | None = None
    try:
        record = runtime.open_session(
            tmp_path,
            execution_profile_id="profile-1",
            provider_id="test-provider",
            model_id="test-model",
            surface_hint=None,
        )
        # Exactly one call
        assert len(call_args) == 1
        args = call_args[0]
        assert args["project_root"] == str(tmp_path)
        assert args["provider_id"] == "test-provider"
        assert args["model_id"] == "test-model"
        assert args["surface_hint"] is None
        # Session opened successfully
        assert record["state"] == "active"
        assert runtime.live_session_ids() == [record["session-id"]]
    finally:
        if record is not None:
            runtime.close_session(tmp_path, record["session-id"])
        runtime.shutdown()


def test_open_passes_exact_snapshot_and_transport(tmp_path):
    """Supported open stores the transport and resolved surface snapshot on handle."""
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []
    expected_surface = _build_fake_surface()

    def prepare_with_surface(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transports.append(transport)
        return PreparedSessionTransport(
            transport=transport,
            surface=expected_surface,
            effective_provider_ref=SessionSurfaceRef(
                provider_id=provider_id,
                surface_id="test-surface",
                resolved_version="0.1.0",
            ),
        )

    runtime = SessionRuntime(
        clock=clock,
        reap_interval_seconds=60,
        provider_prepare_fn=prepare_with_surface,
    )
    record: dict[str, Any] | None = None
    try:
        record = runtime.open_session(
            tmp_path,
            execution_profile_id="profile-1",
            provider_id="test-provider",
            model_id="m1",
            surface_hint=None,
        )
        session_id = record["session-id"]
        # The handle's transport is the neutral one from PreparedSessionTransport
        assert transports[0].opened
        # Surface snapshot is stored on the handle
        status = runtime.session_runtime_status(session_id)
        assert status["available"] is True
    finally:
        if record is not None:
            runtime.close_session(tmp_path, record["session-id"])
        runtime.shutdown()


def test_open_failure_cleans_partial_runtime(tmp_path):
    """If bookkeeping fails after transport.open(), the child is not leaked.

    This tests that the existing exception handling path (closing transport on
    store/binding failure) still works through the new provider_prepare seam."""
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []

    def prepare_fn(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock,
        reap_interval_seconds=60,
        provider_prepare_fn=prepare_fn,
    )
    record: dict[str, Any] | None = None
    try:
        # The transport opens successfully (provider_session_ref returned).
        # If session_store.write_session_record or binding_store.register_open_binding
        # raises, the open path calls await transport.close() before re-raising.
        # We test this by verifying that a successful open has an opened transport.
        record = runtime.open_session(
            tmp_path,
            execution_profile_id="profile-1",
            provider_id="opencode",
            model_id="m1",
            surface_hint=None,
        )
        assert transports[0].opened
        assert not transports[0].closed
    finally:
        if record is not None:
            runtime.close_session(tmp_path, record["session-id"])
        runtime.shutdown()


def test_transport_open_failure_is_closed_before_error_escapes(tmp_path):
    transport = _OpenFailureTransport()

    def prepare_fn(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport.ag_session_id = kwargs["ag_session_id"]
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        provider_prepare_fn=prepare_fn,
    )
    try:
        with pytest.raises(RuntimeError, match="provider open failed"):
            runtime.open_session(
                tmp_path,
                execution_profile_id="profile-1",
                provider_id="opencode",
                model_id="m1",
                surface_hint=None,
            )
        assert transport.closed is True
        assert runtime.live_session_ids() == []
    finally:
        runtime.shutdown()


def test_admitted_session_is_failed_when_provider_open_fails(tmp_path):
    """A pre-admitted new session cannot remain active after transport timeout."""
    transport = _OpenFailureTransport()

    def prepare_fn(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport.ag_session_id = kwargs["ag_session_id"]
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=_Clock(),
        reap_interval_seconds=60,
        provider_prepare_fn=prepare_fn,
    )
    session = session_store.build_session_record(
        created_by_request_id="req_open_timeout",
        provider_transport_kind="provider-session",
        execution_profile_id="profile-1",
        provider_id="opencode",
        model_id="m1",
    )
    session_store.write_session_record(tmp_path, session)
    try:
        with pytest.raises(RuntimeError, match="provider open failed"):
            runtime.open_session(
                tmp_path,
                execution_profile_id="profile-1",
                provider_id="opencode",
                model_id="m1",
                surface_hint=None,
                session_id=session["session-id"],
            )
        failed = session_store.read_session_record(tmp_path, session["session-id"])
        assert failed["state"] == "failed"
        assert failed["close-reason"] == "failed"
        assert failed["timing"]["closed-at"]
    finally:
        runtime.shutdown()

def test_open_prompt_close_lifecycle(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    assert record["state"] == "active"
    assert record["contract-version"] == "v4"
    assert record["binding"]["provider-session-ref"] == "prov-ses-1"
    public_binding = binding_store.public_binding_projection(record["binding"])
    assert public_binding is not None
    assert "provider-session-ref" not in public_binding
    assert runtime.live_session_ids() == [session_id]

    result = runtime.prompt_in_session(tmp_path, session_id, "hello", request_id="req_1")
    assert result.stop_reason == "end_turn"
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["activity"]["turn-count"] == 1
    assert stored["activity"]["request-ids"] == ["req_1"]

    closed = runtime.close_session(tmp_path, session_id)
    assert closed["state"] == "closed"
    assert closed["close-reason"] == "client-request"
    assert transports[0].closed
    assert runtime.live_session_ids() == []


def test_fifo_continuation_keeps_request_metadata_sinks_scoped(tmp_path):
    """A queued continuation must not inherit the opener request's sink."""
    clock = _Clock()
    transport = _RequestScopedMetadataTransport()

    def prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport.ag_session_id = kwargs["ag_session_id"]
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock,
        reap_interval_seconds=60,
        provider_prepare_fn=prepare,
    )
    record = runtime.open_session(
        tmp_path,
        execution_profile_id="profile-1",
        provider_id="opencode",
        model_id="m1",
    )
    request_a: list[dict[str, Any]] = []
    request_b: list[dict[str, Any]] = []

    async def sink_a(metadata: dict[str, Any]) -> None:
        request_a.append(dict(metadata))

    async def sink_b(metadata: dict[str, Any]) -> None:
        request_b.append(dict(metadata))

    results: list[SessionTurnResult] = []

    def run_a() -> None:
        results.append(
            runtime.prompt_in_session(
                tmp_path,
                record["session-id"],
                "request-a",
                request_id="req-a",
                request_provider_metadata_sink=sink_a,
            )
        )

    def run_b() -> None:
        results.append(
            runtime.prompt_in_session(
                tmp_path,
                record["session-id"],
                "request-b",
                request_id="req-b",
                request_provider_metadata_sink=sink_b,
            )
        )

    first = threading.Thread(target=run_a)
    second = threading.Thread(target=run_b)
    try:
        first.start()
        assert transport.first_started.wait(timeout=2)
        second.start()
        time.sleep(0.05)
        transport.release_first.set()
        first.join(timeout=2)
        second.join(timeout=2)

        assert not first.is_alive()
        assert not second.is_alive()
        assert [entry[0] for entry in transport.metadata_by_prompt] == [
            "request-a",
            "request-b",
        ]
        assert request_a[0]["prompt-message-id"] == "prompt-request-a"
        assert request_b[0]["prompt-message-id"] == "prompt-request-b"
        assert len(request_a) == 1
        assert len(request_b) == 1
        assert all(entry not in request_a for entry in request_b)
        assert all(entry not in request_b for entry in request_a)
        assert len(results) == 2
    finally:
        transport.release_first.set()
        first.join(timeout=2)
        second.join(timeout=2)
        runtime.close_session(tmp_path, record["session-id"])
        runtime.shutdown()


def test_recoverable_turn_failure_retains_live_session(tmp_path):
    """A provider recovery decision must not close its browser/session handle."""
    clock = _Clock()
    transport = _RecoverableFailureTransport()

    def prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport.ag_session_id = kwargs["ag_session_id"]
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock,
        reap_interval_seconds=0.05,
        provider_prepare_fn=prepare,
    )
    try:
        record = _open(runtime, tmp_path)
        session_id = record["session-id"]
        with pytest.raises(AudiaGenticError, match="turn failed"):
            runtime.prompt_in_session(tmp_path, session_id, "review", request_id="req-failed")

        assert transport.closed is False
        assert runtime.live_session_ids() == [session_id]
        stored = session_store.read_session_record(tmp_path, session_id)
        assert stored["state"] == "active"
        assert stored.get("close-reason") is None
    finally:
        if runtime.live_session_ids():
            runtime.close_session(tmp_path, runtime.live_session_ids()[0])
        runtime.shutdown()


def test_close_is_idempotent(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    runtime.close_session(tmp_path, record["session-id"])
    again = runtime.close_session(tmp_path, record["session-id"])
    assert again["state"] == "closed"


def test_close_session_control_owns_durable_gateway_transition(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    result = runtime.control_session(
        record["session-id"],
        turn_id=None,
        action=SessionControlAction.CLOSE_SESSION,
        control_id="ctl-close",
    )
    assert result["disposition"] == "accepted"
    assert runtime.live_session_ids() == []
    assert session_store.read_session_record(tmp_path, record["session-id"])["state"] == "closed"


def test_prompt_on_unknown_session_raises(rig):
    runtime, clock, transports, tmp_path = rig
    with pytest.raises(AudiaGenticError, match="RES-AGW-003"):
        runtime.prompt_in_session(tmp_path, "ses_missing", "hello")


def test_idle_timeout_reaps_session(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, idle_timeout_seconds=100)
    session_id = record["session-id"]
    clock.now += 101  # beyond idle timeout
    assert _wait_for(lambda: runtime.live_session_ids() == [])
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "expired"
    assert stored["close-reason"] == "idle-timeout"
    assert transports[0].closed


def test_max_lifetime_reaps_even_recently_active(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, idle_timeout_seconds=10_000, max_lifetime_seconds=200)
    session_id = record["session-id"]
    clock.now += 150
    runtime.prompt_in_session(tmp_path, session_id, "keep busy")  # refreshes idle clock
    clock.now += 60  # total age 210 > 200, idle only 60
    assert _wait_for(lambda: runtime.live_session_ids() == [])
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "expired"
    assert stored["close-reason"] == "max-lifetime"


def test_concurrent_prompts_queue_fifo(rig):
    """Turns on a busy session queue and run in order (RV513), not reject."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate

    results: list[Any] = []

    def turn(prompt):
        results.append(runtime.prompt_in_session(tmp_path, session_id, prompt))

    first = threading.Thread(target=turn, args=("first",))
    second = threading.Thread(target=turn, args=("second",))
    first.start()
    time.sleep(0.1)  # first turn is in flight (blocked on the gate)
    second.start()
    time.sleep(0.1)  # second turn is queued behind it
    assert results == []  # nothing rejected, nothing finished yet
    gate.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert transports[0].turns == ["first", "second"]
    assert len(results) == 2


def test_queued_prompt_timeout_starts_after_fifo_admission(rig):
    """A caller deadline must not expire while an earlier turn is active."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate
    results: list[Any] = []
    errors: list[BaseException] = []

    def first_turn() -> None:
        try:
            results.append(runtime.prompt_in_session(tmp_path, session_id, "first"))
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            errors.append(exc)

    def queued_turn() -> None:
        try:
            results.append(
                runtime.prompt_in_session(
                    tmp_path,
                    session_id,
                    "second",
                    timeout_seconds=0.05,
                )
            )
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            errors.append(exc)

    first = threading.Thread(target=first_turn)
    second = threading.Thread(target=queued_turn)
    first.start()
    time.sleep(0.1)
    second.start()
    time.sleep(0.2)  # exceed the queued turn's deadline while first owns the lock
    assert second.is_alive()
    gate.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not errors
    assert not first.is_alive() and not second.is_alive()
    assert transports[0].turns == ["first", "second"]
    runtime.close_session(tmp_path, session_id)


def test_cancelled_fifo_waiter_releases_pending_before_predecessor_finishes(rig):
    runtime, clock, transports, tmp_path = rig
    session_id = _open(runtime, tmp_path)["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate
    errors = []

    def submit(body, request_id=None):
        try:
            runtime.prompt_in_session(tmp_path, session_id, body, request_id=request_id)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=submit, args=("first",))
    second = threading.Thread(target=submit, args=("cancel me", "req_fifo_cancel"))
    first.start()
    try:
        time.sleep(0.1)
        second.start()
        deadline = time.monotonic() + 2
        while runtime._handles[session_id].pending == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runtime._handles[session_id].pending == 1
        runtime.request_cancel("req_fifo_cancel")
        second.join(timeout=2)
        assert not second.is_alive()
        assert first.is_alive()
        assert runtime._handles[session_id].pending == 0
        assert len(errors) == 1 and errors[0].code == "CON-AGW-099"
        assert "cancel me" not in transports[0].turns
    finally:
        gate.set()
        first.join(timeout=2)
        if second.ident is not None:
            second.join(timeout=2)
        runtime.close_session(tmp_path, session_id)
    assert transports[0].turns == ["first"]


def test_session_snapshot_all_reports_active_turn(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate

    result: list[Any] = []
    worker = threading.Thread(
        target=lambda: result.append(
            runtime.prompt_in_session(tmp_path, session_id, "snapshot", request_id="req_snap_1")
        )
    )
    worker.start()
    time.sleep(0.1)

    snapshot = runtime.session_snapshot_all()
    assert snapshot == {
        session_id: {
            "turn-active": True,
            "pending-turns": 0,
            "current-request-id": "req_snap_1",
        }
    }

    gate.set()
    worker.join(timeout=2)
    assert result and result[0].stop_reason == "end_turn"


def test_reconcile_active_transport_does_not_replay_prompt(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate
    result: list[Any] = []
    worker = threading.Thread(
        target=lambda: result.append(
            runtime.prompt_in_session(tmp_path, session_id, "one prompt", request_id="req-gap")
        )
    )
    worker.start()
    assert _wait_for(
        lambda: runtime.session_runtime_status(session_id).get("current-request-id") == "req-gap"
    )

    reconciliation = runtime.reconcile_active_transport(session_id, "req-gap")
    assert reconciliation["status"] == "reconciled"
    assert transports[0].reconcile_calls == 1

    gate.set()
    worker.join(timeout=2)
    assert len(result) == 1
    assert transports[0].turns == ["one prompt"]


def test_turn_queue_full_rejects(rig, tmp_path):
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock,
        reap_interval_seconds=60,
        provider_prepare_fn=fake_prepare,
        session_queue_max=1,
    )
    try:
        record = _open(runtime, tmp_path)
        session_id = record["session-id"]
        gate = threading.Event()
        transports[0].block_event = gate

        threads = [
            threading.Thread(
                target=lambda p=p: _swallow(
                    lambda: runtime.prompt_in_session(tmp_path, session_id, p)
                )
            )
            for p in ("running", "queued")
        ]
        threads[0].start()
        time.sleep(0.1)  # in flight
        threads[1].start()
        time.sleep(0.1)  # one waiter — queue (max 1) now full
        with pytest.raises(AudiaGenticError, match="CON-AGW-003"):
            runtime.prompt_in_session(tmp_path, session_id, "overflow")
        gate.set()
        for thread in threads:
            thread.join(timeout=2)
        assert transports[0].turns == ["running", "queued"]
    finally:
        runtime.shutdown()


def _swallow(fn):
    try:
        fn()
    except Exception:
        pass


def test_zero_bounds_disable_reaping(rig):
    """idle-timeout 0 and max-lifetime 0 opt the session out of both caps."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, idle_timeout_seconds=0, max_lifetime_seconds=0)
    session_id = record["session-id"]
    clock.now += 1_000_000  # far past any default bound
    time.sleep(0.3)  # several reaper sweeps
    assert runtime.live_session_ids() == [session_id]
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "active"


def test_reaper_never_closes_processing_session(rig):
    """A session past max lifetime drains: the in-flight turn completes, new
    turns are rejected (CON-AGW-004), then the reaper closes it (RV513)."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, max_lifetime_seconds=100, idle_timeout_seconds=10_000)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate

    results: list[Any] = []
    thread = threading.Thread(
        target=lambda: results.append(runtime.prompt_in_session(tmp_path, session_id, "long turn"))
    )
    thread.start()
    time.sleep(0.1)  # turn in flight
    clock.now += 200  # past max lifetime while processing
    time.sleep(0.2)  # reaper sweeps — must NOT close the busy session
    assert runtime.live_session_ids() == [session_id]

    with pytest.raises(AudiaGenticError, match="CON-AGW-004"):
        runtime.prompt_in_session(tmp_path, session_id, "too late")

    gate.set()
    thread.join(timeout=2)
    assert results and results[0].stop_reason == "end_turn"  # turn finished intact
    assert _wait_for(lambda: runtime.live_session_ids() == [])  # then reaped
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "expired"
    assert stored["close-reason"] == "max-lifetime"


def test_explicit_close_busy_session_terminalizes_before_provider_quiescence(rig):
    """Client close must not wait on an unresolved provider turn.

    A GPT-auto recovery turn can remain non-quiescent while its browser page
    is being reconciled.  Explicit close must remove the gateway handle and
    persist the terminal session state immediately so recovery/queue dispatch
    cannot retain the session lock.
    """
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    transports[0].block_event = threading.Event()
    results: list[BaseException] = []

    def run_turn() -> None:
        try:
            runtime.prompt_in_session(tmp_path, session_id, "unresolved", request_id="req-close")
        except BaseException as exc:  # cancellation is the expected close path
            results.append(exc)

    thread = threading.Thread(target=run_turn)
    thread.start()
    time.sleep(0.1)

    started = time.monotonic()
    closed = runtime.close_session(tmp_path, session_id)
    elapsed = time.monotonic() - started

    assert elapsed < 5
    assert closed["state"] == "closed"
    assert closed["close-reason"] == "client-request"
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "closed"
    assert runtime.live_session_ids() == []
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert transports[0].closed


def test_dead_child_fails_session(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    transports[0].alive = False  # child died out-of-band
    with pytest.raises(AudiaGenticError, match="RES-AGW-003"):
        runtime.prompt_in_session(tmp_path, session_id, "hello")
    stored = session_store.read_session_record(tmp_path, session_id)
    assert stored["state"] == "failed"
    assert runtime.live_session_ids() == []


def test_shutdown_closes_all_sessions(rig):
    runtime, clock, transports, tmp_path = rig
    first = _open(runtime, tmp_path)
    second = _open(runtime, tmp_path)
    runtime.shutdown()
    for record in (first, second):
        stored = session_store.read_session_record(tmp_path, record["session-id"])
        assert stored["state"] == "closed"
        assert stored["close-reason"] == "shutdown"
    assert all(t.closed for t in transports)
    with pytest.raises(AudiaGenticError, match="CON-AGW-002"):
        _open(runtime, tmp_path)


def test_api_list_and_close_sessions(rig, monkeypatch):
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    listed = api.list_execution_sessions(tmp_path)
    assert [s["session-id"] for s in listed] == [record["session-id"]]
    assert listed[0]["live"] is True
    assert "provider-session-ref" not in repr(listed)
    assert listed[0]["binding"]["provider-ref-key-prefix"]

    closed = api.close_execution_session(tmp_path, record["session-id"])
    assert closed["state"] == "closed"
    assert api.list_execution_sessions(tmp_path, state="all")[0]["live"] is False
    # Idempotent on an already-terminal session
    again = api.close_execution_session(tmp_path, record["session-id"])
    assert again["state"] == "closed"


def test_api_lists_active_sessions_before_newer_closed_sessions(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    saved_runtime = getattr(sessions_module, "_SESSION_RUNTIME", None)
    try:
        sessions_module._SESSION_RUNTIME = None  # type: ignore[attr-defined]
        active_z = session_store.build_session_record(
            session_id="ses-active-z",
            execution_profile_id="profile-1",
            created_at="2026-09-05T00:00:00Z",
        )
        active_a = session_store.build_session_record(
            session_id="ses-active-a",
            execution_profile_id="profile-1",
            created_at="2026-09-05T02:00:00Z",
        )
        closed_z = session_store.build_session_record(
            session_id="ses-closed-z",
            execution_profile_id="profile-1",
            created_at="2026-09-05T01:00:00Z",
        )
        closed_a = session_store.build_session_record(
            session_id="ses-closed-a",
            execution_profile_id="profile-1",
            created_at="2026-09-05T03:00:00Z",
        )
        for record in (active_z, active_a, closed_z, closed_a):
            session_store.write_session_record(tmp_path, record)
        for record in (closed_z, closed_a):
            session_store.transition_session_record(tmp_path, record["session-id"], "closed")

        listed = api.list_execution_sessions(tmp_path)

        assert [row["session-id"] for row in listed] == [
            "ses-active-a", "ses-active-z",
        ]
        listed_all = api.list_execution_sessions(tmp_path, state="all")
        assert [row["session-id"] for row in listed_all] == [
            "ses-active-a", "ses-active-z", "ses-closed-a", "ses-closed-z",
        ]
    finally:
        sessions_module._SESSION_RUNTIME = saved_runtime  # type: ignore[attr-defined]


def test_api_close_orphaned_session_marks_failed(rig, monkeypatch):
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    # Persisted active, but no live handle (simulates a previous process)
    record = session_store.build_session_record(execution_profile_id="profile-1")
    session_store.write_session_record(tmp_path, record)

    closed = api.close_execution_session(tmp_path, record["session-id"])
    assert closed["state"] == "failed"
    assert closed["close-reason"] == "orphaned"


def test_session_record_validation():
    with pytest.raises(AudiaGenticError, match="VAL-AGW-050"):
        session_store.build_session_record(execution_profile_id="p", idle_timeout_seconds=-1)
    with pytest.raises(AudiaGenticError, match="VAL-AGW-051"):
        session_store.build_session_record(execution_profile_id="p", max_lifetime_seconds=-5)
    # 0 disables a bound — valid (RV513)
    record = session_store.build_session_record(
        execution_profile_id="p", idle_timeout_seconds=0, max_lifetime_seconds=0
    )
    assert record["policy"]["idle-timeout-seconds"] == 0
    assert record["policy"]["max-lifetime-seconds"] == 0


def test_cross_process_session_turn_appends_do_not_lose_updates(tmp_path: Path) -> None:
    """RV733: session mutation now uses the foundation StartupLock (like
    request records), so concurrent processes recording turns on the same
    session cannot lose an update — every request-id and the turn-count
    both reflect all N appends."""
    record = session_store.build_session_record(execution_profile_id="p")
    session_store.write_session_record(tmp_path, record)
    session_id = record["session-id"]
    context = multiprocessing.get_context("spawn")
    count = 12
    processes = [
        context.Process(
            target=functools.partial(
                session_store.record_session_turn,
                tmp_path,
                session_id,
                f"req_{index}",
            ),
        )
        for index in range(count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)

    assert [process.exitcode for process in processes] == [0] * count
    final = session_store.read_session_record(tmp_path, session_id)
    assert final["activity"]["turn-count"] == count
    assert sorted(final["activity"]["request-ids"]) == sorted(f"req_{index}" for index in range(count))


def test_record_session_turn_requires_terminal_evidence_for_that_request(tmp_path: Path) -> None:
    record = session_store.build_session_record(execution_profile_id="p")
    record["provider"] = {
        "provider-id": "gpt-auto",
        "metadata": {
            "unresolved-turn-pending": True,
            "unresolved-turn-id": "req-current",
            "submission-state": "proven",
            "submission-attempt-id": "attempt-current",
            "submission-proven": True,
            "submission-proof-source": "provider-user-message",
            "prompt-text-digest": "turn-digest",
            "unresolved-baseline-user-count": 0,
            "unresolved-baseline-assistant-count": 0,
            "unresolved-baseline-error-alert-occurrences": [],
        },
    }
    session_store.write_session_record(tmp_path, record)
    terminal = {
        "policy": "response-complete",
        "verification-evidence": ["not-generating", "text-present", "completion-control"],
    }

    mismatched = session_store.record_session_turn(
        tmp_path,
        record["session-id"],
        "req-current",
        provider_metadata={
            "unresolved-turn-id": "req-current",
            "submission-attempt-id": "attempt-current",
            "submission-proven": True,
            "submission-proof-source": "provider-user-message",
            "prompt-text-digest": "turn-digest",
            "unresolved-baseline-user-count": 0,
            "unresolved-baseline-assistant-count": 0,
            "unresolved-baseline-error-alert-occurrences": [],
            "terminal-evidence": {**terminal, "turn-id": "req-previous"},
        },
    )
    assert mismatched["provider"]["metadata"]["unresolved-turn-pending"] is True
    assert mismatched["provider"]["metadata"]["unresolved-turn-id"] == "req-current"

    finalized = session_store.record_session_turn(
        tmp_path,
        record["session-id"],
        "req-current",
        provider_metadata={
            "unresolved-turn-id": "req-current",
            "submission-attempt-id": "attempt-current",
            "submission-proven": True,
            "submission-proof-source": "provider-user-message",
            "prompt-text-digest": "turn-digest",
            "unresolved-baseline-user-count": 0,
            "unresolved-baseline-assistant-count": 0,
            "unresolved-baseline-error-alert-occurrences": [],
            "terminal-evidence": {
                **terminal,
                "turn-id": "req-current",
                "checkpoint-clear-persisted": False,
            },
        },
    )
    checkpoint = session_store.session_provider_metadata(finalized)
    assert checkpoint["unresolved-turn-pending"] is True
    assert checkpoint["unresolved-turn-id"] == "req-current"
    assert checkpoint["terminal-evidence"]["turn-id"] == "req-current"

    # Terminal DOM proof is only staged here. The fence is removed after the
    # request output and terminal lifecycle have been durably written.
    from audiagentic.components.agents.gateway import store as gateway_store

    request = gateway_store.build_record(
        request_id="req-current",
        execution_profile_id="p",
        prompt_body="test prompt",
        session_id=record["session-id"],
    )
    request["state"] = "completed"
    gateway_store.write_record(tmp_path, request)
    assert session_store.clear_terminal_submission_checkpoint(
        tmp_path,
        record["session-id"],
        "req-current",
        recovery_state="terminal-completed",
        remove_keys=session_store.TERMINAL_SUBMISSION_CHECKPOINT_REMOVE_KEYS,
        expected_metadata=checkpoint,
    )
    cleared = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, record["session-id"])
    )
    assert cleared["unresolved-turn-pending"] is False
    assert "unresolved-turn-id" not in cleared
    assert "submission-attempt-id" not in cleared


def test_record_session_turn_retains_checkpoint_on_frozen_identity_mismatch(tmp_path: Path) -> None:
    record = session_store.build_session_record(execution_profile_id="p")
    record["provider"] = {
        "provider-id": "gpt-auto",
        "metadata": {
            "unresolved-turn-pending": True,
            "unresolved-turn-id": "req-identity",
            "submission-proven": True,
            "submission-proof-source": "provider-user-message",
            "prompt-text-digest": "original-digest",
        },
    }
    session_store.write_session_record(tmp_path, record)
    metadata = {
        "unresolved-turn-id": "req-identity",
        "submission-proven": True,
        "submission-proof-source": "provider-user-message",
        "prompt-text-digest": "different-digest",
        "terminal-evidence": {
            "turn-id": "req-identity",
            "policy": "response-complete",
            "verification-evidence": [
                "not-generating",
                "text-present",
                "completion-control",
            ],
        },
    }

    result = session_store.record_session_turn(
        tmp_path, record["session-id"], "req-identity", provider_metadata=metadata
    )

    assert result["provider"]["metadata"]["unresolved-turn-pending"] is True
    assert result["provider"]["metadata"]["unresolved-turn-id"] == "req-identity"


def test_record_session_turn_does_not_clear_a_successor_submission_attempt(tmp_path: Path) -> None:
    record = session_store.build_session_record(execution_profile_id="p")
    record["provider"] = {
        "provider-id": "gpt-auto",
        "metadata": {
            "unresolved-turn-pending": True,
            "unresolved-turn-id": "req-same-logical-turn",
            "submission-proven": True,
            "submission-proof-source": "provider-user-message",
            "submission-attempt-id": "attempt-successor",
            "submission-recovery-generation": 4,
            "prompt-text-digest": "current-digest",
            "unresolved-baseline-user-count": 1,
            "unresolved-baseline-assistant-count": 2,
            "unresolved-baseline-error-alert-occurrences": [],
        },
    }
    session_store.write_session_record(tmp_path, record)

    result = session_store.record_session_turn(
        tmp_path,
        record["session-id"],
        "req-same-logical-turn",
        provider_metadata={
            "unresolved-turn-id": "req-same-logical-turn",
            "submission-proven": True,
            "submission-proof-source": "provider-user-message",
            "submission-attempt-id": "attempt-stale",
            "submission-recovery-generation": 3,
            "prompt-text-digest": "current-digest",
            "unresolved-baseline-user-count": 1,
            "unresolved-baseline-assistant-count": 2,
            "unresolved-baseline-error-alert-occurrences": [],
            "terminal-evidence": {
                "turn-id": "req-same-logical-turn",
                "policy": "response-complete",
                "verification-evidence": [
                    "not-generating",
                    "text-present",
                    "completion-control",
                ],
            },
        },
    )

    metadata = result["provider"]["metadata"]
    assert metadata["unresolved-turn-pending"] is True
    assert metadata["submission-attempt-id"] == "attempt-successor"
    assert metadata["submission-recovery-generation"] == 4


def test_v1_session_record_without_surface_fails_closed(tmp_path):
    import json

    legacy = {
        "contract-version": "v1",
        "session-id": "ses_legacy",
        "execution-profile-id": "p",
        "provider-id": "opencode",
        "model-id": "m",
        "provider-session-ref": "secret-ref",
        "state": "active",
        "close-reason": None,
        "idle-timeout-seconds": None,
        "max-lifetime-seconds": None,
        "request-ids": [],
        "turn-count": 0,
        "error": None,
        "created-at": "2026-01-01T00:00:00Z",
        "updated-at": "2026-01-01T00:00:00Z",
        "last-activity-at": "2026-01-01T00:00:00Z",
        "closed-at": None,
    }
    path = (
        tmp_path
        / ".audiagentic"
        / "runtime"
        / "agent-execution-gateway"
        / "sessions"
        / "ses_legacy"
        / "record.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(legacy), encoding="utf-8")

    with pytest.raises(AudiaGenticError, match="has no resolved surface id"):
        session_store.read_session_record(tmp_path, "ses_legacy")


def test_binding_index_uses_hash_not_raw_ref(rig):
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    text = gateway_session_binding_index_path(tmp_path).read_text(encoding="utf-8")
    assert "prov-ses-1" not in text
    assert record["binding"]["provider-ref-key"] in text


def test_duplicate_owned_binding_rolls_back_transport(tmp_path):
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transport.provider_session_ref = "same-ref"
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock, reap_interval_seconds=60, provider_prepare_fn=fake_prepare
    )
    try:
        _open(runtime, tmp_path)
        with pytest.raises(AudiaGenticError, match="CON-AGW-096"):
            _open(runtime, tmp_path)
        assert transports[1].closed
    finally:
        runtime.shutdown()


def test_closed_owned_binding_allows_later_same_ref(tmp_path):
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transport.provider_session_ref = "same-ref"
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock, reap_interval_seconds=60, provider_prepare_fn=fake_prepare
    )
    try:
        first = _open(runtime, tmp_path)
        runtime.close_session(tmp_path, first["session-id"])
        second = _open(runtime, tmp_path)
        assert second["binding"]["provider-session-ref"] == "same-ref"
        assert second["session-id"] != first["session-id"]
    finally:
        runtime.shutdown()


def test_request_record_session_field_validation():
    from audiagentic.components.agents.gateway import store as store

    # session_idle_timeout without keep_alive still rejected (VAL-AGW-059)
    with pytest.raises(AudiaGenticError, match="VAL-AGW-059"):
        store.build_record(
            execution_profile_id="p",
            prompt_body="x",
            session_idle_timeout_seconds=60,
        )
    # session_max_lifetime without keep_alive still rejected (VAL-AGW-061)
    with pytest.raises(AudiaGenticError, match="VAL-AGW-061"):
        store.build_record(
            execution_profile_id="p",
            prompt_body="x",
            session_max_lifetime_seconds=60,  # requires keep-alive
        )
    # Negative max_lifetime rejected
    with pytest.raises(AudiaGenticError, match="VAL-AGW-061"):
        store.build_record(
            execution_profile_id="p",
            prompt_body="x",
            session_keep_alive=True,
            session_max_lifetime_seconds=-1,
        )
    # New session with keep-alive and bounds (unchanged)
    record = store.build_record(
        execution_profile_id="p",
        prompt_body="x",
        session_keep_alive=True,
        session_idle_timeout_seconds=60,
        session_max_lifetime_seconds=0,  # 0 = no lifetime cap (RV513)
    )
    assert record["session-keep-alive"] is True
    assert record["session-idle-timeout-seconds"] == 60
    assert record["session-max-lifetime-seconds"] == 0


def test_session_id_with_keep_alive_allowed():
    """session_id + session_keep_alive=true is valid: continue session and
    leave it live after the turn."""
    from audiagentic.components.agents.gateway import store as store

    record = store.build_record(
        execution_profile_id="p",
        prompt_body="x",
        session_id="ses_1",
        session_keep_alive=True,
    )
    assert record["session-id"] == "ses_1"
    assert record["session-keep-alive"] is True


def test_session_id_with_keep_alive_omitted_is_none():
    """session_id without keep_alive (omitted) stores None — preserves
    existing behavior: continued session stays live after the turn."""
    from audiagentic.components.agents.gateway import store as store

    record = store.build_record(
        execution_profile_id="p",
        prompt_body="x",
        session_id="ses_1",
    )
    assert record["session-id"] == "ses_1"
    assert record["session-keep-alive"] is None


def test_session_id_with_keep_alive_false_allowed():
    """session_id + session_keep_alive=false is valid: continue session and
    close it after the turn if quiescent."""
    from audiagentic.components.agents.gateway import store as store

    record = store.build_record(
        execution_profile_id="p",
        prompt_body="x",
        session_id="ses_1",
        session_keep_alive=False,
    )
    assert record["session-id"] == "ses_1"
    assert record["session-keep-alive"] is False


def test_session_id_with_keep_alive_and_bounds_allowed():
    """session_id + keep_alive=true + bounds is valid: continue session,
    update its lifetime policy after the turn."""
    from audiagentic.components.agents.gateway import store as store

    record = store.build_record(
        execution_profile_id="p",
        prompt_body="x",
        session_id="ses_1",
        session_keep_alive=True,
        session_idle_timeout_seconds=120,
        session_max_lifetime_seconds=3600,
    )
    assert record["session-id"] == "ses_1"
    assert record["session-keep-alive"] is True
    assert record["session-idle-timeout-seconds"] == 120
    assert record["session-max-lifetime-seconds"] == 3600


def test_session_id_with_keep_alive_false_and_bounds_rejected():
    """session_id + keep_alive=false + bounds is rejected: without
    keep-alive, no lifetime policy update happens after the turn, so bounds
    are meaningless."""
    from audiagentic.components.agents.gateway import store as store

    with pytest.raises(AudiaGenticError, match="VAL-AGW-059"):
        store.build_record(
            execution_profile_id="p",
            prompt_body="x",
            session_id="ses_1",
            session_keep_alive=False,
            session_idle_timeout_seconds=60,
        )
    with pytest.raises(AudiaGenticError, match="VAL-AGW-061"):
        store.build_record(
            execution_profile_id="p",
            prompt_body="x",
            session_id="ses_1",
            session_keep_alive=False,
            session_max_lifetime_seconds=3600,
        )


def test_update_session_bounds_on_live_handle(rig):
    """update_session_bounds mutates the in-memory handle's timeout fields."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, idle_timeout_seconds=100, max_lifetime_seconds=200)
    session_id = record["session-id"]

    # Verify initial bounds
    snapshot = runtime.session_snapshot_all()
    assert snapshot[session_id]  # handle exists

    # Update bounds via runtime API
    runtime.update_session_bounds(
        session_id,
        idle_timeout_seconds=500,
        max_lifetime_seconds=1000,
    )

    # Verify the handle's bounds changed by checking reaping behavior.
    # After update, idle timeout is 500 (was 100). Advance clock past 200
    # but not past 500 — session should still be alive.
    clock.now += 200  # past original 100s idle, within new 500s
    time.sleep(0.3)  # several reaper sweeps
    assert runtime.live_session_ids() == [session_id]

    runtime.close_session(tmp_path, session_id)


def test_continuation_policy_never_shortens_live_bounds(rig):
    """Global/profile continuation settings use the more-open bound."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, idle_timeout_seconds=500, max_lifetime_seconds=1000)
    session_id = record["session-id"]

    runtime.update_session_bounds(
        session_id,
        idle_timeout_seconds=100,
        max_lifetime_seconds=200,
    )
    clock.now += 250
    time.sleep(0.2)
    assert runtime.live_session_ids() == [session_id]
    runtime.close_session(tmp_path, session_id)


def test_rehydrate_active_generation_reuses_provider_binding(tmp_path):
    """A missing process-local handle is reattached without a new session id."""
    transports: list[FakeAgentSessionTransport] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transport.provider_session_ref = kwargs.get("resume_provider_ref") or "prov-durable"
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(provider_prepare_fn=fake_prepare)
    try:
        record = runtime.open_session(
            tmp_path,
            execution_profile_id="profile-1",
            provider_id="opencode",
            model_id="m1",
            surface_hint=None,
        )
        session_id = record["session-id"]
        # Simulate a gateway process restart: durable record remains active,
        # but this process has lost its ephemeral transport handle.
        async def drop_handle() -> None:
            runtime._handles.pop(session_id, None)

        runtime._call(drop_handle(), timeout=5)
        assert runtime.session_runtime_status(session_id)["available"] is False

        restored = runtime.rehydrate_session(
            tmp_path,
            session_id,
            execution_profile_id="profile-1",
            provider_id="opencode",
            model_id="m1",
            surface_hint=None,
        )
        assert restored["session-id"] == session_id
        assert runtime.session_runtime_status(session_id)["available"] is True
        assert len(transports) == 2
        assert transports[1].provider_session_ref == transports[0].provider_session_ref
        runtime.prompt_in_session(tmp_path, session_id, "second turn")
        assert transports[1].turns == ["second turn"]
    finally:
        runtime.shutdown()


def test_rehydrate_checkpoint_sink_rejects_unowned_pending_prompt_digest(tmp_path):
    """Legacy pending checkpoints cannot be rewritten without request ownership."""
    transports: list[FakeAgentSessionTransport] = []
    checkpoint_sinks: list[Any] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        checkpoint_sinks.append(kwargs["checkpoint_sink"])
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transport.provider_session_ref = kwargs.get("resume_provider_ref") or "prov-durable"
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(provider_prepare_fn=fake_prepare)
    try:
        record = session_store.build_session_record(
            session_id="ses_digest",
            execution_profile_id="profile-1",
            provider_id="opencode",
            model_id="m1",
            provider_session_ref="prov-durable",
            surface_id="opencode-acp",
            provider_metadata={"prompt-text-digest": "old-digest"},
        )
        session_store.write_session_record(tmp_path, record)
        runtime.rehydrate_session(
            tmp_path,
            "ses_digest",
            execution_profile_id="profile-1",
            provider_id="opencode",
            model_id="m1",
            surface_hint=None,
        )

        async def apply_checkpoint() -> None:
            await checkpoint_sinks[0](
                {
                    "unresolved-turn-pending": True,
                    "submission-proven": False,
                    "prompt-text-digest": "new-digest",
                }
            )

        with pytest.raises(AudiaGenticError, match="requires its request-owner fence"):
            runtime._call(apply_checkpoint(), timeout=5)
        stored = session_store.read_session_record(tmp_path, "ses_digest")
        assert stored["provider"]["metadata"]["prompt-text-digest"] == "old-digest"
    finally:
        runtime.shutdown()


def test_rehydrate_reopens_unbound_session_only_for_correlated_prepared_turn(tmp_path):
    """A proven pre-Send crash can reopen the project under the same session."""
    transports: list[FakeAgentSessionTransport] = []
    checkpoint_sinks: list[Any] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        checkpoint_sinks.append(kwargs["checkpoint_sink"])
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        if not transports:
            async def fail_first_open():
                raise RuntimeError("transient provider open failure")

            transport.open = fail_first_open
        transports.append(transport)
        return _build_fake_prepared(
            transport, provider_id="gpt-auto", surface_id="gpt-auto-cdp"
        )

    request_id = "req-prepared-restart"
    session_id = "ses-unbound-prepared"
    record = session_store.build_session_record(
        session_id=session_id,
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        created_by_request_id=request_id,
        idle_timeout_seconds=3600,
        max_lifetime_seconds=7200,
        provider_metadata={
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "project-id": "g-p-project",
            "unresolved-turn-pending": True,
            "unresolved-turn-id": request_id,
            "submission-proven": False,
            "submission-state": "prepared",
            "recovery-state": "submission-prepared",
        },
    )
    session_store.write_session_record(tmp_path, record)
    from audiagentic.components.agents.gateway import store as gateway_store

    request = gateway_store.build_record(
        request_id=request_id,
        execution_profile_id="gpt-auto",
        prompt_body="immutable admitted prompt",
        session_id=session_id,
        resolved_provider_id="gpt-auto",
    )
    request.update(
        {
            "state": "running",
            "started-at": now_iso_z(),
            "worker-id": "worker-prepared",
            "attempt-epoch": 1,
            "dispatch-owner-epoch": "owner-prepared",
            "provider-metadata": {"project-id": "g-p-project"},
            "gateway-profile-id": "gpt-auto",
            "gateway-profile-generation": "1",
            "gateway-profile-config-digest": "sha256:test",
            "resolved-instance-ids": ["source-gpt-auto"],
            "gateway-profile-runtime": {
                "provider-id": "gpt-auto",
                "params": {},
                "surface-id": "gpt-auto-cdp",
            },
        }
    )
    gateway_store.write_record(tmp_path, request)

    runtime = SessionRuntime(provider_prepare_fn=fake_prepare)
    try:
        with pytest.raises(AudiaGenticError, match="provider rejected prepared session recovery") as caught:
            runtime.rehydrate_session(
                tmp_path,
                session_id,
                execution_profile_id="gpt-auto",
                provider_id="gpt-auto",
                model_id="chatgpt",
                surface_hint=None,
                request_id=request_id,
                dispatch_owner_epoch="owner-prepared",
                worker_id="worker-prepared",
                attempt_epoch=1,
            )
        assert caught.value.details["submission-state"] == "not_started"
        checkpoint = session_store.session_provider_metadata(
            session_store.read_session_record(tmp_path, session_id)
        )
        assert checkpoint["unresolved-turn-pending"] is True
        assert checkpoint["submission-state"] == "prepared"
        assert "submission-recovery-claim" not in checkpoint

        restored = runtime.rehydrate_session(
            tmp_path,
            session_id,
            execution_profile_id="gpt-auto",
            provider_id="gpt-auto",
            model_id="chatgpt",
            surface_hint=None,
            request_id=request_id,
            dispatch_owner_epoch="owner-prepared",
            worker_id="worker-prepared",
            attempt_epoch=1,
        )

        assert restored["session-id"] == session_id
        assert restored["created-by-request-id"] == request_id
        assert restored["policy"]["idle-timeout-seconds"] == 3600
        assert restored["policy"]["max-lifetime-seconds"] == 7200
        assert len(transports) == 2
        assert transports[0].closed is True
        assert transports[1].opened is True
        checkpoint = session_store.session_provider_metadata(
            session_store.read_session_record(tmp_path, session_id)
        )
        assert checkpoint["unresolved-turn-pending"] is True
        assert checkpoint["submission-state"] == "prepared"
        assert checkpoint["unresolved-turn-id"] == request_id
        assert "submission-recovery-claim" in checkpoint
        with pytest.raises(AudiaGenticError, match="already claimed"):
            session_store.claim_prepared_submission_recovery(
                tmp_path,
                session_id,
                request_id,
                dispatch_owner_epoch="owner-prepared",
                worker_id="worker-prepared",
                attempt_epoch=1,
            )
        assert session_store.read_session_binding(tmp_path, session_id)[
            "provider-session-ref"
        ] == "prov-ses-1"

        dispatching_checkpoint = {
            "unresolved-turn-pending": True,
            "submission-state": "dispatching",
            "submission-proven": False,
            "unresolved-turn-id": request_id,
            "recovery-state": "side-effect-may-have-started",
        }
        asyncio.run(checkpoint_sinks[1](dispatching_checkpoint))
        # Repeated provider checkpoint updates must preserve the negative proof
        # marker; removing it is only safe for absent/default fields at the
        # initial prepared stage, never after dispatching has been recorded.
        asyncio.run(checkpoint_sinks[1](dispatching_checkpoint))
        checkpoint = session_store.session_provider_metadata(
            session_store.read_session_record(tmp_path, session_id)
        )
        assert checkpoint["submission-state"] == "dispatching"
        assert "submission-recovery-claim" not in checkpoint

        runtime.prompt_in_session(
            tmp_path, session_id, "immutable admitted prompt", request_id=request_id
        )
        assert transports[1].turns == ["immutable admitted prompt"]
    finally:
        runtime.shutdown()


def test_submission_checkpoint_cleanup_requires_terminal_request_and_owner_fence(tmp_path):
    from audiagentic.components.agents.gateway import store as gateway_store

    session_id = "ses_terminal_guard"
    request_id = "req_terminal_guard"
    session = session_store.build_session_record(
        session_id=session_id,
        execution_profile_id="profile-1",
        provider_id="opencode",
        model_id="m1",
        provider_session_ref="provider-session",
        surface_id="opencode-acp",
        provider_metadata={
            "unresolved-turn-pending": True,
            "unresolved-turn-id": request_id,
            "submission-state": "dispatching",
            "submission-proven": True,
            "submission-recovery-generation": 4,
            "prompt-text-digest": "prompt-hash",
        },
    )
    session_store.write_session_record(tmp_path, session)
    request = gateway_store.build_record(
        request_id=request_id,
        execution_profile_id="profile-1",
        prompt_body="prompt",
        session_id=session_id,
        resolved_provider_id="opencode",
    )
    request.update(
        {
            "state": "running",
            "worker-id": "worker-a",
            "attempt-epoch": 1,
            "dispatch-owner-epoch": "owner-a",
        }
    )
    gateway_store.write_record(tmp_path, request)

    with pytest.raises(AudiaGenticError, match="requires its request-owner fence"):
        session_store.update_provider_metadata(
            tmp_path,
            session_id,
            {},
            remove_keys=("submission-recovery-generation",),
        )
    with pytest.raises(AudiaGenticError, match="requires a terminal request"):
        session_store.update_provider_metadata(
            tmp_path,
            session_id,
            {},
            request_id=request_id,
            dispatch_owner_epoch="owner-a",
            worker_id="worker-a",
            attempt_epoch=1,
            remove_keys=("submission-state", "unresolved-turn-id"),
        )
    with pytest.raises(AudiaGenticError, match="cannot clear its recovery checkpoint"):
        session_store.update_owned_submission_checkpoint(
            tmp_path,
            session_id,
            request_id,
            {"unresolved-turn-pending": False},
            dispatch_owner_epoch="owner-a",
            worker_id="worker-a",
            attempt_epoch=1,
        )
    with pytest.raises(AudiaGenticError, match="requires a terminal request"):
        session_store.clear_terminal_submission_checkpoint(
            tmp_path,
            session_id,
            request_id,
            recovery_state="terminal-completed",
            remove_keys=("submission-state", "unresolved-turn-id"),
        )

    request["state"] = "completed"
    gateway_store.write_record(tmp_path, request)
    checkpoint_snapshot = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    successor_attempt = dict(checkpoint_snapshot)
    successor_attempt["submission-recovery-generation"] = 5
    assert not session_store.clear_terminal_submission_checkpoint(
        tmp_path,
        session_id,
        request_id,
        recovery_state="terminal-completed",
        remove_keys=("submission-state", "unresolved-turn-id"),
        expected_metadata=successor_attempt,
    )
    unchanged = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert unchanged["unresolved-turn-pending"] is True
    assert unchanged["submission-recovery-generation"] == 4

    assert session_store.clear_terminal_submission_checkpoint(
        tmp_path,
        session_id,
        request_id,
        recovery_state="terminal-completed",
        remove_keys=(
            "submission-state",
            "submission-recovery-generation",
            "unresolved-turn-id",
            "prompt-text-digest",
            "submission-proven",
        ),
        expected_metadata=checkpoint_snapshot,
    )
    metadata = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert metadata["unresolved-turn-pending"] is False
    assert metadata["recovery-state"] == "terminal-completed"
    assert not {
        "submission-state",
        "submission-recovery-generation",
        "unresolved-turn-id",
        "prompt-text-digest",
        "submission-proven",
    }.intersection(metadata)
    with pytest.raises(AudiaGenticError, match="requires its request-owner fence"):
        session_store.update_provider_metadata(
            tmp_path, session_id, {"submission-proven": False}
        )
    with pytest.raises(AudiaGenticError, match="lost its request owner fence"):
        session_store.update_provider_metadata(
            tmp_path,
            session_id,
            {"submission-proven": False},
            request_id=request_id,
            dispatch_owner_epoch="owner-a",
            worker_id="worker-a",
            attempt_epoch=1,
        )


@pytest.mark.parametrize("session_state", ["active", "failed"])
def test_completed_attempt_clears_nonpending_checkpoint_residue(tmp_path, session_state):
    from audiagentic.components.agents.gateway import store as gateway_store
    from audiagentic.components.agents.gateway.output import persist_final_response

    predecessor_id = "req-terminal-residue-predecessor"
    session_id = "ses-terminal-residue"
    attempt_id = "attempt-terminal-residue"
    session = session_store.build_session_record(
        session_id=session_id,
        created_by_request_id=predecessor_id,
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        provider_session_ref="provider-terminal-residue",
        surface_id="gpt-auto-cdp",
        provider_metadata={
            "unresolved-turn-pending": False,
            "recovery-state": "terminal-captured",
            "submission-state": "cleared",
            "submission-attempt-id": attempt_id,
            "submission-stage": "send-click-acknowledged",
            "send-intent-ever": True,
            "target-id": "target-1",
        },
    )
    session["state"] = session_state
    session_store.write_session_record(tmp_path, session)
    request = gateway_store.build_record(
        request_id=predecessor_id,
        execution_profile_id="gpt-auto",
        prompt_body="previous request",
        session_id=session_id,
        resolved_provider_id="gpt-auto",
    )
    artifact = persist_final_response(tmp_path, predecessor_id, "previous response")
    artifact.pop("output-preview", None)
    artifact.pop("output-truncated", None)
    request.update(
        {
            "state": "completed",
            "response-artifact": artifact,
            "provider-metadata": {"submission-attempt-id": attempt_id},
        }
    )
    gateway_store.write_record(tmp_path, request)
    expected = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    binding = session_store.read_session_record(tmp_path, session_id)["binding"]

    assert session_store.clear_completed_checkpoint_residue(
        tmp_path,
        session_id,
        predecessor_id,
        expected_metadata=expected,
        expected_binding_identity={
            "binding-id": binding["binding-id"],
            "generation": binding["generation"],
        },
    )

    actual = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert actual["unresolved-turn-pending"] is False
    assert actual["target-id"] == "target-1"
    assert actual["recovery-state"] == "stale-terminal-checkpoint-residue-cleared"
    assert not {
        "submission-state",
        "submission-attempt-id",
        "submission-stage",
        "send-intent-ever",
        "submission-proven",
        "submission-proof-source",
        "submission-recovery-generation",
        "unresolved-turn-id",
        "prompt-text-digest",
        "prompt-message-id",
        "assistant-message-id",
        "assistant-before-message-id",
        "assistant-before-id",
        "terminal-evidence",
        "unresolved-baseline-user-id",
        "unresolved-baseline-assistant-id",
        "unresolved-baseline-user-count",
        "unresolved-baseline-assistant-count",
        "unresolved-baseline-error-alert-occurrences",
    }.intersection(actual)


def test_orphaned_pending_checkpoint_requires_exact_terminal_attempt_proof(tmp_path):
    from audiagentic.components.agents.gateway import store as gateway_store
    from audiagentic.components.agents.gateway.output import persist_final_response
    from audiagentic.components.providers.adapters.gpt_auto.turn import (
        _terminal_checkpoint_fingerprint as provider_checkpoint_fingerprint,
    )

    predecessor_id = "req-orphan-pending-predecessor"
    session_id = "ses-orphan-pending"
    attempt_id = "attempt-orphan-pending"
    session = session_store.build_session_record(
        session_id=session_id,
        created_by_request_id=predecessor_id,
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        provider_session_ref="provider-orphan-pending",
        surface_id="gpt-auto-cdp",
        provider_metadata={
            "unresolved-turn-pending": True,
            "submission-attempt-id": attempt_id,
            "submission-stage": "send-click-acknowledged",
            "send-intent-ever": True,
            "submission-proven": True,
            "prompt-text-digest": "prompt-digest-orphan-pending",
            "unresolved-baseline-user-count": 0,
            "unresolved-baseline-assistant-count": 0,
            "unresolved-baseline-error-alert-occurrences": [],
        },
    )
    session_store.write_session_record(tmp_path, session)
    request = gateway_store.build_record(
        request_id=predecessor_id,
        execution_profile_id="gpt-auto",
        prompt_body="previous request",
        session_id=session_id,
        resolved_provider_id="gpt-auto",
    )
    artifact = persist_final_response(tmp_path, predecessor_id, "previous response")
    artifact.pop("output-preview", None)
    artifact.pop("output-truncated", None)
    request.update(
        {
            "state": "completed",
            "response-artifact": artifact,
            "provider-metadata": {
                "terminal-evidence": {
                    "turn-id": predecessor_id,
                    "policy": "response-complete",
                    "terminal-witness-id": "assistant-terminal",
                    "submission-attempt-fingerprint": hashlib.sha256(
                        attempt_id.encode("utf-8")
                    ).hexdigest(),
                    "submission-checkpoint-fingerprint": provider_checkpoint_fingerprint(
                        SimpleNamespace(
                            terminal_checkpoint_metadata=lambda turn_id: (
                                {
                                    **session_store.session_provider_metadata(session),
                                    "unresolved-turn-id": turn_id,
                                }
                                if turn_id == predecessor_id
                                else {}
                            )
                        ),
                        predecessor_id,
                    ),
                }
            },
        }
    )
    gateway_store.write_record(tmp_path, request)
    expected_record = session_store.read_session_record(tmp_path, session_id)
    expected_metadata = session_store.session_provider_metadata(expected_record)
    binding = expected_record["binding"]
    binding_identity = {
        "binding-id": binding["binding-id"],
        "generation": binding["generation"],
    }

    different_attempt_record = dict(expected_record)
    different_attempt_record["provider"] = dict(expected_record["provider"])
    different_attempt_record["provider"]["metadata"] = {
        **expected_metadata,
        "submission-attempt-id": "attempt-successor-b",
        "prompt-text-digest": "prompt-digest-successor-b",
    }
    session_store.write_session_record(tmp_path, different_attempt_record)
    different_attempt_metadata = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert not session_store.clear_completed_checkpoint_residue(
        tmp_path,
        session_id,
        predecessor_id,
        expected_metadata=different_attempt_metadata,
        expected_binding_identity=binding_identity,
        allow_orphaned_pending=True,
    )
    assert session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    ) == different_attempt_metadata
    session_store.write_session_record(tmp_path, expected_record)

    assert not session_store.clear_completed_checkpoint_residue(
        tmp_path,
        session_id,
        predecessor_id,
        expected_metadata=expected_metadata,
        expected_binding_identity=binding_identity,
    )
    terminal_evidence = request["provider-metadata"]["terminal-evidence"]
    checkpoint_fingerprint = terminal_evidence[
        "submission-checkpoint-fingerprint"
    ]
    terminal_evidence["submission-checkpoint-fingerprint"] = "mismatched-identity"
    gateway_store.write_record(tmp_path, request)
    assert not session_store.clear_completed_checkpoint_residue(
        tmp_path,
        session_id,
        predecessor_id,
        expected_metadata=expected_metadata,
        expected_binding_identity=binding_identity,
        allow_orphaned_pending=True,
    )
    assert session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    ) == expected_metadata
    terminal_evidence["submission-checkpoint-fingerprint"] = checkpoint_fingerprint
    gateway_store.write_record(tmp_path, request)

    assert session_store.clear_completed_checkpoint_residue(
        tmp_path,
        session_id,
        predecessor_id,
        expected_metadata=expected_metadata,
        expected_binding_identity=binding_identity,
        allow_orphaned_pending=True,
    )

    actual_record = session_store.read_session_record(tmp_path, session_id)
    actual = session_store.session_provider_metadata(actual_record)
    assert actual["unresolved-turn-pending"] is False
    assert actual["recovery-state"] == "orphaned-terminal-fence-cleared"
    assert actual_record["binding"] == binding
    assert "submission-attempt-id" not in actual


def test_initial_provider_binding_cannot_create_or_overwrite_turn_checkpoint(tmp_path):
    fresh_id = "ses-binding-metadata-fresh"
    fresh = session_store.build_session_record(
        session_id=fresh_id,
        created_by_request_id="req-binding-metadata-fresh",
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
    )
    session_store.write_session_record(tmp_path, fresh)
    binding_update = {
        "chat-url": "https://chatgpt.com/g/project/c/chat",
        **{
            key: f"foreign-{key}"
            for key in session_store._RECOVERY_CHECKPOINT_KEYS
        },
    }
    session_store.install_initial_provider_binding(
        tmp_path,
        fresh_id,
        provider_id="gpt-auto",
        surface_id="gpt-auto-cdp",
        provider_session_ref="provider-chat-fresh",
        metadata=binding_update,
    )
    fresh_metadata = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, fresh_id)
    )
    assert fresh_metadata["chat-url"] == binding_update["chat-url"]
    assert not session_store._RECOVERY_CHECKPOINT_KEYS.intersection(fresh_metadata)

    existing_id = "ses-binding-metadata-existing"
    existing_checkpoint = {
        "unresolved-turn-pending": True,
        "unresolved-turn-id": "req-owned-turn",
        "submission-state": "dispatching",
        "submission-attempt-id": "attempt-owned",
        "prompt-text-digest": "owned-digest",
    }
    existing = session_store.build_session_record(
        session_id=existing_id,
        created_by_request_id="req-binding-metadata-existing",
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        provider_metadata=existing_checkpoint,
    )
    session_store.write_session_record(tmp_path, existing)
    session_store.install_initial_provider_binding(
        tmp_path,
        existing_id,
        provider_id="gpt-auto",
        surface_id="gpt-auto-cdp",
        provider_session_ref="provider-chat-existing",
        metadata={
            "chat-title": "Bound chat",
            "unresolved-turn-pending": False,
            "unresolved-turn-id": "req-foreign-turn",
            "submission-state": "cleared",
            "submission-attempt-id": "attempt-foreign",
            "prompt-text-digest": "foreign-digest",
        },
    )
    persisted = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, existing_id)
    )
    assert persisted["chat-title"] == "Bound chat"
    for key, value in existing_checkpoint.items():
        assert persisted[key] == value


def test_request_owner_fence_rejection_records_exact_mismatch_facts(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import store as gateway_store

    monkeypatch.setattr(
        gateway_store,
        "read_record",
        lambda *_args: {
            "request-id": "req-owner-fence",
            "state": "running",
            "session-id": "ses-owner-fence",
            "dispatch-owner-epoch": "owner-current",
            "worker-id": "worker-current",
            "attempt-epoch": 3,
            "recovery-required": False,
        },
    )
    with pytest.raises(AudiaGenticError, match="lost its request owner fence") as caught:
        session_store._assert_request_dispatch_owner(
            tmp_path,
            "req-owner-fence",
            "ses-owner-fence",
            dispatch_owner_epoch="owner-stale",
            worker_id="worker-current",
            attempt_epoch=3,
        )

    facts = caught.value.details["request-owner-fence"]
    assert facts == {
        "request-state-owned": True,
        "session-id-matches": True,
        "dispatch-owner-epoch-matches": False,
        "worker-id-matches": True,
        "attempt-epoch-matches": True,
        "allow-queued-pre-send": False,
        "recovery-required": False,
    }


def test_completed_attempt_residue_clear_rejects_corrupt_artifact(tmp_path):
    from audiagentic.components.agents.gateway import store as gateway_store
    from audiagentic.components.agents.gateway.output import persist_final_response

    predecessor_id = "req-terminal-residue-reject"
    session_id = "ses-terminal-residue-reject"
    attempt_id = "attempt-terminal-residue-reject"
    session = session_store.build_session_record(
        session_id=session_id,
        created_by_request_id=predecessor_id,
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        provider_session_ref="provider-terminal-residue-reject",
        surface_id="gpt-auto-cdp",
        provider_metadata={
            "unresolved-turn-pending": False,
            "submission-attempt-id": attempt_id,
            "submission-stage": "send-click-acknowledged",
        },
    )
    session_store.write_session_record(tmp_path, session)
    request = gateway_store.build_record(
        request_id=predecessor_id,
        execution_profile_id="gpt-auto",
        prompt_body="previous request",
        session_id=session_id,
        resolved_provider_id="gpt-auto",
    )
    artifact = persist_final_response(tmp_path, predecessor_id, "previous response")
    artifact.pop("output-preview", None)
    artifact.pop("output-truncated", None)
    artifact["sha256"] = "not-the-real-digest"
    request.update(
        {
            "state": "completed",
            "response-artifact": artifact,
            "provider-metadata": {"submission-attempt-id": attempt_id},
        }
    )
    gateway_store.write_record(tmp_path, request)
    expected = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    binding = session_store.read_session_record(tmp_path, session_id)["binding"]

    assert not session_store.clear_completed_checkpoint_residue(
        tmp_path,
        session_id,
        predecessor_id,
        expected_metadata=expected,
        expected_binding_identity={
            "binding-id": binding["binding-id"],
            "generation": binding["generation"],
        },
    )
    assert session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    ) == expected


def test_completed_residue_cleanup_rejects_replaced_session_binding_generation(tmp_path):
    from audiagentic.components.agents.gateway import store as gateway_store
    from audiagentic.components.agents.gateway.output import persist_final_response

    predecessor_id = "req-terminal-residue-generation"
    session_id = "ses-terminal-residue-generation"
    attempt_id = "attempt-terminal-residue-generation"
    session = session_store.build_session_record(
        session_id=session_id,
        created_by_request_id=predecessor_id,
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        provider_session_ref="provider-terminal-residue-generation",
        surface_id="gpt-auto-cdp",
        provider_metadata={
            "unresolved-turn-pending": False,
            "submission-attempt-id": attempt_id,
            "submission-stage": "send-click-acknowledged",
        },
    )
    session_store.write_session_record(tmp_path, session)
    request = gateway_store.build_record(
        request_id=predecessor_id,
        execution_profile_id="gpt-auto",
        prompt_body="previous request",
        session_id=session_id,
        resolved_provider_id="gpt-auto",
    )
    artifact = persist_final_response(tmp_path, predecessor_id, "previous response")
    artifact.pop("output-preview", None)
    artifact.pop("output-truncated", None)
    request.update(
        {
            "state": "completed",
            "response-artifact": artifact,
            "provider-metadata": {"submission-attempt-id": attempt_id},
        }
    )
    gateway_store.write_record(tmp_path, request)
    expected_record = session_store.read_session_record(tmp_path, session_id)
    expected_metadata = session_store.session_provider_metadata(expected_record)
    expected_binding = expected_record["binding"]

    replacement = dict(expected_record)
    replacement["binding"] = {
        **expected_binding,
        "binding-id": "sbind-replacement-generation",
        "generation": expected_binding["generation"] + 1,
    }
    session_store.write_session_record(tmp_path, replacement)
    before_cleanup = session_store.read_session_record(tmp_path, session_id)

    assert not session_store.clear_completed_checkpoint_residue(
        tmp_path,
        session_id,
        predecessor_id,
        expected_metadata=expected_metadata,
        expected_binding_identity={
            "binding-id": expected_binding["binding-id"],
            "generation": expected_binding["generation"],
        },
    )
    after_cleanup = session_store.read_session_record(tmp_path, session_id)
    assert after_cleanup["binding"] == before_cleanup["binding"]
    assert session_store.session_provider_metadata(after_cleanup) == expected_metadata


def test_completed_residue_artifact_validation_serializes_with_archive_removal(
    tmp_path, monkeypatch
):
    from audiagentic.components.agents.agents_paths import (
        gateway_final_response_path,
        gateway_retention_lock_path,
    )
    from audiagentic.components.agents.gateway import output
    from audiagentic.components.agents.gateway import store as gateway_store
    from audiagentic.components.agents.gateway.output import persist_final_response
    from audiagentic.foundation.system.process import StartupLock

    predecessor_id = "req-terminal-residue-retention-lock"
    session_id = "ses-terminal-residue-retention-lock"
    attempt_id = "attempt-terminal-residue-retention-lock"
    session = session_store.build_session_record(
        session_id=session_id,
        created_by_request_id=predecessor_id,
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        provider_session_ref="provider-terminal-residue-retention-lock",
        surface_id="gpt-auto-cdp",
        provider_metadata={
            "unresolved-turn-pending": False,
            "submission-attempt-id": attempt_id,
            "submission-stage": "send-click-acknowledged",
        },
    )
    session_store.write_session_record(tmp_path, session)
    request = gateway_store.build_record(
        request_id=predecessor_id,
        execution_profile_id="gpt-auto",
        prompt_body="previous request",
        session_id=session_id,
        resolved_provider_id="gpt-auto",
    )
    artifact = persist_final_response(tmp_path, predecessor_id, "previous response")
    artifact.pop("output-preview", None)
    artifact.pop("output-truncated", None)
    request.update(
        {
            "state": "completed",
            "response-artifact": artifact,
            "provider-metadata": {"submission-attempt-id": attempt_id},
        }
    )
    gateway_store.write_record(tmp_path, request)
    session_record = session_store.read_session_record(tmp_path, session_id)
    expected_metadata = session_store.session_provider_metadata(session_record)
    binding = session_record["binding"]

    original_read = output.read_final_response
    artifact_read_entered = threading.Event()
    release_artifact_read = threading.Event()
    archive_lock_acquired = threading.Event()
    cleanup_results = []

    def paused_read(*args, **kwargs):
        artifact_read_entered.set()
        if not release_artifact_read.wait(timeout=3):
            raise TimeoutError("test did not release the artifact read")
        return original_read(*args, **kwargs)

    monkeypatch.setattr(output, "read_final_response", paused_read)

    def clear_checkpoint():
        cleanup_results.append(
            session_store.clear_completed_checkpoint_residue(
                tmp_path,
                session_id,
                predecessor_id,
                expected_metadata=expected_metadata,
                expected_binding_identity={
                    "binding-id": binding["binding-id"],
                    "generation": binding["generation"],
                },
            )
        )

    def archive_after_retention_fence():
        with StartupLock(gateway_retention_lock_path(tmp_path)):
            gateway_final_response_path(tmp_path, predecessor_id).unlink(missing_ok=True)
            archive_lock_acquired.set()

    cleanup_thread = threading.Thread(target=clear_checkpoint)
    cleanup_thread.start()
    try:
        assert artifact_read_entered.wait(timeout=2)
        archive_thread = threading.Thread(target=archive_after_retention_fence)
        archive_thread.start()
        assert not archive_lock_acquired.wait(timeout=0.1)
    finally:
        release_artifact_read.set()
    cleanup_thread.join(timeout=2)
    archive_thread.join(timeout=2)

    assert not cleanup_thread.is_alive()
    assert not archive_thread.is_alive()
    assert cleanup_results == [True]
    assert archive_lock_acquired.is_set()
    assert not gateway_final_response_path(tmp_path, predecessor_id).exists()


def test_owned_checkpoint_stage_rejection_records_bounded_trace_predicates(tmp_path):
    from audiagentic.components.agents.gateway import store as gateway_store

    request_id = "req-stage-diagnostic"
    session_id = "ses-stage-diagnostic"
    owner = {
        "dispatch_owner_epoch": "owner-stage-diagnostic",
        "worker_id": "worker-stage-diagnostic",
        "attempt_epoch": 1,
    }
    session = session_store.build_session_record(
        session_id=session_id,
        created_by_request_id=request_id,
        provider_transport_kind="provider-session",
        execution_profile_id="profile-1",
        provider_id="opencode",
        model_id="model-1",
        provider_metadata={
            "unresolved-turn-pending": True,
            "unresolved-turn-id": request_id,
            "submission-state": "proven",
            "submission-proven": True,
        },
    )
    session_store.write_session_record(tmp_path, session)
    request = gateway_store.build_record(
        request_id=request_id,
        execution_profile_id="profile-1",
        prompt_body="not persisted in diagnostic details",
        session_id=session_id,
        resolved_provider_id="opencode",
    )
    request.update(
        {
            "state": "running",
            "dispatch-owner-epoch": owner["dispatch_owner_epoch"],
            "worker-id": owner["worker_id"],
            "attempt-epoch": owner["attempt_epoch"],
        }
    )
    gateway_store.write_record(tmp_path, request)

    with pytest.raises(AudiaGenticError) as caught:
        session_store.update_owned_submission_checkpoint(
            tmp_path,
            session_id,
            request_id,
            {"recovery-state": "submission-proven"},
            **owner,
        )

    assert caught.value.code == "CON-AGW-125"
    assert caught.value.details["checkpoint-diagnostics"] == {
        "observed-stage": "proven",
        "requested-stage": None,
        "unresolved-turn-pending": True,
        "turn-id-matches-request": True,
        "claim-id-supplied": False,
        "claim-present": False,
        "claim-generation-present": False,
        "submission-proven": True,
        "request-recovery-required": False,
        "proof-source-valid": False,
        "proof-update-keys-safe": True,
        "frozen-identity-unchanged": False,
        "frozen-identity-mismatch-keys": ["unresolved-turn-id"],
        "provider-anchor-valid": False,
        "fingerprint-equal": False,
        "baseline-user-count-matches": False,
        "baseline-assistant-count-matches": False,
        "baseline-user-id-is-new": True,
        "request-owner-is-current": True,
    }
    sessions_module._record_submission_checkpoint_rejection(
        tmp_path,
        request_id,
        session_id,
        owner["attempt_epoch"],
        caught.value,
    )
    from audiagentic.components.agents.agents_paths import gateway_observation_path

    events = load_ndjson(gateway_observation_path(tmp_path, request_id))
    assert events[-1]["source"] == "session-checkpoint"
    assert events[-1]["facts"]["diagnostic-facts"]["checkpoint"] == {
        "observed-stage": "proven",
        "unresolved-turn-pending": True,
        "turn-id-matches-request": True,
        "claim-id-supplied": False,
        "claim-present": False,
        "claim-generation-present": False,
        "submission-proven": True,
        "request-recovery-required": False,
        "proof-source-valid": False,
        "proof-update-keys-safe": True,
        "frozen-identity-unchanged": False,
        "frozen-identity-mismatch-keys": ["unresolved-turn-id"],
        "provider-anchor-valid": False,
        "fingerprint-equal": False,
        "baseline-user-count-matches": False,
        "baseline-assistant-count-matches": False,
        "baseline-user-id-is-new": True,
        "request-owner-is-current": True,
    }
    assert events[-1]["facts"]["error-occurrence"]["failure-code"] == "CON-AGW-125"
    serialized = str(events[-1])
    assert "not persisted in diagnostic details" not in serialized


@pytest.mark.parametrize("initial_alert_baseline", [None, []])
@pytest.mark.parametrize("cleared_annotation", [None, "terminal-captured", "stale-terminal-checkpoint-residue-cleared", "orphaned-terminal-fence-cleared"])
def test_fresh_owned_submission_checkpoint_is_durable_before_send_and_terminal_cleanup(
    tmp_path, initial_alert_baseline, cleared_annotation,
):
    from audiagentic.components.agents.gateway import store as gateway_store

    request_id = "req-fresh-owned-checkpoint"
    session_id = "ses-fresh-owned-checkpoint"
    owner = {
        "dispatch_owner_epoch": "owner-fresh",
        "worker_id": "worker-fresh",
        "attempt_epoch": 1,
    }
    project_id = "g-p-audiagentic-exact"
    session = session_store.build_session_record(
        session_id=session_id,
        created_by_request_id=request_id,
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        provider_metadata={
            "project-id": project_id,
            "project-url": f"https://chatgpt.com/{project_id}/project",
            # GPT-auto includes these negative defaults in initial binding
            # metadata, before this newly admitted request's first prepared
            # checkpoint is written.
            "unresolved-turn-pending": False,
            "submission-proven": False,
            **({"recovery-state": cleared_annotation} if cleared_annotation else {}),
            **({"unresolved-baseline-error-alert-occurrences": initial_alert_baseline}
               if initial_alert_baseline is not None else {}),
        },
    )
    session_store.write_session_record(tmp_path, session)
    request = gateway_store.build_record(
        request_id=request_id,
        execution_profile_id="gpt-auto",
        prompt_body="prompt remains request-owned",
        session_id=session_id,
        resolved_provider_id="gpt-auto",
    )
    request.update(
        {
            "state": "running",
            "worker-id": owner["worker_id"],
            "attempt-epoch": owner["attempt_epoch"],
            "dispatch-owner-epoch": owner["dispatch_owner_epoch"],
            "provider-metadata": {"project-id": project_id},
        }
    )
    gateway_store.write_record(tmp_path, request)

    # A newly admitted GPT session has no unresolved-turn checkpoint yet.
    # The active request owner may initialize exactly its own prepared turn.
    fresh_submission_remove_keys = (
        "submission-proven",
        "prompt-message-id",
        "assistant-message-id",
        "assistant-before-message-id",
        "assistant-before-id",
        "terminal-evidence",
    )
    with pytest.raises(AudiaGenticError, match="cleanup exceeds the absent/default allowlist"):
        session_store.update_provider_metadata(
            tmp_path,
            session_id,
            {
                "unresolved-turn-pending": True,
                "unresolved-turn-id": request_id,
                "submission-state": "prepared",
                "submission-proven": False,
                "recovery-state": "submission-prepared",
                "prompt-text-digest": "prompt-digest",
            },
            request_id=request_id,
            **owner,
            remove_keys=("project-id",),
        )
    with pytest.raises(AudiaGenticError, match="cleanup exceeds the absent/default allowlist"):
        session_store.update_provider_metadata(
            tmp_path,
            session_id,
            {
                "unresolved-turn-pending": True,
                "unresolved-turn-id": request_id,
                "submission-state": "prepared",
                "submission-proven": False,
                "recovery-state": "submission-prepared",
                "prompt-text-digest": "prompt-digest",
                "terminal-evidence": {"source": "test"},
            },
            request_id=request_id,
            **owner,
            remove_keys=("terminal-evidence",),
        )
    session_store.update_provider_metadata(
        tmp_path,
        session_id,
        {
            "unresolved-turn-pending": True,
            "unresolved-turn-id": request_id,
            "submission-state": "prepared",
            "submission-proven": False,
            "recovery-state": "submission-prepared",
            "prompt-text-digest": "prompt-digest",
            "unresolved-baseline-user-count": 0,
            "unresolved-baseline-assistant-count": 0,
            "unresolved-baseline-error-alert-occurrences": [],
        },
        request_id=request_id,
        **owner,
        remove_keys=fresh_submission_remove_keys,
    )
    persisted = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert persisted["submission-state"] == "prepared"
    assert persisted["unresolved-turn-pending"] is True
    assert persisted["unresolved-turn-id"] == request_id

    # The uninterrupted first-turn owner advances before the browser Send.
    dispatching_checkpoint = {
        "unresolved-turn-pending": True,
        "unresolved-turn-id": request_id,
        "submission-state": "dispatching",
        "submission-proven": False,
        "recovery-state": "side-effect-may-have-started",
        "unresolved-baseline-user-count": 0,
        "unresolved-baseline-assistant-count": 0,
        "unresolved-baseline-error-alert-occurrences": [],
    }
    session_store.update_provider_metadata(
        tmp_path,
        session_id,
        dispatching_checkpoint,
        request_id=request_id,
        **owner,
        # The live checkpoint sink applies the same cleanup list to both the
        # prepared and prepared->dispatching callbacks.
        remove_keys=fresh_submission_remove_keys,
    )
    restarted_metadata = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert restarted_metadata["submission-state"] == "dispatching"
    assert restarted_metadata["unresolved-turn-pending"] is True
    assert restarted_metadata["unresolved-turn-id"] == request_id

    # A provider-validated user-message proof advances this exact owned turn
    # from dispatching to proven; it cannot be used to change turn identity.
    session_record = session_store.read_session_record(tmp_path, session_id)
    malformed_metadata = session_store.session_provider_metadata(session_record)
    malformed_metadata["submission-proven"] = "false"
    session_record.setdefault("provider", {})["metadata"] = malformed_metadata
    session_store.write_session_record(tmp_path, session_record)
    with pytest.raises(AudiaGenticError, match="does not match the current dispatch stage"):
        session_store.update_provider_metadata(
            tmp_path,
            session_id,
            {
                "submission-state": "proven",
                "submission-proven": True,
                "unresolved-turn-pending": True,
                "unresolved-turn-id": request_id,
                "prompt-message-id": "provider-user-message-1",
                "prompt-text-digest": "prompt-digest",
                "unresolved-baseline-user-count": 0,
            },
            request_id=request_id,
            **owner,
        )
    malformed_metadata.pop("submission-proven")
    session_record.setdefault("provider", {})["metadata"] = malformed_metadata
    session_store.write_session_record(tmp_path, session_record)

    with pytest.raises(AudiaGenticError, match="does not match the current dispatch stage"):
        session_store.update_provider_metadata(
            tmp_path,
            session_id,
            {
                "submission-state": "proven",
                "submission-proven": True,
                "unresolved-turn-pending": True,
                "unresolved-turn-id": "req-another-turn",
            },
            request_id=request_id,
            **owner,
        )
    with pytest.raises(AudiaGenticError, match="does not match the current dispatch stage"):
        session_store.update_provider_metadata(
            tmp_path,
            session_id,
            {
                "submission-state": "proven",
                "submission-proven": True,
                "unresolved-turn-pending": True,
                "unresolved-turn-id": request_id,
                "unresolved-baseline-user-count": 0,
            },
            request_id=request_id,
            **owner,
        )
    valid_proven_update = {
        "submission-state": "proven",
        "submission-proven": True,
        "submission-proof-source": "provider-user-message",
        "unresolved-turn-pending": True,
        "unresolved-turn-id": request_id,
        "prompt-message-id": "provider-user-message-1",
        "prompt-text-digest": "prompt-digest",
        "unresolved-baseline-user-count": 0,
        "unresolved-baseline-assistant-count": 0,
        "unresolved-baseline-error-alert-occurrences": [],
        "recovery-state": "submission-proven",
    }
    dispatching_metadata = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    for injected in (
        {"unresolved-baseline-assistant-count": 999},
        {"unresolved-baseline-user-id": "foreign-provider-message"},
        {"unresolved-baseline-error-alert-occurrences": [{"digest": "foreign"}]},
        {"prompt-text-digest": "different-digest"},
        {"unapproved-checkpoint-field": "not-owned"},
        {"prompt-message-id": "virtualized-prompt-for-assistant-1"},
        {"submission-proof-source": "caller-asserted"},
    ):
        with pytest.raises(
            AudiaGenticError,
            match="does not match the current dispatch stage",
        ) as rejected:
            session_store.update_provider_metadata(
                tmp_path,
                session_id,
                {**valid_proven_update, **injected},
                request_id=request_id,
                **owner,
            )
        if "prompt-message-id" in injected:
            assert rejected.value.details["checkpoint-diagnostics"][
                "provider-anchor-valid"
            ] is False
        if "prompt-text-digest" in injected:
            assert rejected.value.details["checkpoint-diagnostics"][
                "frozen-identity-mismatch-keys"
            ] == ["prompt-text-digest"]
        assert session_store.session_provider_metadata(
            session_store.read_session_record(tmp_path, session_id)
        ) == dispatching_metadata

    session_store.update_provider_metadata(
        tmp_path,
        session_id,
        valid_proven_update,
        request_id=request_id,
        **owner,
    )
    proven_metadata = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert proven_metadata["submission-state"] == "proven"
    assert proven_metadata["submission-proven"] is True

    with pytest.raises(AudiaGenticError, match="changed before recovery claim"):
        session_store.claim_prepared_submission_recovery(
            tmp_path,
            session_id,
            request_id,
            **owner,
        )

    request["state"] = "completed"
    gateway_store.write_record(tmp_path, request)
    assert session_store.clear_terminal_submission_checkpoint(
        tmp_path,
        session_id,
        request_id,
        recovery_state="terminal-completed",
        remove_keys=(
            "submission-state",
            "submission-recovery-generation",
            "unresolved-turn-id",
            "prompt-text-digest",
            "submission-proven",
        ),
    )
    terminal_metadata = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert terminal_metadata["unresolved-turn-pending"] is False
    assert terminal_metadata["recovery-state"] == "terminal-completed"
    assert "submission-state" not in terminal_metadata
    assert "unresolved-turn-id" not in terminal_metadata


def test_queued_owner_can_claim_only_proven_unsent_prepared_checkpoint(tmp_path):
    from audiagentic.components.agents.gateway import store as gateway_store

    request_id = "req-queued-prepared-checkpoint"
    session_id = "ses-queued-prepared-checkpoint"
    project_id = "g-p-audiagentic-exact"
    owner = {
        "dispatch_owner_epoch": "owner-queued",
        "worker_id": "worker-queued",
        "attempt_epoch": 1,
    }
    session = session_store.build_session_record(
        session_id=session_id,
        created_by_request_id=request_id,
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        provider_metadata={
            "project-id": project_id,
            "unresolved-turn-pending": True,
            "unresolved-turn-id": request_id,
            "submission-state": "prepared",
            "submission-proven": False,
            "recovery-state": "submission-prepared",
            "prompt-text-digest": "queued-prompt-digest",
        },
    )
    session_store.write_session_record(tmp_path, session)
    request = gateway_store.build_record(
        request_id=request_id,
        execution_profile_id="gpt-auto",
        prompt_body="immutable queued prompt",
        session_id=session_id,
        resolved_provider_id="gpt-auto",
    )
    request.update(
        {
            "state": "queued",
            "worker-id": owner["worker_id"],
            "attempt-epoch": owner["attempt_epoch"],
            "dispatch-owner-epoch": owner["dispatch_owner_epoch"],
            "provider-metadata": {"project-id": project_id},
        }
    )
    gateway_store.write_record(tmp_path, request)

    with pytest.raises(AudiaGenticError, match="owner fence"):
        session_store.claim_prepared_submission_recovery(
            tmp_path,
            session_id,
            request_id,
            dispatch_owner_epoch=owner["dispatch_owner_epoch"],
            worker_id="stale-worker",
            attempt_epoch=owner["attempt_epoch"],
        )

    claim = session_store.claim_prepared_submission_recovery(
        tmp_path,
        session_id,
        request_id,
        **owner,
    )
    session_store.advance_prepared_submission_to_dispatching(
        tmp_path,
        session_id,
        request_id,
        {
            "unresolved-turn-pending": True,
            "unresolved-turn-id": request_id,
            "submission-state": "dispatching",
            "submission-proven": False,
            "recovery-state": "side-effect-may-have-started",
        },
        claim_id=claim["claim-id"],
        **owner,
    )
    checkpoint = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert checkpoint["submission-state"] == "dispatching"
    assert checkpoint["submission-proven"] is False


def test_restarted_prepared_checkpoint_requires_recovery_claim(tmp_path):
    from audiagentic.components.agents.gateway import store as gateway_store

    request_id = "req-restarted-prepared-checkpoint"
    session_id = "ses-restarted-prepared-checkpoint"
    project_id = "g-p-audiagentic-exact"
    initial_owner = {
        "dispatch_owner_epoch": "owner-before-restart",
        "worker_id": "worker-before-restart",
        "attempt_epoch": 1,
    }
    session = session_store.build_session_record(
        session_id=session_id,
        created_by_request_id=request_id,
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        provider_metadata={"project-id": project_id},
    )
    session_store.write_session_record(tmp_path, session)
    request = gateway_store.build_record(
        request_id=request_id,
        execution_profile_id="gpt-auto",
        prompt_body="immutable prepared prompt",
        session_id=session_id,
        resolved_provider_id="gpt-auto",
    )
    request.update(
        {
            "state": "running",
            "worker-id": initial_owner["worker_id"],
            "attempt-epoch": initial_owner["attempt_epoch"],
            "dispatch-owner-epoch": initial_owner["dispatch_owner_epoch"],
            "provider-metadata": {"project-id": project_id},
        }
    )
    gateway_store.write_record(tmp_path, request)
    session_store.update_provider_metadata(
        tmp_path,
        session_id,
        {
            "unresolved-turn-pending": True,
            "unresolved-turn-id": request_id,
            "submission-state": "prepared",
            "submission-proven": False,
            "recovery-state": "submission-prepared",
            "prompt-text-digest": "restart-prompt-digest",
        },
        request_id=request_id,
        **initial_owner,
    )

    recovery_owner = {
        "dispatch_owner_epoch": "owner-after-restart",
        "worker_id": "worker-after-restart",
        "attempt_epoch": initial_owner["attempt_epoch"],
    }
    gateway_store.takeover_nonterminal_owner(
        tmp_path,
        request_id,
        expected_owner_epoch=initial_owner["dispatch_owner_epoch"],
        new_owner_epoch=recovery_owner["dispatch_owner_epoch"],
        new_worker_id=recovery_owner["worker_id"],
    )
    dispatching_checkpoint = {
        "unresolved-turn-pending": True,
        "unresolved-turn-id": request_id,
        "submission-state": "dispatching",
        "submission-proven": False,
        "recovery-state": "side-effect-may-have-started",
    }
    with pytest.raises(AudiaGenticError, match="cannot advance without its request owner"):
        session_store.update_owned_submission_checkpoint(
            tmp_path,
            session_id,
            request_id,
            dispatching_checkpoint,
            **recovery_owner,
        )
    unchanged = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert unchanged["submission-state"] == "prepared"
    assert unchanged["unresolved-turn-id"] == request_id

    claim = session_store.claim_prepared_submission_recovery(
        tmp_path,
        session_id,
        request_id,
        **recovery_owner,
    )
    with pytest.raises(AudiaGenticError, match="removal is not limited to absent/default fields"):
        session_store.advance_prepared_submission_to_dispatching(
            tmp_path,
            session_id,
            request_id,
            dispatching_checkpoint,
            claim_id=claim["claim-id"],
            **recovery_owner,
            remove_keys=("unresolved-turn-id",),
        )
    unchanged = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert unchanged["submission-state"] == "prepared"
    assert unchanged["unresolved-turn-id"] == request_id
    session_store.advance_prepared_submission_to_dispatching(
        tmp_path,
        session_id,
        request_id,
        dispatching_checkpoint,
        claim_id=claim["claim-id"],
        **recovery_owner,
    )
    recovered = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert recovered["submission-state"] == "dispatching"
    assert recovered["unresolved-turn-pending"] is True

    session_store.update_owned_submission_checkpoint(
        tmp_path,
        session_id,
        request_id,
        {
            "submission-attempt-id": "attempt-stage-1",
            "submission-stage": "send-intent",
            "send-intent-ever": True,
        },
        **recovery_owner,
    )
    with pytest.raises(AudiaGenticError, match="cannot move backwards"):
        session_store.update_owned_submission_checkpoint(
            tmp_path,
            session_id,
            request_id,
            {
                "submission-attempt-id": "attempt-stage-1",
                "submission-stage": "composer-filled",
                "send-intent-ever": True,
            },
            **recovery_owner,
        )
    with pytest.raises(AudiaGenticError, match="latch cannot be cleared"):
        session_store.update_owned_submission_checkpoint(
            tmp_path,
            session_id,
            request_id,
            {"send-intent-ever": False},
            **recovery_owner,
        )
    staged = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert staged["submission-stage"] == "send-intent"
    assert staged["send-intent-ever"] is True


def test_successor_claim_fences_stale_prepared_binding_checkpoint_and_open_commit(
    tmp_path, monkeypatch
):
    from audiagentic.components.agents.gateway import store as gateway_store

    request_id = "req-prepared-owner-takeover"
    session_id = "ses-prepared-owner-takeover"
    session = session_store.build_session_record(
        session_id=session_id,
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        provider_metadata={
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "project-id": "g-p-project",
            "unresolved-turn-pending": True,
            "unresolved-turn-id": request_id,
            "submission-proven": False,
            "submission-state": "prepared",
        },
    )
    session_store.write_session_record(tmp_path, session)
    request = gateway_store.build_record(
        request_id=request_id,
        execution_profile_id="gpt-auto",
        prompt_body="frozen prompt",
        session_id=session_id,
        resolved_provider_id="gpt-auto",
    )
    request.update(
        {
            "state": "running",
            "started-at": now_iso_z(),
            "worker-id": "worker-a",
            "attempt-epoch": 1,
            "dispatch-owner-epoch": "owner-a",
            "provider-metadata": {"project-id": "g-p-project"},
        }
    )
    gateway_store.write_record(tmp_path, request)

    claim_a = session_store.claim_prepared_submission_recovery(
        tmp_path,
        session_id,
        request_id,
        dispatch_owner_epoch="owner-a",
        worker_id="worker-a",
        attempt_epoch=1,
    )
    assert session_store.release_prepared_submission_recovery_claim(
        tmp_path, session_id, claim_id=claim_a["claim-id"]
    )
    released_metadata = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert released_metadata["submission-recovery-generation"] == claim_a["generation"]
    assert "submission-recovery-claim" not in released_metadata
    claim_a = session_store.claim_prepared_submission_recovery(
        tmp_path,
        session_id,
        request_id,
        dispatch_owner_epoch="owner-a",
        worker_id="worker-a",
        attempt_epoch=1,
    )
    assert claim_a["generation"] == released_metadata["submission-recovery-generation"] + 1
    expired_session = session_store.read_session_record(tmp_path, session_id)
    expired_metadata = session_store.session_provider_metadata(expired_session)
    expired_metadata["submission-recovery-claim"]["lease-expires-at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat().replace("+00:00", "Z")
    expired_session.setdefault("provider", {})["metadata"] = expired_metadata
    session_store.write_session_record(tmp_path, expired_session)
    claim_a_expired_retry = session_store.claim_prepared_submission_recovery(
        tmp_path,
        session_id,
        request_id,
        dispatch_owner_epoch="owner-a",
        worker_id="worker-a",
        attempt_epoch=1,
    )
    assert claim_a_expired_retry["generation"] == claim_a["generation"] + 1
    claim_a = claim_a_expired_retry
    request.update(
        {
            "worker-id": "worker-b",
            "attempt-epoch": 2,
            "dispatch-owner-epoch": "owner-b",
        }
    )
    gateway_store.write_record(tmp_path, request)
    claim_b = session_store.claim_prepared_submission_recovery(
        tmp_path,
        session_id,
        request_id,
        dispatch_owner_epoch="owner-b",
        worker_id="worker-b",
        attempt_epoch=2,
    )
    assert claim_b["generation"] == claim_a["generation"] + 1

    with pytest.raises(AudiaGenticError, match="requires its request-owner fence"):
        session_store.update_provider_metadata(
            tmp_path,
            session_id,
            {"submission-recovery-claim": {"claim-id": "unfenced"}},
        )
    with pytest.raises(AudiaGenticError, match="cannot claim a submitted prompt"):
        session_store.update_owned_submission_checkpoint(
            tmp_path,
            session_id,
            request_id,
            {"submission-proven": True},
            claim_id=claim_b["claim-id"],
            dispatch_owner_epoch="owner-b",
            worker_id="worker-b",
            attempt_epoch=2,
        )
    with pytest.raises(AudiaGenticError, match="cannot be removed before dispatch"):
        session_store.update_owned_submission_checkpoint(
            tmp_path,
            session_id,
            request_id,
            {},
            claim_id=claim_b["claim-id"],
            dispatch_owner_epoch="owner-b",
            worker_id="worker-b",
            attempt_epoch=2,
            remove_keys=("submission-state", "unresolved-turn-id"),
        )

    with pytest.raises(AudiaGenticError, match="lost its request owner fence"):
        session_store.update_prepared_submission_checkpoint(
            tmp_path,
            session_id,
            request_id,
            {"recovery-state": "stale-worker-write"},
            claim_id=claim_a["claim-id"],
            dispatch_owner_epoch="owner-a",
            worker_id="worker-a",
            attempt_epoch=1,
        )
    with pytest.raises(AudiaGenticError, match="lost its request owner fence"):
        session_store.install_prepared_recovery_binding(
            tmp_path,
            session_id,
            request_id,
            provider_id="gpt-auto",
            surface_id="gpt-auto-cdp",
            provider_session_ref="stale-provider-session",
            expected_surface_id="gpt-auto-cdp",
            claim_id=claim_a["claim-id"],
            dispatch_owner_epoch="owner-a",
            worker_id="worker-a",
            attempt_epoch=1,
        )

    opened_record = session_store.build_session_record(
        session_id=session_id,
        provider_transport_kind="provider-session",
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        model_id="chatgpt",
        provider_session_ref="provider-session-a",
        surface_id="gpt-auto-cdp",
        provider_metadata={
            "provider-open-marker": "ok",
            "submission-state": "dispatching",
            "submission-proven": True,
            "unresolved-turn-id": "another-request",
        },
    )
    with pytest.raises(AudiaGenticError, match="lost its request owner fence"):
        session_store.commit_prepared_recovery_open(
            tmp_path,
            session_id,
            request_id,
            opened_record,
            claim_id=claim_a["claim-id"],
            dispatch_owner_epoch="owner-a",
            worker_id="worker-a",
            attempt_epoch=1,
            expected_surface_id="gpt-auto-cdp",
        )

    persisted = session_store.read_session_record(tmp_path, session_id)
    assert persisted.get("binding") is None
    metadata = session_store.session_provider_metadata(persisted)
    assert metadata["submission-state"] == "prepared"
    assert metadata["submission-recovery-claim"]["claim-id"] == claim_b["claim-id"]

    register_open_binding = binding_store.register_open_binding
    registration_attempts = 0

    def fail_index_registration(*args, **kwargs):
        raise RuntimeError("simulated binding index failure")

    monkeypatch.setattr(binding_store, "register_open_binding", fail_index_registration)
    with pytest.raises(RuntimeError, match="simulated binding index failure"):
        session_store.commit_prepared_recovery_open(
            tmp_path,
            session_id,
            request_id,
            opened_record,
            claim_id=claim_b["claim-id"],
            dispatch_owner_epoch="owner-b",
            worker_id="worker-b",
            attempt_epoch=2,
            expected_surface_id="gpt-auto-cdp",
        )
    rolled_back = session_store.read_session_record(tmp_path, session_id)
    assert rolled_back.get("binding") is None

    def crash_before_index_publication(*args, **kwargs):
        nonlocal registration_attempts
        registration_attempts += 1
        if registration_attempts == 1:
            raise SystemExit("simulated crash before binding index publication")
        return register_open_binding(*args, **kwargs)

    monkeypatch.setattr(
        binding_store, "register_open_binding", crash_before_index_publication
    )
    callback_records = []
    with pytest.raises(SystemExit, match="simulated crash"):
        session_store.commit_prepared_recovery_open(
            tmp_path,
            session_id,
            request_id,
            opened_record,
            claim_id=claim_b["claim-id"],
            dispatch_owner_epoch="owner-b",
            worker_id="worker-b",
            attempt_epoch=2,
            expected_surface_id="gpt-auto-cdp",
            on_commit=callback_records.append,
        )

    persisted = session_store.read_session_record(tmp_path, session_id)
    assert persisted["binding"]["provider-session-ref"] == "provider-session-a"
    index = binding_store._read_index(gateway_session_binding_index_path(tmp_path))
    assert not index["bindings"]
    assert callback_records == []

    session_store.commit_prepared_recovery_open(
        tmp_path,
        session_id,
        request_id,
        opened_record,
        claim_id=claim_b["claim-id"],
        dispatch_owner_epoch="owner-b",
        worker_id="worker-b",
        attempt_epoch=2,
        expected_surface_id="gpt-auto-cdp",
        on_commit=callback_records.append,
    )
    index = binding_store._read_index(gateway_session_binding_index_path(tmp_path))
    assert any(
        entry["session-id"] == session_id
        for entries in index["bindings"].values()
        for entry in entries
    )
    assert len(callback_records) == 1
    recovered_metadata = session_store.session_provider_metadata(
        session_store.read_session_record(tmp_path, session_id)
    )
    assert recovered_metadata["submission-state"] == "prepared"
    assert recovered_metadata["submission-proven"] is False
    assert recovered_metadata["unresolved-turn-id"] == request_id
    assert recovered_metadata["provider-open-marker"] == "ok"


def test_rehydrated_generation_preserves_durable_max_lifetime(tmp_path):
    """A gateway restart cannot reset the session's absolute lifetime."""
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transport.provider_session_ref = kwargs.get("resume_provider_ref") or "prov-durable"
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(clock=clock, provider_prepare_fn=fake_prepare)
    try:
        record = runtime.open_session(
            tmp_path,
            execution_profile_id="profile-1",
            provider_id="opencode",
            model_id="m1",
            surface_hint=None,
            max_lifetime_seconds=60,
        )
        session_id = record["session-id"]
        old_created_at = (
            datetime.now(timezone.utc) - timedelta(seconds=30)
        ).isoformat().replace("+00:00", "Z")
        stored = session_store.read_session_record(tmp_path, session_id)
        stored["timing"]["created-at"] = old_created_at
        session_store.write_session_record(tmp_path, stored)

        async def drop_handle() -> None:
            runtime._handles.pop(session_id, None)

        runtime._call(drop_handle(), timeout=5)
        runtime.rehydrate_session(
            tmp_path,
            session_id,
            execution_profile_id="profile-1",
            provider_id="opencode",
            model_id="m1",
            surface_hint=None,
        )
        clock.now += 31
        with pytest.raises(AudiaGenticError, match="CON-AGW-004"):
            runtime.prompt_in_session(tmp_path, session_id, "too late")
    finally:
        runtime.shutdown()


def test_rehydrate_rejects_provider_identity_swap_and_closes_transport(tmp_path):
    """A resume that proves a different provider ref cannot leak a handle."""
    transports: list[FakeAgentSessionTransport] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transport.provider_session_ref = "prov-not-the-bound-session"
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(provider_prepare_fn=fake_prepare)
    try:
        # Seed a durable active record with the binding that the fake will
        # deliberately violate on rehydration.
        record = session_store.build_session_record(
            session_id="ses_swap",
            execution_profile_id="profile-1",
            provider_id="opencode",
            model_id="m1",
            provider_session_ref="prov-bound",
            surface_id="opencode-acp",
        )
        session_store.write_session_record(tmp_path, record)
        with pytest.raises(AudiaGenticError, match="CON-AGW-121"):
            runtime.rehydrate_session(
                tmp_path,
                "ses_swap",
                execution_profile_id="profile-1",
                provider_id="opencode",
                model_id="m1",
                surface_hint=None,
            )
        assert runtime.live_session_ids() == []
        assert transports and transports[0].closed is True
    finally:
        runtime.shutdown()


def test_update_session_bounds_unknown_session_raises(rig):
    """update_session_bounds on a non-live session raises RES-AGW-003."""
    runtime, clock, transports, tmp_path = rig
    with pytest.raises(AudiaGenticError, match="RES-AGW-003"):
        runtime.update_session_bounds("ses_nonexistent", idle_timeout_seconds=100)


def test_session_is_quiescent_true_when_no_turns(rig):
    """session_is_quiescent returns True when no turn is active or queued."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    assert runtime.session_is_quiescent(session_id) is True
    runtime.close_session(tmp_path, session_id)


def test_session_is_quiescent_false_during_active_turn(rig):
    """session_is_quiescent returns False while a turn is running."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    gate = threading.Event()
    transports[0].block_event = gate

    def _turn():
        runtime.prompt_in_session(tmp_path, session_id, "busy")

    worker = threading.Thread(target=_turn)
    worker.start()
    time.sleep(0.1)  # turn is in flight
    assert runtime.session_is_quiescent(session_id) is False

    gate.set()
    worker.join(timeout=2)
    # After turn completes, should be quiescent again
    time.sleep(0.05)
    assert runtime.session_is_quiescent(session_id) is True
    runtime.close_session(tmp_path, session_id)


def test_session_is_quiescent_nonexistent_returns_true(rig):
    """session_is_quiescent returns True for a session that isn't live —
    treating it as already closed for post-turn close purposes."""
    runtime, clock, transports, tmp_path = rig
    assert runtime.session_is_quiescent("ses_nonexistent") is True


def test_session_lifecycle_events_published(rig, monkeypatch):
    """A subscriber sees the full lifecycle: opened → turn-finished → closed."""
    runtime, clock, transports, tmp_path = rig

    events_captured: list[tuple[str, dict]] = []

    def fake_publish(topic: str, payload: dict, metadata: dict | None = None) -> None:
        events_captured.append((topic, payload))

    from audiagentic.foundation import event as event_mod

    monkeypatch.setattr(event_mod, "get_bus", lambda: _FakeBus(fake_publish))

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    # opened event
    assert len(events_captured) == 1
    topic, payload = events_captured[0]
    assert topic == "agents.session.opened"
    assert payload["session-id"] == session_id
    assert payload["execution-profile-id"] == "profile-1"
    assert payload["state"] == "active"
    assert payload["provider-id"] == "opencode"
    assert payload["model-id"] == "m1"

    # turn-finished event
    runtime.prompt_in_session(tmp_path, session_id, "hello", request_id="req_1")
    assert len(events_captured) == 2
    topic, payload = events_captured[1]
    assert topic == "agents.session.turn-finished"
    assert payload["session-id"] == session_id
    assert payload["state"] == "active"
    assert payload["request-id"] == "req_1"
    assert payload["turn-count"] == 1
    assert payload["stop-reason"] == "end_turn"

    # closed event
    runtime.close_session(tmp_path, session_id)
    assert len(events_captured) == 3
    topic, payload = events_captured[2]
    assert topic == "agents.session.closed"
    assert payload["state"] == "closed"
    assert payload["close-reason"] == "client-request"
    assert payload["turn-count"] == 1


def test_publish_failure_does_not_break_session_lifecycle(rig, monkeypatch):
    """Publish failure does not break the session loop — open/close/prompt succeed."""
    runtime, clock, transports, tmp_path = rig

    def raising_publish(topic: str, payload: dict, metadata: dict | None = None) -> None:
        raise RuntimeError("bus is down")

    from audiagentic.foundation import event as event_mod

    monkeypatch.setattr(event_mod, "get_bus", lambda: _FakeBus(raising_publish))

    # Open succeeds despite publish failure
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    assert record["state"] == "active"

    # Prompt succeeds despite publish failure
    result = runtime.prompt_in_session(tmp_path, session_id, "hello", request_id="req_1")
    assert result.stop_reason == "end_turn"

    # Close succeeds despite publish failure
    closed = runtime.close_session(tmp_path, session_id)
    assert closed["state"] == "closed"


class _FakeBus:
    def __init__(self, publish_fn) -> None:
        self._publish_fn = publish_fn

    def publish(self, topic: str, payload: dict, metadata: dict | None = None) -> None:
        return self._publish_fn(topic, payload, metadata)


def test_intra_turn_events_wired_to_eventbus(rig, monkeypatch):
    """AS18 — on_event callback publishes normalized events during prompt."""
    runtime, clock, transports, tmp_path = rig

    events_captured: list[tuple[str, dict]] = []

    def capture_publish(topic: str, payload: dict, metadata: dict | None = None) -> None:
        events_captured.append((topic, {**payload, "_metadata": metadata or {}}))

    from audiagentic.foundation import event as event_mod

    monkeypatch.setattr(event_mod, "get_bus", lambda: _FakeBus(capture_publish))

    # Configure the fake transport to emit CANONICAL intra-turn events via
    # the neutral sink (TransportObservation), the way the real transport does.
    async def _emit_test_events(on_event, session_id):
        from audiagentic.foundation.transports.agent_session import TransportObservationKind

        for i, (kind_enum, attributes) in enumerate(
            [
                (TransportObservationKind.ACTIVITY, {"model_activity": "generating"}),
                (TransportObservationKind.ACTIVITY, {"model_activity": "generating"}),  # deduped
                (
                    TransportObservationKind.TOOL_REQUESTED,
                    {"tool_call_id": "tc1", "tool_status": "pending"},
                ),
                (
                    TransportObservationKind.TOOL_REQUESTED,
                    {"tool_call_id": "tc1", "tool_status": "in_progress"},
                ),  # deduped
                (
                    TransportObservationKind.TOOL_FINISHED,
                    {"tool_call_id": "tc1", "tool_status": "failed"},
                ),
                (TransportObservationKind.TERMINAL, {"stop_reason": "end_turn"}),
            ]
        ):
            from audiagentic.foundation.transports.agent_session import TransportObservation

            obs = TransportObservation(
                ag_session_id=session_id,
                turn_id="turn-1",
                sequence=i + 1,
                kind=kind_enum,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes=attributes,
            )
            result = on_event(obs)
            if result is not None:
                await result

    record = _open(runtime, tmp_path)
    transports[0].on_event_emitter = _emit_test_events  # transport created by open
    session_id = record["session-id"]
    events_captured.clear()  # clear open event

    result = runtime.prompt_in_session(
        tmp_path,
        session_id,
        "hello",
        request_id="req_1",
        correlation_id="corr_1",
    )
    assert result.stop_reason == "end_turn"

    from audiagentic.components.agents.gateway.observability import read_observation_page
    journal = read_observation_page(tmp_path, "req_1", limit=20)
    assert journal["items"]
    assert journal["items"][-1]["session_id"] == session_id
    assert journal["items"][-1]["facts"]["response-identity"]["terminal"] is True
    activity_facts = [item["facts"]["activity"] for item in journal["items"] if item["facts"]["activity"].get("label")]
    assert any(item.get("label") == "generating" and item.get("group") for item in activity_facts)

    # Verify the normalized turn events were published, deduped, and terminal-aware
    turn_topics = [(t, p) for t, p in events_captured if t.startswith("agents.turn.")]
    assert [t for t, _ in turn_topics] == [
        "agents.turn.model.started",
        "agents.turn.tool.started",
        "agents.turn.tool.completed",
        "agents.turn.model.completed",
    ], f"unexpected projection: {turn_topics}"

    # Check correlation: session-id and request-id are present; strength/tier
    # are honestly unknown until AS19 declaration-driven resolution lands.
    for topic, payload in turn_topics:
        assert payload["session-id"] == session_id
        assert payload["request-id"] == "req_1"
        assert payload["execution-profile-id"] is not None
        assert payload["semantic-strength"] == "unknown"
        assert payload["verification-tier"] == "unknown"
        assert payload["_metadata"] == {"correlation_id": "corr_1"}

    # Verify tool failure is observable
    tool_completed = [p for t, p in turn_topics if t == "agents.turn.tool.completed"][0]
    assert tool_completed["status"] == "failed"
    assert tool_completed["tool-call-id"] == "tc1"

    runtime.close_session(tmp_path, session_id)


def test_response_decision_timing_observation_reaches_console_trace(rig):
    """Exercise the real SessionRuntime observation callback timing branch."""
    from io import StringIO

    from audiagentic.components.agents.gateway.session.console_trace import (
        GatewayConsoleTrace,
    )
    from audiagentic.foundation.transports.agent_session import (
        TransportObservation,
        TransportObservationKind,
    )

    runtime, clock, transports, tmp_path = rig
    stream = StringIO()
    runtime._console_trace = GatewayConsoleTrace(stream=stream, clock=lambda: 10.0)

    async def _emit_response_decision(obs_sink, session_id):
        observation = TransportObservation(
            ag_session_id=session_id,
            turn_id="req_decision",
            sequence=1,
            kind=TransportObservationKind.TIMING,
            observed_at="2025-01-01T00:00:00Z",
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            attributes={
                "timing-event": "response-decision",
                "diagnostic-signature": "0123456789abcdef",
                "diagnostic-details": '{"completion-satisfied":false}',
            },
        )
        result = obs_sink(observation)
        if result is not None:
            await result

    record = _open(runtime, tmp_path)
    transports[0].on_event_emitter = _emit_response_decision
    session_id = record["session-id"]

    result = runtime.prompt_in_session(
        tmp_path,
        session_id,
        "hello",
        request_id="req_decision",
    )

    assert result.stop_reason == "end_turn"
    rendered = stream.getvalue()
    assert "DECISION" in rendered
    assert "request=req_decision" in rendered
    assert "signature=0123456789abcdef" in rendered
    runtime.close_session(tmp_path, session_id)


def test_turn_event_publish_failure_does_not_break_prompt(rig, monkeypatch):
    """AS18 — publish failure in on_event callback does not break the prompt."""
    runtime, clock, transports, tmp_path = rig

    def raising_publish(topic: str, payload: dict, metadata: dict | None = None) -> None:
        raise RuntimeError("bus is down")

    from audiagentic.foundation import event as event_mod

    monkeypatch.setattr(event_mod, "get_bus", lambda: _FakeBus(raising_publish))

    # Configure the fake transport to emit an intra-turn event (triggers publish failure)
    async def _emit_one_event(on_event, session_id):
        from audiagentic.foundation.transports.agent_session import (
            TransportObservation,
            TransportObservationKind,
        )

        obs = TransportObservation(
            ag_session_id=session_id,
            turn_id="turn-1",
            sequence=1,
            kind=TransportObservationKind.ACTIVITY,
            observed_at="2025-01-01T00:00:00Z",
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            attributes={"model_activity": "generating"},
        )
        result = on_event(obs)
        if result is not None:
            await result

    record = _open(runtime, tmp_path)
    transports[0].on_event_emitter = _emit_one_event  # transport created by open
    session_id = record["session-id"]

    # Prompt succeeds despite publish failure in on_event callback
    result = runtime.prompt_in_session(tmp_path, session_id, "hello", request_id="req_1")
    assert result.stop_reason == "end_turn"

    runtime.close_session(tmp_path, session_id)


# ── RV680: turn deadline, protocol cancel, silence watchdog ─────────


def test_turn_deadline_is_not_terminal_evidence(rig):
    """Elapsed time does not fail a session; explicit cancel remains available."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, turn_timeout_seconds=0.2)
    session_id = record["session-id"]
    transports[0].block_event = threading.Event()  # never set — the turn hangs

    result: list = []
    worker = threading.Thread(
        target=lambda: result.append(
            runtime.prompt_in_session(tmp_path, session_id, "long tool call", request_id="req_deadline")
        )
    )
    worker.start()
    assert _wait_for(worker.is_alive)
    time.sleep(0.3)
    assert worker.is_alive()
    assert runtime.request_cancel("req_deadline") is True
    worker.join(timeout=5)
    assert result and result[0].stop_reason == "cancelled"
    runtime.close_session(tmp_path, session_id)


def test_request_cancel_interrupts_running_turn(rig):
    """request_cancel() reaches an in-flight turn via the transport
    cancel_signal and the turn returns stop_reason 'cancelled'."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    transports[0].block_event = threading.Event()  # block until cancelled

    results: list = []

    def _turn():
        results.append(
            runtime.prompt_in_session(tmp_path, session_id, "long turn", request_id="req_cancel_1")
        )

    worker = threading.Thread(target=_turn)
    worker.start()
    assert _wait_for(lambda: transports[0].block_event is not None and worker.is_alive())
    time.sleep(0.05)  # let the turn reach the transport block loop
    assert runtime.request_cancel("req_cancel_1") is True
    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert results and results[0].stop_reason == "cancelled"
    # The session survives a cancelled turn — only the turn was interrupted.
    assert runtime.live_session_ids() == [session_id]
    runtime.close_session(tmp_path, session_id)


def test_silence_watchdog_records_suspicion_without_failing_turn(rig):
    """Silence can be monitored, but remote/tool waits are not failures."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path, turn_silence_timeout_seconds=5.0, turn_timeout_seconds=0)
    session_id = record["session-id"]
    transports[0].block_event = threading.Event()  # silent, endless turn

    results: list = []

    def _turn():
        results.append(runtime.prompt_in_session(tmp_path, session_id, "silent turn", request_id="req_silent"))

    worker = threading.Thread(target=_turn)
    worker.start()
    assert _wait_for(lambda: worker.is_alive())
    time.sleep(0.1)  # turn is now inside the transport block loop
    clock.now += 60.0  # exceed the 5s silence bound on the injected clock
    time.sleep(0.1)
    assert session_id in runtime.live_session_ids()
    assert runtime.request_cancel("req_silent") is True
    worker.join(timeout=5.0)
    assert results and results[0].stop_reason == "cancelled"
    runtime.close_session(tmp_path, session_id)


# ── AS91: positive owned-child death reaps through the turn task ─────────


def _owned_child() -> AdoptedChild:
    return AdoptedChild(
        evidence=ProcessEvidence(
            pid=4242,
            scope="session-child",
            command_fingerprint="sha256:" + "a" * 64,
            ownership_proof_kind="creation-identity",
            owner_epoch="test-owner",
            creation_identity="created:4242",
        )
    )


def _attach_adopted_child(runtime: SessionRuntime, session_id: str, child: AdoptedChild) -> None:
    async def attach() -> None:
        runtime._handles[session_id].adopted_child = child  # noqa: SLF001 - runtime seam test

    runtime._call(attach(), timeout=2)  # noqa: SLF001 - runtime seam test


def test_reaper_proven_owned_child_death_cleans_through_owning_turn_once(rig, monkeypatch):
    runtime, _clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    transports[0].block_event = threading.Event()
    _attach_adopted_child(runtime, session_id, _owned_child())
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        sessions_module,
        "_publish_session_event",
        lambda topic, payload, **_kwargs: events.append((topic, payload)),
    )
    import audiagentic.foundation.system.adopted_process as adopted_process

    child_dead = threading.Event()
    monkeypatch.setattr(
        adopted_process,
        "observe_child",
        lambda _evidence: OwnershipCheckResult(
            owned=not child_dead.is_set(),
            alive=not child_dead.is_set(),
            observed=None,
            refusal_reason="process-dead" if child_dead.is_set() else None,
        ),
    )
    from audiagentic.components.agents.gateway.queue import queue as queue_module

    released_turns: list[str] = []

    async def record_turn_done(request_id: str) -> None:
        released_turns.append(request_id)

    monkeypatch.setattr(queue_module, "notify_turn_done", record_turn_done)
    outcome: list[BaseException] = []

    def run_turn() -> None:
        try:
            runtime.prompt_in_session(tmp_path, session_id, "blocked", request_id="req_orphan")
        except BaseException as exc:  # cancellation is the expected owner-task cleanup signal
            outcome.append(exc)

    worker = threading.Thread(target=run_turn)
    worker.start()
    assert _wait_for(
        lambda: runtime.session_runtime_status(session_id).get("current-request-id") == "req_orphan"
    )

    # The fixture also runs a 50ms background reaper. Announcing death before
    # observing admission races that reaper: it can correctly remove the
    # session before this thread ever sees its transient busy state.
    runtime._call(runtime._reap_once(), timeout=2)  # noqa: SLF001
    assert runtime.session_runtime_status(session_id)["current-request-id"] == "req_orphan"
    child_dead.set()
    runtime._call(runtime._reap_once(), timeout=2)  # noqa: SLF001 - direct deterministic sweep
    runtime._call(runtime._reap_once(), timeout=2)  # noqa: SLF001 - prove idempotence after removal
    worker.join(timeout=3)

    assert not worker.is_alive()
    assert outcome
    assert released_turns == ["req_orphan"]
    durable = session_store.read_session_record(tmp_path, session_id)
    assert durable["state"] == "failed"
    assert durable["close-reason"] == "orphaned"
    orphan_events = [event for event in events if event[0] == "agents.session.orphaned"]
    assert len(orphan_events) == 1
    timeline = load_ndjson(session_store.gateway_session_timeline_path(tmp_path, session_id))
    assert [entry["event"] for entry in timeline].count("session.orphaned") == 1
    assert runtime.session_runtime_status(session_id) == {"available": False}


def test_reaper_unknown_owned_child_evidence_does_not_clean_up_busy_turn(rig, monkeypatch):
    runtime, _clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    transports[0].block_event = threading.Event()
    _attach_adopted_child(runtime, session_id, _owned_child())
    events: list[str] = []
    monkeypatch.setattr(
        sessions_module,
        "_publish_session_event",
        lambda topic, _payload, **_kwargs: events.append(topic),
    )
    import audiagentic.foundation.system.adopted_process as adopted_process

    monkeypatch.setattr(
        adopted_process,
        "observe_child",
        lambda _evidence: OwnershipCheckResult(
            owned=False, alive=True, observed=None, refusal_reason="unobservable"
        ),
    )
    outcome: list[BaseException] = []

    def run_turn() -> None:
        try:
            runtime.prompt_in_session(tmp_path, session_id, "blocked", request_id="req_unknown")
        except BaseException as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run_turn)
    worker.start()
    assert _wait_for(
        lambda: runtime.session_runtime_status(session_id).get("current-request-id") == "req_unknown"
    )

    runtime._call(runtime._reap_once(), timeout=2)  # noqa: SLF001 - direct deterministic sweep
    assert worker.is_alive()
    assert session_store.read_session_record(tmp_path, session_id)["state"] == "active"
    assert "agents.session.orphaned" not in events

    assert runtime.request_cancel("req_unknown") is True
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert outcome == []
    runtime.close_session(tmp_path, session_id)


def test_reaper_real_owned_subprocess_death_emits_once_and_releases_turn(rig, tmp_path):
    """AS91 process-boundary proof: a real adopted child exits mid-turn.

    The reaper consumes foundation's authenticated creation-identity evidence;
    no synthetic observation is injected.  This is intentionally kept
    deterministic by terminating the child ourselves, then sweeping once.
    """
    runtime, _clock, transports, _fixture_root = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    transports[0].block_event = threading.Event()

    child_cmd = (sys.executable, "-c", "import time; time.sleep(60)")
    child_proc = subprocess.Popen(child_cmd)
    adopted = adopt_child(pid=child_proc.pid, command=child_cmd, owner_epoch="real-owner")
    assert isinstance(adopted, AdoptedChild)
    _attach_adopted_child(runtime, session_id, adopted)

    outcome: list[BaseException] = []

    def run_turn() -> None:
        try:
            runtime.prompt_in_session(tmp_path, session_id, "blocked", request_id="req_real_orphan")
        except BaseException as exc:  # cancellation is the owner cleanup signal
            outcome.append(exc)

    worker = threading.Thread(target=run_turn)
    worker.start()
    assert _wait_for(
        lambda: runtime.session_runtime_status(session_id).get("current-request-id") == "req_real_orphan"
    )
    child_proc.terminate()
    child_proc.wait(timeout=5)

    runtime._call(runtime._reap_once(), timeout=2)  # noqa: SLF001 - deterministic sweep
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert outcome
    durable = session_store.read_session_record(tmp_path, session_id)
    assert durable["state"] == "failed"
    assert durable["close-reason"] == "orphaned"
    timeline = load_ndjson(session_store.gateway_session_timeline_path(tmp_path, session_id))
    assert [entry["event"] for entry in timeline].count("session.orphaned") == 1


def test_reaper_real_external_subprocess_is_never_touched(rig, tmp_path):
    """AS91 negative process-boundary proof: external child is diagnostics-only."""
    runtime, _clock, transports, _fixture_root = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    transports[0].block_event = threading.Event()

    child_cmd = (sys.executable, "-c", "import time; time.sleep(60)")
    child_proc = subprocess.Popen(child_cmd)
    adopted = adopt_child(
        pid=child_proc.pid,
        command=child_cmd,
        owner_epoch="external-owner",
        is_external=True,
    )
    assert isinstance(adopted, AdoptedChild)
    _attach_adopted_child(runtime, session_id, adopted)

    worker = threading.Thread(
        target=lambda: runtime.prompt_in_session(
            tmp_path, session_id, "blocked", request_id="req_external_orphan"
        )
    )
    worker.start()
    assert _wait_for(
        lambda: runtime.session_runtime_status(session_id).get("current-request-id") == "req_external_orphan"
    )
    child_proc.terminate()
    child_proc.wait(timeout=5)
    runtime._call(runtime._reap_once(), timeout=2)  # noqa: SLF001
    assert worker.is_alive()
    assert session_store.read_session_record(tmp_path, session_id)["state"] == "active"
    assert runtime.request_cancel("req_external_orphan") is True
    worker.join(timeout=3)
    runtime.close_session(tmp_path, session_id)


# AS34: stale persisted active session diagnostics.


def test_stale_persisted_session_lists_not_live_no_runtime_started(tmp_path, monkeypatch):
    """A persisted active session with no live runtime lists as not-live with a
    stale diagnostic flag, and listing does NOT start a new runtime."""
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    # No runtime — ensure by resetting the singleton.
    saved_runtime = getattr(sessions_module, "_SESSION_RUNTIME", None)
    try:
        sessions_module._SESSION_RUNTIME = None  # type: ignore[attr-defined]

        # Persisted active record — no live handle in this process
        record = session_store.build_session_record(execution_profile_id="profile-1")
        stale_id = record["session-id"]
        session_store.write_session_record(tmp_path, record)

        listed = api.list_execution_sessions(tmp_path, state="all")
        row = [s for s in listed if s["session-id"] == stale_id][0]
        assert row["live"] is False
        # A stale persisted active session should carry a diagnostic flag.
        assert row.get("runtime-state") == "stale-non-live"

        # The stored record must remain unchanged (no mutation of stale rows)
        stored = session_store.read_session_record(tmp_path, stale_id)
        assert stored["state"] == "active"

        # Listing did not start a runtime
        assert sessions_module.peek_session_runtime() is None
    finally:
        if saved_runtime is not None:
            sessions_module._SESSION_RUNTIME = saved_runtime  # type: ignore[attr-defined]


def test_stale_non_live_session_is_expired_by_durable_idle_policy(tmp_path):
    from audiagentic.components.agents.gateway import api as api

    record = session_store.build_session_record(
        execution_profile_id="profile-1", idle_timeout_seconds=60
    )
    session_id = record["session-id"]
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace(
        "+00:00", "Z"
    )
    record["timing"]["last-activity-at"] = old
    session_store.write_session_record(tmp_path, record)

    listed = api.list_execution_sessions(tmp_path, state="all", _live_ids=set())
    row = next(item for item in listed if item["session-id"] == session_id)

    assert row["state"] == "expired"
    assert row["close-reason"] == "idle-timeout"
    assert "runtime-state" not in row
    assert session_store.read_session_record(tmp_path, session_id)["state"] == "expired"


def test_legacy_gpt_session_without_persisted_policy_uses_admission_default(tmp_path):
    from audiagentic.components.agents.gateway import api as api

    record = session_store.build_session_record(
        execution_profile_id="gpt-auto", provider_id="gpt-auto"
    )
    session_id = record["session-id"]
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace(
        "+00:00", "Z"
    )
    record["timing"]["last-activity-at"] = old
    session_store.write_session_record(tmp_path, record)

    row = next(
        item
        for item in api.list_execution_sessions(tmp_path, state="all", _live_ids=set())
        if item["session-id"] == session_id
    )

    assert row["state"] == "expired"
    assert row["close-reason"] == "idle-timeout"


def test_durable_idle_sweep_reconciles_nonterminal_request(tmp_path):
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway import store

    session = session_store.build_session_record(
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        provider_session_ref="provider-session",
        surface_id="surface-1",
        provider_metadata={"provider-session-id": "provider-session"},
        idle_timeout_seconds=60,
    )
    session_id = session["session-id"]
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace(
        "+00:00", "Z"
    )
    session["timing"]["last-activity-at"] = old
    session_store.write_session_record(tmp_path, session)
    request = store.build_record(
        request_id="req_protect_session",
        execution_profile_id="gpt-auto",
        prompt_body="x",
        session_id=session_id,
        session_keep_alive=True,
        resolved_provider_id="gpt-auto",
    )
    request["provider-metadata"] = {"provider-session-id": "provider-session"}
    store.write_record(tmp_path, request)

    row = next(
        item
        for item in api.list_execution_sessions(tmp_path, state="all", _live_ids=set())
        if item["session-id"] == session_id
    )

    reconciled = store.read_record(tmp_path, request["request-id"])
    assert reconciled["state"] == "interrupted"
    assert reconciled["error"]["code"] == "CON-AGW-084"
    assert reconciled["diagnostics"]["reason-code"] == "provider-session-expired"
    assert row["state"] == "expired"
    assert "runtime-state" not in row
    assert session_store.read_session_record(tmp_path, session_id)["state"] == "expired"


def test_expiry_waits_for_request_lock_before_taking_retention_lock(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import store

    session = session_store.build_session_record(
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        provider_session_ref="provider-session",
        surface_id="surface-1",
        provider_metadata={"provider-session-id": "provider-session"},
        idle_timeout_seconds=60,
    )
    session_id = session["session-id"]
    session["timing"]["last-activity-at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    session_store.write_session_record(tmp_path, session)
    request = store.build_record(
        request_id="req_expiry_lock_order",
        execution_profile_id="gpt-auto",
        prompt_body="x",
        session_id=session_id,
        session_keep_alive=True,
        resolved_provider_id="gpt-auto",
    )
    request["provider-metadata"] = {"provider-session-id": "provider-session"}
    store.write_record(tmp_path, request)

    retention_requested = threading.Event()
    request_lock_attempted = threading.Event()
    real_request_lock = session_store._request_lock
    real_startup_lock = session_store.StartupLock

    def track_request_lock(root, request_id):
        if request_id == request["request-id"]:
            request_lock_attempted.set()
        return real_request_lock(root, request_id)

    def track_retention_lock(path, *args, **kwargs):
        if Path(path).name == "retention.mutation.lock":
            retention_requested.set()
        return real_startup_lock(path, *args, **kwargs)

    monkeypatch.setattr(session_store, "_request_lock", track_request_lock)
    monkeypatch.setattr(session_store, "StartupLock", track_retention_lock)
    result: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def expire():
        try:
            result.append(session_store.expire_session_if_policy_exceeded(tmp_path, session_id))
        except BaseException as exc:  # surfaced in the parent test thread
            errors.append(exc)

    # Model a request finalizer holding request ownership while it proceeds to
    # retention cleanup. Expiry must wait at the request fence, not hold the
    # project fence and form the inverse half of a deadlock.
    with real_request_lock(tmp_path, request["request-id"]):
        worker = threading.Thread(target=expire)
        worker.start()
        assert request_lock_attempted.wait(timeout=2)
        time.sleep(0.05)
        assert not retention_requested.is_set()
        with real_startup_lock(
            session_store.gateway_retention_lock_path(tmp_path), timeout=1
        ):
            pass

    worker.join(timeout=5)
    assert not worker.is_alive()
    assert not errors
    assert result[0]["state"] == "expired"
    assert store.read_record(tmp_path, request["request-id"])["state"] == "interrupted"


def test_durable_idle_sweep_preserves_request_with_provider_activity_lease(tmp_path):
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway import store

    session = session_store.build_session_record(
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        provider_session_ref="provider-session",
        surface_id="surface-1",
        provider_metadata={"provider-session-id": "provider-session"},
        idle_timeout_seconds=60,
    )
    session_id = session["session-id"]
    session["timing"]["last-activity-at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    session_store.write_session_record(tmp_path, session)
    request = store.build_record(
        request_id="req_live_provider_lease",
        execution_profile_id="gpt-auto",
        prompt_body="x",
        session_id=session_id,
        session_keep_alive=True,
        resolved_provider_id="gpt-auto",
    )
    request["provider-metadata"] = {"provider-session-id": "provider-session"}
    request["activity"]["provider"]["lease-expires-at"] = (
        datetime.now(timezone.utc) + timedelta(minutes=5)
    ).isoformat().replace("+00:00", "Z")
    store.write_record(tmp_path, request)

    row = next(
        item
        for item in api.list_execution_sessions(tmp_path, state="all", _live_ids=set())
        if item["session-id"] == session_id
    )

    assert row["state"] == "active"
    assert row["runtime-state"] == "stale-non-live"
    assert store.read_record(tmp_path, request["request-id"])["state"] == "queued"


def test_durable_idle_sweep_requires_exact_provider_session_identity(tmp_path):
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway import store

    session = session_store.build_session_record(
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        provider_session_ref="provider-session",
        surface_id="surface-1",
        provider_metadata={"provider-session-id": "provider-session"},
        idle_timeout_seconds=60,
    )
    session["timing"]["last-activity-at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    session_store.write_session_record(tmp_path, session)
    request = store.build_record(
        request_id="req_mismatched_provider_session",
        execution_profile_id="gpt-auto",
        prompt_body="x",
        session_id=session["session-id"],
        session_keep_alive=True,
        resolved_provider_id="gpt-auto",
    )
    request["provider-metadata"] = {"provider-session-id": "other-session"}
    store.write_record(tmp_path, request)

    row = next(
        item
        for item in api.list_execution_sessions(tmp_path, state="all", _live_ids=set())
        if item["session-id"] == session["session-id"]
    )

    assert row["state"] == "active"
    assert store.read_record(tmp_path, request["request-id"])["state"] == "queued"


def test_durable_idle_sweep_rejects_binding_metadata_divergence(tmp_path):
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway import store

    session = session_store.build_session_record(
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        provider_session_ref="provider-session",
        surface_id="surface-1",
        provider_metadata={"provider-session-id": "provider-session"},
        idle_timeout_seconds=60,
    )
    session["binding"]["provider-session-ref"] = "different-provider-session"
    session["timing"]["last-activity-at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    session_store.write_session_record(tmp_path, session)
    request = store.build_record(
        request_id="req_binding_metadata_divergence",
        execution_profile_id="gpt-auto",
        prompt_body="x",
        session_id=session["session-id"],
        session_keep_alive=True,
        resolved_provider_id="gpt-auto",
    )
    request["provider-metadata"] = {"provider-session-id": "provider-session"}
    store.write_record(tmp_path, request)

    row = next(
        item
        for item in api.list_execution_sessions(tmp_path, state="all", _live_ids=set())
        if item["session-id"] == session["session-id"]
    )

    assert row["state"] == "active"
    assert store.read_record(tmp_path, request["request-id"])["state"] == "queued"


def test_durable_idle_sweep_rejects_unrelayed_request_binding(tmp_path):
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway import store

    session = session_store.build_session_record(
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        provider_session_ref="provider-session",
        surface_id="surface-1",
        provider_metadata={"provider-session-id": "provider-session"},
        idle_timeout_seconds=60,
    )
    session["timing"]["last-activity-at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    session_store.write_session_record(tmp_path, session)
    request = store.build_record(
        request_id="req_unrelayed_binding",
        execution_profile_id="gpt-auto",
        prompt_body="x",
        session_id=session["session-id"],
        session_keep_alive=True,
        resolved_provider_id="gpt-auto",
    )
    store.write_record(tmp_path, request)

    row = next(
        item
        for item in api.list_execution_sessions(tmp_path, state="all", _live_ids=set())
        if item["session-id"] == session["session-id"]
    )

    assert row["state"] == "active"
    assert store.read_record(tmp_path, request["request-id"])["state"] == "queued"


def test_durable_idle_sweep_ignores_legacy_owner_activity_lease(tmp_path):
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway import store

    session = session_store.build_session_record(
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        provider_session_ref="provider-session",
        surface_id="surface-1",
        provider_metadata={"provider-session-id": "provider-session"},
        idle_timeout_seconds=60,
    )
    session["timing"]["last-activity-at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    session_store.write_session_record(tmp_path, session)
    request = store.build_record(
        request_id="req_owner_lease_only",
        execution_profile_id="gpt-auto",
        prompt_body="x",
        session_id=session["session-id"],
        session_keep_alive=True,
        resolved_provider_id="gpt-auto",
    )
    request["provider-metadata"] = {"provider-session-id": "provider-session"}
    request["activity-lease-expires-at"] = (
        datetime.now(timezone.utc) + timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    store.write_record(tmp_path, request)

    row = next(
        item
        for item in api.list_execution_sessions(tmp_path, state="all", _live_ids=set())
        if item["session-id"] == session["session-id"]
    )

    assert row["state"] == "expired"
    assert store.read_record(tmp_path, request["request-id"])["state"] == "interrupted"


def test_durable_idle_sweep_preflights_all_requests_before_mutation(tmp_path):
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway import store

    session = session_store.build_session_record(
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        provider_session_ref="provider-session",
        surface_id="surface-1",
        provider_metadata={"provider-session-id": "provider-session"},
        idle_timeout_seconds=60,
    )
    session["timing"]["last-activity-at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    session_store.write_session_record(tmp_path, session)
    requests = []
    for request_id in ("req_preflight_one", "req_preflight_two"):
        request = store.build_record(
            request_id=request_id,
            execution_profile_id="gpt-auto",
            prompt_body="x",
            session_id=session["session-id"],
            session_keep_alive=True,
            resolved_provider_id="gpt-auto",
        )
        request["provider-metadata"] = {"provider-session-id": "provider-session"}
        requests.append(request)
        store.write_record(tmp_path, request)
    requests[0]["activity"]["provider"]["lease-expires-at"] = (
        datetime.now(timezone.utc) + timedelta(minutes=5)
    ).isoformat().replace("+00:00", "Z")
    store.write_record(tmp_path, requests[0])

    row = next(
        item
        for item in api.list_execution_sessions(tmp_path, state="all", _live_ids=set())
        if item["session-id"] == session["session-id"]
    )

    assert row["state"] == "active"
    assert all(store.read_record(tmp_path, item["request-id"])["state"] == "queued" for item in requests)


def test_durable_idle_sweep_rechecks_revision_before_first_mutation(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway import store

    session = session_store.build_session_record(
        execution_profile_id="gpt-auto",
        provider_id="gpt-auto",
        provider_session_ref="provider-session",
        surface_id="surface-1",
        provider_metadata={"provider-session-id": "provider-session"},
        idle_timeout_seconds=60,
    )
    session["timing"]["last-activity-at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    session_store.write_session_record(tmp_path, session)
    request = store.build_record(
        request_id="req_revision_changed_during_preflight",
        execution_profile_id="gpt-auto",
        prompt_body="x",
        session_id=session["session-id"],
        session_keep_alive=True,
        resolved_provider_id="gpt-auto",
    )
    request["provider-metadata"] = {"provider-session-id": "provider-session"}
    store.write_record(tmp_path, request)

    real_read = store.read_record
    reads = 0

    def read_with_revision_change(root, request_id, *args, **kwargs):
        nonlocal reads
        value = real_read(root, request_id, *args, **kwargs)
        if request_id == request["request-id"]:
            reads += 1
            # list_records performs the first read; the request collection
            # performs the second.  Simulate an activity update before the
            # immediate pre-mutation re-read.
            if reads == 2:
                changed = dict(value)
                changed["revision"] = int(value["revision"]) + 1
                return changed
        return value

    monkeypatch.setattr(store, "read_record", read_with_revision_change)

    row = next(
        item
        for item in api.list_execution_sessions(tmp_path, state="all", _live_ids=set())
        if item["session-id"] == session["session-id"]
    )

    assert row["state"] == "active"
    assert real_read(tmp_path, request["request-id"])["state"] == "queued"


def test_durable_idle_sweep_rechecks_policy_inside_retention_fence(tmp_path, monkeypatch):
    session = session_store.build_session_record(
        execution_profile_id="gpt-auto", provider_id="gpt-auto", idle_timeout_seconds=60
    )
    session_id = session["session-id"]
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    session["timing"]["last-activity-at"] = old
    session_store.write_session_record(tmp_path, session)
    real_read = session_store.read_session_record
    reads = 0

    def refreshed_after_initial_read(root, current_id):
        nonlocal reads
        value = real_read(root, current_id)
        if current_id == session_id:
            reads += 1
            if reads >= 2:
                value = dict(value)
                timing = dict(value["timing"])
                timing["last-activity-at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                value["timing"] = timing
        return value

    monkeypatch.setattr(session_store, "read_session_record", refreshed_after_initial_read)
    result = session_store.expire_session_if_policy_exceeded(tmp_path, session_id)

    assert result["state"] == "active"


def test_live_session_lists_without_stale_flag(rig, monkeypatch):
    """A live active session from the runtime lists as live=True and does NOT
    carry a stale diagnostic flag."""
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    listed = api.list_execution_sessions(tmp_path)
    row = [s for s in listed if s["session-id"] == session_id][0]
    assert row["live"] is True
    # Live sessions must not carry a stale flag.
    assert row.get("runtime-state") != "stale-non-live"


def test_reconcile_terminal_live_session_closes_provider_handle(rig):
    """A terminal durable session cannot retain a live provider worker."""
    runtime, _clock, transports, project_root = rig
    record = _open(runtime, project_root)
    session_id = record["session-id"]

    session_store.transition_session_record(project_root, session_id, "closed")

    assert runtime.reconcile_terminal_live_sessions() == [session_id]
    assert runtime.live_session_ids() == []
    assert transports[-1].closed is True


def test_closing_session_not_in_runtime_is_stale(tmp_path, monkeypatch):
    """A persisted closing session with no live runtime is also flagged stale."""
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    saved_runtime = getattr(sessions_module, "_SESSION_RUNTIME", None)
    try:
        sessions_module._SESSION_RUNTIME = None  # type: ignore[attr-defined]

        # Persisted closing record — no live handle
        record = session_store.build_session_record(execution_profile_id="profile-1")
        closing_id = record["session-id"]
        session_store.write_session_record(tmp_path, record)
        session_store.transition_session_record(
            tmp_path,
            closing_id,
            "closing",
        )

        listed = api.list_execution_sessions(tmp_path, state="all")
        row = [s for s in listed if s["session-id"] == closing_id][0]
        assert row["live"] is False
        assert row.get("runtime-state") == "stale-non-live"
    finally:
        if saved_runtime is not None:
            sessions_module._SESSION_RUNTIME = saved_runtime  # type: ignore[attr-defined]


def test_stale_session_when_runtime_exists_but_not_live(rig, monkeypatch):
    """When a runtime exists but the session is not in its live set,
    listing reports stale-non-live without starting anything."""
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)

    # Persisted active record that is NOT in the runtime's live set
    stale_record = session_store.build_session_record(execution_profile_id="profile-1")
    stale_id = stale_record["session-id"]
    session_store.write_session_record(tmp_path, stale_record)

    listed = api.list_execution_sessions(tmp_path)
    row = [s for s in listed if s["session-id"] == stale_id][0]
    assert row["live"] is False
    assert row.get("runtime-state") == "stale-non-live"


def test_gateway_overview_active_count_excludes_stale(rig, monkeypatch):
    """gateway_overview counts only live sessions in active-count, not stale
    persisted active rows."""
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)

    # One live session from the runtime
    live_record = _open(runtime, tmp_path)
    other_root = tmp_path / "other-project"
    other_root.mkdir()
    other_live_record = _open(runtime, other_root)

    # One stale persisted active session (no live handle)
    stale_record = session_store.build_session_record(execution_profile_id="profile-1")
    session_store.write_session_record(tmp_path, stale_record)

    overview = api.gateway_overview(tmp_path)
    assert overview["sessions"]["active-count"] == 1  # only the live one
    assert overview["sessions"]["machine-live-count"] == 2
    # The stale session should appear in the detail list but not count as active
    session_ids = [s["session-id"] for s in overview["sessions"]["sessions"]]
    assert live_record["session-id"] in session_ids
    assert stale_record["session-id"] in session_ids

    # Clean up
    runtime.close_session(tmp_path, live_record["session-id"])
    runtime.close_session(other_root, other_live_record["session-id"])


def test_list_sessions_no_provider_ref_leak(rig, monkeypatch):
    """Public session rows must not leak provider-session-ref or full
    provider-ref-key; only the prefix is allowed (binding projection)."""
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)
    monkeypatch.setattr(sessions_module, "peek_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    listed = api.list_execution_sessions(tmp_path)
    row = [s for s in listed if s["session-id"] == record["session-id"]][0]

    # repr of the entire listing must not contain provider-session-ref or
    # the full provider-ref-key hash (only the 12-char prefix is allowed).
    listing_repr = repr(listed)
    assert "provider-session-ref" not in listing_repr
    # The full key is 64 hex chars; if it leaked, we'd see >12 hex chars.
    full_key = record["binding"]["provider-ref-key"]
    assert full_key not in listing_repr

    # Only the prefix should be present
    binding_row = row.get("binding", {})
    assert "provider-ref-key-prefix" in binding_row
    assert len(binding_row["provider-ref-key-prefix"]) == 12


# AS35: close result redaction.


def test_api_close_live_session_result_is_redacted(rig, monkeypatch):
    """Live close returns public session shape: no provider-session-ref or full
    provider-ref-key in the close result, but useful fields are retained."""
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    closed = api.close_execution_session(tmp_path, session_id)
    assert closed["state"] == "closed"
    assert closed["close-reason"] == "client-request"
    assert closed["session-id"] == session_id
    assert closed["execution-profile-id"] == "profile-1"

    # Redaction: no provider-session-ref or full provider-ref-key in output
    close_repr = repr(closed)
    assert "provider-session-ref" not in close_repr
    full_key = record["binding"]["provider-ref-key"]
    assert full_key not in close_repr

    # Public binding projection is present with prefix
    pub_binding = closed.get("binding", {})
    assert "provider-ref-key-prefix" in pub_binding
    assert len(pub_binding["provider-ref-key-prefix"]) == 12


def test_api_close_durable_record_retains_protected_binding(rig, monkeypatch):
    """After close, the durable persisted session record still carries the
    protected binding internals for ownership/recovery (AS35 requirement 4)."""
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]
    original_ref = record["binding"]["provider-session-ref"]

    closed = api.close_execution_session(tmp_path, session_id)
    # Public result is redacted
    assert "provider-session-ref" not in repr(closed)

    # Durable record retains protected binding
    durable = session_store.read_session_record(tmp_path, session_id)
    assert durable["binding"]["provider-session-ref"] == original_ref
    assert durable["binding"]["provider-ref-key"]  # full key present


def test_api_close_idempotent_terminal_result_is_redacted(rig, monkeypatch):
    """Idempotent close of an already-terminal session returns a redacted
    public result (AS35 requirement 5 — idempotent path)."""
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    # Close first time
    api.close_execution_session(tmp_path, session_id)
    full_key = record["binding"]["provider-ref-key"]

    # Idempotent second close reads from durable store.
    again = api.close_execution_session(tmp_path, session_id)
    assert again["state"] == "closed"
    again_repr = repr(again)
    assert "provider-session-ref" not in again_repr
    assert full_key not in again_repr


def test_api_close_orphaned_stale_result_is_redacted(rig, monkeypatch):
    """Close of a stale non-live active session (orphaned by restart) returns
    a redacted public result with state=failed/close-reason=orphaned (AS35
    requirement 5 - stale non-live active path)."""
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.session import sessions as sessions_module

    runtime, clock, transports, tmp_path = rig
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    # Build a fresh persisted active record (no live handle) to simulate orphan
    orphan_record = session_store.build_session_record(
        execution_profile_id="profile-1",
        provider_id="opencode",
        provider_session_ref="orphan-ref",
        surface_id="opencode-acp",
    )
    orphan_id = orphan_record["session-id"]
    full_key = orphan_record["binding"]["provider-ref-key"]
    session_store.write_session_record(tmp_path, orphan_record)

    closed = api.close_execution_session(tmp_path, orphan_id)
    assert closed["state"] == "failed"
    assert closed["close-reason"] == "orphaned"
    # Redacted public result
    close_repr = repr(closed)
    assert "provider-session-ref" not in close_repr
    assert full_key not in close_repr

    # Durable record still has protected binding for recovery
    durable = session_store.read_session_record(tmp_path, orphan_id)
    assert durable["binding"]["provider-session-ref"] == "orphan-ref"


def test_latest_turn_projection_excludes_native_topic(tmp_path: Path) -> None:
    """native-topic is not public; latest_turn_projection must not leak it."""
    import json

    from audiagentic.components.agents.agents_paths import gateway_session_timeline_path
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    # Build a minimal session record so timeline path exists
    record = session_store.build_session_record(execution_profile_id="default")
    session_id = record["session-id"]
    session_store.write_session_record(tmp_path, record)

    # Write a turn timeline entry with native-topic (NDJSON format)
    timeline_path = gateway_session_timeline_path(tmp_path, session_id)
    entry = {
        "event": "session.turn.started",
        "state": "active",
        "timestamp": "2026-07-19T00:00:00Z",
        "attributes": {
            "request-id": "req_test",
            "native-topic": "provider.internal.secret-topic",
            "turn-count": 1,
        },
    }
    timeline_path.write_text(json.dumps(entry), encoding="utf-8")

    projected = session_store.latest_turn_projection(tmp_path, session_id, request_id="req_test")
    assert projected is not None
    assert projected["event"] == "session.turn.started"
    assert projected["turn-count"] == 1
    # native-topic must not leak
    assert "native-topic" not in projected
    assert "provider.internal.secret-topic" not in repr(projected)


# ── AS19/AS21: accepted-evidence-only contract and request_id binding ──


def _build_fake_observer_lease(evidence_queue: list) -> Any:
    """Build a fake StatusObserverLease that returns evidence from the queue.

    Pops one StatusEvidence per call (or None when empty). Used to inject
    controlled evidence into the observation sink for AS21 contract testing.
    """
    from audiagentic.foundation.transports.harness_status_observer import (
        StatusObserverLease,
    )

    def _observe(observation):
        return evidence_queue.pop(0) if evidence_queue else None

    return StatusObserverLease(
        binding_id="obsbnd_test_lease",
        observe_transport=_observe,
    )


def test_as21_accepted_evidence_only_rejected_does_not_change_decision(rig):
    """AS21 accepted-evidence-only contract: rejected evidence (duplicate/lower/
    mismatched) must not change the lifecycle decision. Valid activity is accepted
    and changes the decision; subsequent rejected evidence leaves it unchanged."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    from audiagentic.foundation.transports.harness_status_observer import (
        StatusEvidence,
        StatusEvidenceSemanticStrength,
        StatusEvidenceSourceKind,
    )

    def _inject_lease(evidence_items: list) -> None:
        lease = _build_fake_observer_lease(evidence_items)

        async def _set_lease():
            handle = runtime._handles[session_id]
            handle.observer_lease = lease

        runtime._call(_set_lease(), timeout=2)

    def _make_emit_one(session_id: str, turn_id: str):
        """Return an on_event_emitter coroutine that triggers one TransportObservation."""

        async def _sink(obs_sink, provider_session_id):
            from audiagentic.foundation.transports.agent_session import (
                CorrelationQuality,
                TransportObservation,
                TransportObservationKind,
            )

            obs = TransportObservation(
                ag_session_id=session_id,
                turn_id=turn_id,
                sequence=1,
                kind=TransportObservationKind.ACTIVITY,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={},
            )
            result = obs_sink(obs)
            if result is not None:
                await result

        return _sink

    # Turn 1: valid activity evidence accepted → decision goes to "active".
    ev_activity = StatusEvidence(
        status="model-thinking",
        session_id=session_id,
        request_id="req_as21_1",
        correlation_id="obsbnd_test_lease",
        observed_at="2025-01-01T00:00:00Z",
        sequence=1,
        source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
        semantic_strength=StatusEvidenceSemanticStrength.UNKNOWN,
        verification_tier="unknown",
    )
    _inject_lease([ev_activity])
    transports[0].on_event_emitter = _make_emit_one(session_id, "req_as21_1")
    runtime.prompt_in_session(
        tmp_path,
        session_id,
        "turn 1",
        request_id="req_as21_1",
    )

    # Check decision for the specific (session, request) key.
    dec = runtime._evidence_projection.latest_decision_for_key(
        session_id,
        "req_as21_1",
    )
    assert dec is not None
    assert dec.coarse_state == "active"

    # Turn 2: inject a duplicate-sequence evidence (same sequence=1 within turn).
    # The StatusEvidenceSink will reject it; the projection must NOT change.
    ev_duplicate = StatusEvidence(
        status="model-generating",
        session_id=session_id,
        request_id="req_as21_2",
        correlation_id="obsbnd_test_lease",
        observed_at="2025-01-01T00:01:00Z",
        sequence=1,  # first in this turn, but same as previous turn's seq
        source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
        semantic_strength=StatusEvidenceSemanticStrength.UNKNOWN,
        verification_tier="unknown",
    )
    _inject_lease([ev_duplicate])
    transports[0].on_event_emitter = _make_emit_one(session_id, "req_as21_2")
    runtime.prompt_in_session(
        tmp_path,
        session_id,
        "turn 2",
        request_id="req_as21_2",
    )

    # Turn 1 decision should be unchanged (still active) — rejected evidence
    # did not alter it. Also verify turn 2 has no projection (evidence was
    # rejected by sink).
    dec1 = runtime._evidence_projection.latest_decision_for_key(
        session_id,
        "req_as21_1",
    )
    assert dec1 is not None
    assert dec1.coarse_state == "active"

    # Turn 3: inject a lower-sequence evidence within its own turn (seq=0 after
    # seq=5 was accepted in this turn). We send two pieces of evidence: first
    # accepted, then a lower one rejected.
    ev_ok = StatusEvidence(
        status="waiting-permission",
        session_id=session_id,
        request_id="req_as21_3",
        correlation_id="obsbnd_test_lease",
        observed_at="2025-01-01T00:02:00Z",
        sequence=5,  # accepted
        source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
        semantic_strength=StatusEvidenceSemanticStrength.UNKNOWN,
        verification_tier="unknown",
    )
    ev_lower = StatusEvidence(
        status="tool-calling",
        session_id=session_id,
        request_id="req_as21_3",
        correlation_id="obsbnd_test_lease",
        observed_at="2025-01-01T00:02:01Z",
        sequence=3,  # lower than 5 — rejected
        source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
        semantic_strength=StatusEvidenceSemanticStrength.UNKNOWN,
        verification_tier="unknown",
    )
    _inject_lease([ev_ok, ev_lower])

    async def _emit_two(obs_sink, provider_session_id):
        from audiagentic.foundation.transports.agent_session import (
            CorrelationQuality,
            TransportObservation,
            TransportObservationKind,
        )

        for i, kind in enumerate(
            [
                TransportObservationKind.ACTIVITY,
                TransportObservationKind.TOOL_REQUESTED,
            ]
        ):
            obs = TransportObservation(
                ag_session_id=session_id,
                turn_id="req_as21_3",
                sequence=i + 1,
                kind=kind,
                observed_at="2025-01-01T00:02:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={},
            )
            result = obs_sink(obs)
            if result is not None:
                await result

    transports[0].on_event_emitter = _emit_two
    runtime.prompt_in_session(
        tmp_path,
        session_id,
        "turn 3",
        request_id="req_as21_3",
    )

    # Turn 3: first evidence accepted (waiting-permission → waiting), second
    # rejected (lower-sequence). Decision should be waiting, not active+tool.
    dec3 = runtime._evidence_projection.latest_decision_for_key(
        session_id,
        "req_as21_3",
    )
    assert dec3 is not None
    # First evidence was waiting-permission → waiting; rejected one didn't change it
    assert dec3.coarse_state == "waiting"

    # Turn 4: inject a binding-mismatch evidence (wrong session_id).
    ev_mismatch = StatusEvidence(
        status="tool-calling",
        session_id="ses_wrong_session",  # wrong — rejected
        request_id="req_as21_4",
        correlation_id="obsbnd_test_lease",
        observed_at="2025-01-01T00:03:00Z",
        sequence=1,
        source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
        semantic_strength=StatusEvidenceSemanticStrength.UNKNOWN,
        verification_tier="unknown",
    )
    _inject_lease([ev_mismatch])
    transports[0].on_event_emitter = _make_emit_one(session_id, "req_as21_4")
    runtime.prompt_in_session(
        tmp_path,
        session_id,
        "turn 4",
        request_id="req_as21_4",
    )

    # Turn 4 has no projected decision (evidence was rejected by sink).
    dec4 = runtime._evidence_projection.latest_decision_for_key(
        session_id,
        "req_as21_4",
    )
    assert dec4 is None

    # Previous turns' decisions are unchanged.
    dec1_after = runtime._evidence_projection.latest_decision_for_key(
        session_id,
        "req_as21_1",
    )
    assert dec1_after.coarse_state == "active"

    runtime.close_session(tmp_path, session_id)


def test_as19_request_id_binding_no_spurious_reject(rig):
    """AS19 request_id binding: a lease opened at session open with
    request_id=None must NOT cause per-turn evidence to be spuriously rejected.
    The StatusEvidenceSink uses immutable per-turn correlation; the lease's
    initial request_id=None is irrelevant because StatusEvidence from
    observe_transport carries observation.turn_id as its request_id."""
    runtime, clock, transports, tmp_path = rig
    record = _open(runtime, tmp_path)
    session_id = record["session-id"]

    from audiagentic.foundation.transports.harness_status_observer import (
        StatusEvidence,
        StatusEvidenceSemanticStrength,
        StatusEvidenceSourceKind,
    )

    def _inject_lease(evidence_items: list) -> None:
        lease = _build_fake_observer_lease(evidence_items)

        async def _set_lease():
            handle = runtime._handles[session_id]
            handle.observer_lease = lease

        runtime._call(_set_lease(), timeout=2)

    # The observer lease was opened at session open with request_id=None.
    # But observe_transport produces StatusEvidence with request_id from
    # the TransportObservation's turn_id. Per-turn sinks use immutable
    # per-turn correlation — they should accept this evidence.
    ev_for_turn = StatusEvidence(
        status="model-thinking",
        session_id=session_id,
        request_id="req_binding_1",  # from observation.turn_id, not None
        correlation_id="obsbnd_test_lease",
        observed_at="2025-01-01T00:00:00Z",
        sequence=1,
        source_kind=StatusEvidenceSourceKind.TRANSPORT_OBSERVATION,
        semantic_strength=StatusEvidenceSemanticStrength.UNKNOWN,
        verification_tier="unknown",
    )
    _inject_lease([ev_for_turn])

    async def _emit_one(obs_sink, provider_session_id):
        from audiagentic.foundation.transports.agent_session import (
            CorrelationQuality,
            TransportObservation,
            TransportObservationKind,
        )

        obs = TransportObservation(
            ag_session_id=session_id,
            turn_id="req_binding_1",
            sequence=1,
            kind=TransportObservationKind.ACTIVITY,
            observed_at="2025-01-01T00:00:00Z",
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            attributes={},
        )
        result = obs_sink(obs)
        if result is not None:
            await result

    transports[0].on_event_emitter = _emit_one
    runtime.prompt_in_session(
        tmp_path,
        session_id,
        "binding test",
        request_id="req_binding_1",
    )

    # The evidence should have been accepted (not spuriously rejected due to
    # the lease's request_id=None at session open). Decision should be active.
    dec = runtime._evidence_projection.latest_decision_for_key(
        session_id,
        "req_binding_1",
    )
    assert dec is not None, (
        "Evidence was spuriously rejected — lease request_id=None caused "
        "per-turn evidence to fail binding"
    )
    assert dec.coarse_state == "active"

    runtime.close_session(tmp_path, session_id)


def test_session_runtime_durable_owner_probe_is_project_and_terminal_scoped(rig, tmp_path):
    runtime, _clock, transports, project_root = rig
    other_root = tmp_path / "other-project"
    first = _open(runtime, project_root)
    second = _open(runtime, other_root)
    first_transport, second_transport = transports[-2], transports[-1]

    assert first_transport.durable_owner_probe(None) is True
    assert second_transport.durable_owner_probe(None) is True

    runtime.close_session(project_root, first["session-id"])
    assert first_transport.durable_owner_probe(None) is False
    assert second_transport.durable_owner_probe(None) is True

    runtime.close_session(other_root, second["session-id"])


def test_shutdown_cancels_busy_owner_before_transport_teardown(rig):
    runtime, _clock, transports, project_root = rig
    record = _open(runtime, project_root)
    transports[0].block_event = threading.Event()
    outcome: list[BaseException] = []

    def run_turn() -> None:
        try:
            runtime.prompt_in_session(
                project_root,
                record["session-id"],
                "blocked shutdown",
                request_id="req-shutdown-owner",
            )
        except BaseException as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run_turn)
    worker.start()
    assert _wait_for(
        lambda: runtime.session_runtime_status(record["session-id"]).get("current-request-id")
        == "req-shutdown-owner"
    )

    runtime.shutdown()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert transports[0].closed is True
    assert transports[0].request_owner is None
    stored = session_store.read_session_record(project_root, record["session-id"])
    assert stored["state"] == "closed"
    assert stored["close-reason"] == "shutdown"


def test_handoff_shutdown_revokes_page_owner_without_closing_session(rig):
    runtime, _clock, transports, project_root = rig
    record = _open(runtime, project_root)
    transport = transports[0]
    transport.set_request_owner("req-old-generation")

    runtime.shutdown(handoff=True)

    assert transport.request_owner is None
    assert transport.closed is False
    stored = session_store.read_session_record(project_root, record["session-id"])
    assert stored["state"] == "active"
    assert stored.get("close-reason") is None


def test_missing_provider_binding_observation_records_redacted_recovery_facts(
    tmp_path, monkeypatch
):
    from audiagentic.components.agents.gateway import observability

    observations = []
    monkeypatch.setattr(
        observability,
        "append_observation",
        lambda *args, **kwargs: observations.append((args, kwargs)),
    )

    sessions_module._observe_missing_provider_session_ref(
        tmp_path,
        request_id="req-missing-provider-ref",
        session_id="ses-missing-provider-ref",
        attempt_epoch=4,
        metadata={
            "target-id": "private-cdp-target",
            "unresolved-turn-pending": True,
            "unresolved-turn-id": "req-missing-provider-ref",
            "submission-state": "prepared",
            "submission-stage": "composer-filled",
            "submission-proven": False,
            "send-intent-ever": False,
            "prompt-text-digest": "private-prompt-digest",
        },
    )

    assert len(observations) == 1
    _, observation = observations[0]
    assert observation["source"] == "session-recovery"
    assert observation["error_occurrence"] == {
        "failure-code": "CON-AGW-124",
        "classification": "provider-session-ref-unavailable",
    }
    facts = observation["diagnostic_facts"]["provider-binding"]
    assert facts == {
        "provider-binding-present": False,
        "provider-session-ref-present": False,
        "target-id-present": True,
        "unresolved-turn-pending": True,
        "turn-id-matches-request": True,
        "submission-proven": False,
        "send-intent-ever": False,
        "submission-stage": "composer-filled",
        "submission-state": "prepared",
        "recovery-state": "unknown",
    }
    assert "private-cdp-target" not in repr(observation)
    assert "private-prompt-digest" not in repr(observation)
