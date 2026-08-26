"""AS41 — Pi RPC tap evidence mapping (frame mapper, observation source, hook).

No real sockets/subprocesses here — iter_tap_frames/open_tap_listener_for_launch
are monkeypatched at the rpc_tap_evidence module boundary. The real end-to-end
proof against a genuine pi-acp bridge lives in
tests/integration/providers/test_pi_acp_resume_live.py-style Docker tests
(AS40/AS49's established pattern) — this file is the fast, deterministic
unit layer for the mapping/threading logic itself.
"""

from __future__ import annotations

import time

import pytest

from audiagentic.components.providers.adapters.pi.rpc_tap import (
    JsonlTapDecodeError,
    JsonlTapFrame,
)
from audiagentic.components.providers.adapters.pi.rpc_tap_evidence import (
    PiRpcTapPreSpawnHook,
    map_pi_rpc_frame_to_observation,
)
from audiagentic.foundation.transports.agent_session import TransportObservationKind


def _frame(frame_type: str, **extra) -> JsonlTapFrame:
    payload = {"type": frame_type, **extra}
    return JsonlTapFrame(payload=payload, raw_length=len(str(payload)))


# ── Frame mapper: closed vocabulary ─────────────────────────────────────────


class TestMapPiRpcFrameToObservation:
    @pytest.mark.parametrize(
        "frame_type,expected_kind",
        [
            ("agent_start", TransportObservationKind.ACTIVITY),
            ("message_update", TransportObservationKind.IN_PROGRESS),
            ("turn_end", TransportObservationKind.TERMINAL),
            ("agent_end", TransportObservationKind.TERMINAL),
        ],
    )
    def test_docker_proven_frame_types_mapped(self, frame_type, expected_kind):
        obs = map_pi_rpc_frame_to_observation(
            _frame(frame_type),
            ag_session_id="s1",
            turn_id="t1",
            sequence=1,
        )
        assert obs.kind == expected_kind

    @pytest.mark.parametrize(
        "frame_type",
        [
            "tool_execution_start",
            "tool_execution_update",
            "tool_execution_end",
            "compaction_start",
            "compaction_end",
            "queue_update",
            "auto_retry_start",
            "extension_ui_request",
            "something_never_seen",
        ],
    )
    def test_unproven_frame_types_degrade_to_unknown(self, frame_type):
        """Source-documented but not transcript-proven this session — must
        NOT be claimed as a known kind (AS41's own conservative doctrine)."""
        obs = map_pi_rpc_frame_to_observation(
            _frame(frame_type),
            ag_session_id="s1",
            turn_id="t1",
            sequence=1,
        )
        assert obs.kind == TransportObservationKind.TRANSPORT_UNKNOWN

    def test_no_payload_leak_into_attributes(self):
        obs = map_pi_rpc_frame_to_observation(
            _frame("agent_start", secret_field="should-never-appear"),
            ag_session_id="s1",
            turn_id="t1",
            sequence=1,
        )
        assert obs.attributes == {}

    def test_correlation_fields_set_from_caller(self):
        obs = map_pi_rpc_frame_to_observation(
            _frame("agent_start"),
            ag_session_id="my-session",
            turn_id="my-turn",
            sequence=7,
        )
        assert obs.ag_session_id == "my-session"
        assert obs.turn_id == "my-turn"
        assert obs.sequence == 7

    def test_malformed_payload_does_not_raise(self):
        weird = JsonlTapFrame(payload={}, raw_length=0)
        obs = map_pi_rpc_frame_to_observation(weird, ag_session_id="s1", turn_id=None, sequence=1)
        assert obs.kind == TransportObservationKind.TRANSPORT_UNKNOWN


# ── PiRpcTapObservationSource: threaded drain ───────────────────────────────


class _FakeListener:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestPiRpcTapObservationSource:
    @pytest.mark.asyncio
    async def test_poll_returns_none_when_queue_empty(self, monkeypatch):
        import audiagentic.components.providers.adapters.pi.rpc_tap_evidence as mod

        monkeypatch.setattr(mod, "iter_tap_frames", lambda listener: iter(()))
        source = mod.PiRpcTapObservationSource(_FakeListener())
        assert _wait_until(lambda: not source._thread.is_alive())
        assert await source.poll("s1", "t1") is None

    @pytest.mark.asyncio
    async def test_poll_drains_frames_in_order(self, monkeypatch):
        import audiagentic.components.providers.adapters.pi.rpc_tap_evidence as mod

        frames = [_frame("agent_start"), _frame("message_update"), _frame("turn_end")]
        monkeypatch.setattr(mod, "iter_tap_frames", lambda listener: iter(frames))
        source = mod.PiRpcTapObservationSource(_FakeListener())

        assert _wait_until(lambda: source._queue.qsize() == 3)

        first = await source.poll("s1", "t1")
        second = await source.poll("s1", "t1")
        third = await source.poll("s1", "t1")
        fourth = await source.poll("s1", "t1")

        assert [first.kind, second.kind, third.kind] == [
            TransportObservationKind.ACTIVITY,
            TransportObservationKind.IN_PROGRESS,
            TransportObservationKind.TERMINAL,
        ]
        # The RPC tap is an auxiliary stream. It has no truthful ordering
        # relation with the native ACP stream, so the gateway allocates the
        # aggregate activity sequence rather than accepting a fake local one.
        assert [first.sequence, second.sequence, third.sequence] == [None, None, None]
        assert fourth is None

    @pytest.mark.asyncio
    async def test_decode_errors_skipped_never_surfaced(self, monkeypatch):
        import audiagentic.components.providers.adapters.pi.rpc_tap_evidence as mod

        items = [
            JsonlTapDecodeError(reason="invalid-json", raw_length=10),
            _frame("agent_start"),
        ]
        monkeypatch.setattr(mod, "iter_tap_frames", lambda listener: iter(items))
        source = mod.PiRpcTapObservationSource(_FakeListener())

        assert _wait_until(lambda: source._queue.qsize() == 1)
        obs = await source.poll("s1", "t1")
        assert obs is not None
        assert obs.kind == TransportObservationKind.ACTIVITY

    def test_close_closes_listener(self, monkeypatch):
        import audiagentic.components.providers.adapters.pi.rpc_tap_evidence as mod

        monkeypatch.setattr(mod, "iter_tap_frames", lambda listener: iter(()))
        listener = _FakeListener()
        source = mod.PiRpcTapObservationSource(listener)
        source.close()
        assert listener.closed
        source.close()  # idempotent, must not raise


# ── PiRpcTapPreSpawnHook: no-op unless the launch enabled a tap ────────────


class TestPiRpcTapPreSpawnHook:
    def test_no_op_when_no_tap_configured(self, monkeypatch):
        import audiagentic.components.providers.adapters.pi.rpc_tap_evidence as mod

        called = {"open": False}

        def _fail_if_called(env):
            called["open"] = True
            raise AssertionError("open_tap_listener_for_launch should not be called")

        monkeypatch.setattr(mod, "tap_listener_config", lambda env: None)
        monkeypatch.setattr(mod, "open_tap_listener_for_launch", _fail_if_called)

        hook = mod.PiRpcTapPreSpawnHook()
        result = hook.on_environment_ready({"SOME_OTHER_VAR": "x"})

        assert result is None
        assert called["open"] is False

    def test_opens_listener_when_tap_configured(self, monkeypatch):
        import audiagentic.components.providers.adapters.pi.rpc_tap_evidence as mod

        fake_listener = _FakeListener()
        monkeypatch.setattr(mod, "tap_listener_config", lambda env: ("127.0.0.1:9", b"key"))
        monkeypatch.setattr(mod, "open_tap_listener_for_launch", lambda env: fake_listener)
        monkeypatch.setattr(mod, "iter_tap_frames", lambda listener: iter(()))

        hook = mod.PiRpcTapPreSpawnHook()
        result = hook.on_environment_ready({"AUDIAGENTIC_PI_TAP_ADDRESS": "127.0.0.1:9"})

        assert isinstance(result, mod.PiRpcTapObservationSource)

    def test_on_close_closes_source(self, monkeypatch):
        import audiagentic.components.providers.adapters.pi.rpc_tap_evidence as mod

        fake_listener = _FakeListener()
        monkeypatch.setattr(mod, "iter_tap_frames", lambda listener: iter(()))
        source = mod.PiRpcTapObservationSource(fake_listener)

        hook = mod.PiRpcTapPreSpawnHook()
        hook.on_close(source)
        assert fake_listener.closed

    def test_on_close_none_is_a_no_op(self):
        hook = PiRpcTapPreSpawnHook()
        hook.on_close(None)  # must not raise
