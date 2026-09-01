"""AS28 slice 2 — AcpAgentSessionTransport private wrapper tests.

Covers raw-event redaction, known/unknown kind mapping, request correlation,
callback exception isolation, cancellation dispositions, no native leakage,
protocol conformance, and existing ACP regression parity.
"""
from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.acp import (
    AcpAgentSessionTransport as _AcpAgentSessionTransport,
)
from audiagentic.foundation.transports.acp import (
    AcpEvent,
    AcpLaunch,
    _map_acp_event_to_observation,
)
from audiagentic.foundation.transports.session_binding import ProviderSessionRef


def AcpAgentSessionTransport(*args, **kwargs):
    """Construct the ACP adapter with a caller-owned Gateway identity."""
    kwargs.setdefault("ag_session_id", "ag-gateway-1")
    return _AcpAgentSessionTransport(*args, **kwargs)
from audiagentic.foundation.transports.agent_session import (
    AgentSessionTransport,
    ControlDisposition,
    CorrelationQuality,
    SessionControlAction,
    SessionControlRequest,
    SessionTurnResult,
    TransportObservation,
    TransportObservationKind,
)

# ── AS28 architecture-boundary: package export gate ─────────────

class TestAcpAgentSessionTransportExportBoundary:
    """Static test: AcpAgentSessionTransport is private to acp / provider adapters.

    foundation.transports must NOT expose raw ACP wrapper types; the direct
    acp module remains usable for foundation and provider-adapter tests.
    """

    def test_transports_package_does_not_export_acp_agent_session_transport(self):
        """AcpAgentSessionTransport is absent from foundation.transports.__all__."""
        from audiagentic.foundation import transports
        assert (
            "AcpAgentSessionTransport" not in transports.__all__
        ), "AS28 boundary breach: AcpAgentSessionTransport must not be in transports.__all__"

    def test_transports_package_has_no_acp_agent_session_transport_attr(self):
        """AcpAgentSessionTransport is not accessible on the transports package namespace."""
        from audiagentic.foundation import transports
        assert (
            not hasattr(transports, "AcpAgentSessionTransport")
        ), "AS28 boundary breach: AcpAgentSessionTransport must not be on transports pkg"

    def test_acp_module_exports_acp_agent_session_transport(self):
        """The direct acp module still exposes AcpAgentSessionTransport for internal use."""
        from audiagentic.foundation.transports.acp import AcpAgentSessionTransport as DirectImport
        assert DirectImport is not None
        assert callable(DirectImport)


# ── SDK mock helpers (same pattern as test_acp_session.py) ──────

def _install_sdk(monkeypatch, *, prompt_side_effect=None):
    """Install a fake acp SDK; returns (conn, captured)."""
    captured = {"client": None}

    conn = MagicMock()
    conn.initialize = AsyncMock()
    conn.new_session = AsyncMock(return_value=SimpleNamespace(session_id="acp-s-1"))
    conn.set_config_option = AsyncMock()
    turn_counter = {"n": 0}

    async def default_prompt(session_id, prompt):
        turn_counter["n"] += 1
        client = captured["client"]
        if client is not None:
            await client.session_update(
                session_id,
                {"sessionUpdate": "agent_message_chunk", "text": f"turn-{turn_counter['n']}"},
            )
        return SimpleNamespace(stop_reason="end_turn")

    conn.prompt = AsyncMock(side_effect=prompt_side_effect or default_prompt)

    proc = SimpleNamespace(returncode=None, terminate=lambda: None, kill=lambda: None)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=(conn, proc))
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    def spawn(client_instance, executable, *args, **kwargs):
        captured["client"] = client_instance
        return mock_ctx

    acp_mod = types.ModuleType("acp")
    acp_mod.PROTOCOL_VERSION = 1
    acp_mod.spawn_agent_process = spawn
    acp_mod.text_block = lambda text: {"type": "text", "text": text}
    interfaces_mod = types.ModuleType("acp.interfaces")
    interfaces_mod.Client = object
    monkeypatch.setitem(sys.modules, "acp", acp_mod)
    monkeypatch.setitem(sys.modules, "acp.interfaces", interfaces_mod)
    return conn, captured


# ── Kind mapping unit tests ─────────────────────────────────────

class TestAcpKindToTransportMapping:
    """Unit tests for _map_acp_event_to_observation kind translation."""

    def _make_acp_event(self, kind: str, **ext_kwargs) -> AcpEvent:
        ext = {"acp": {**ext_kwargs}}
        return AcpEvent(
            sequence=1,
            kind=kind,
            timestamp="2025-01-01T00:00:00Z",
            session_id="acp-session-42",  # raw ACP session ref
            text=None,
            terminal=False,
            error=None,
            ext=ext,
        )

    def test_assistant_message_maps_to_activity(self):
        ev = self._make_acp_event("assistant-message")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.ACTIVITY
        assert obs.ag_session_id == "ag-s-1"  # not ACP session id
        assert obs.turn_id == "turn-t-1"

    def test_thought_maps_to_activity_with_model_activity(self):
        ev = self._make_acp_event("thought")
        ev_text = "thinking hard"
        ev_with_text = AcpEvent(
            sequence=2, kind="thought", timestamp="2025-01-01T00:00:00Z",
            session_id="acp-s-42", text=ev_text, terminal=False, error=None,
            ext={"acp": {}},
        )
        obs = _map_acp_event_to_observation(ev_with_text, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.ACTIVITY
        assert obs.attributes.get("model_activity") == ev_text

    def test_status_maps_to_activity(self):
        ev = self._make_acp_event("status")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.ACTIVITY

    def test_usage_maps_to_activity(self):
        ev = self._make_acp_event("usage")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.ACTIVITY

    def test_tool_call_pending_maps_to_tool_requested(self):
        ev = self._make_acp_event("tool-call", status="pending", tool_call_id="tc-5")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TOOL_REQUESTED
        assert obs.attributes["tool_call_id"] == "tc-5"
        assert obs.attributes["tool_status"] == "pending"

    def test_tool_call_started_maps_to_tool_requested(self):
        ev = self._make_acp_event("tool-call", status="started", tool_call_id="tc-6")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TOOL_REQUESTED
        assert obs.attributes["tool_status"] == "started"

    def test_tool_call_in_progress_maps_to_tool_requested(self):
        ev = self._make_acp_event("tool-call", status="in_progress", tool_call_id="tc-7")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TOOL_REQUESTED

    def test_tool_call_completed_maps_to_tool_finished(self):
        ev = self._make_acp_event("tool-call", status="completed", tool_call_id="tc-8")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TOOL_FINISHED
        assert obs.attributes["tool_status"] == "completed"

    def test_tool_call_finished_maps_to_tool_finished(self):
        ev = self._make_acp_event("tool-call", status="finished", tool_call_id="tc-9")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TOOL_FINISHED

    def test_tool_call_failed_maps_to_tool_finished(self):
        ev = self._make_acp_event("tool-call", status="failed", tool_call_id="tc-10")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TOOL_FINISHED
        assert obs.attributes["tool_status"] == "failed"

    def test_tool_call_cancelled_maps_to_tool_finished(self):
        ev = self._make_acp_event("tool-call", status="cancelled", tool_call_id="tc-11")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TOOL_FINISHED

    def test_tool_call_no_status_falls_to_unknown(self):
        """Tool-call with no status falls through to TRANSPORT_UNKNOWN."""
        ev = self._make_acp_event("tool-call")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TRANSPORT_UNKNOWN
        assert obs.attributes == {}  # no attributes for unknown

    def test_permission_request_maps_with_tool_call_id(self):
        ev = self._make_acp_event("permission-request", tool_call_id="tc-perm")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.PERMISSION_REQUESTED
        assert obs.attributes["tool_call_id"] == "tc-perm"

    def test_permission_request_no_tool_call_id(self):
        ev = self._make_acp_event("permission-request")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.PERMISSION_REQUESTED
        assert obs.attributes["tool_call_id"] is None

    def test_result_terminal_with_stop_reason(self):
        ev = self._make_acp_event("result", stop_reason="end_turn")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TERMINAL
        assert obs.attributes["stop_reason"] == "end_turn"

    def test_result_terminal_with_error(self):
        ev_err = AcpEvent(
            sequence=3, kind="result", timestamp="2025-01-01T00:00:00Z",
            session_id="acp-s-42", text=None, terminal=True,
            error={"code": "ERR-001", "message": "crash"},
            ext={"acp": {}},
        )
        obs = _map_acp_event_to_observation(ev_err, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TERMINAL
        assert obs.attributes["error_code"] == "ERR-001"

    def test_error_maps_to_transport_error(self):
        ev_err = AcpEvent(
            sequence=4, kind="error", timestamp="2025-01-01T00:00:00Z",
            session_id="acp-s-42", text=None, terminal=False,
            error={"code": "EXT-ACP-002", "message": "malformed"},
            ext={"acp": {}},
        )
        obs = _map_acp_event_to_observation(ev_err, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TRANSPORT_ERROR
        assert obs.attributes["error_code"] == "EXT-ACP-002"
        assert obs.attributes["reason"] == "malformed"

    def test_error_without_error_dict_uses_text(self):
        ev_err = AcpEvent(
            sequence=5, kind="error", timestamp="2025-01-01T00:00:00Z",
            session_id="acp-s-42", text="something bad", terminal=False,
            error=None,
            ext={"acp": {}},
        )
        obs = _map_acp_event_to_observation(ev_err, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TRANSPORT_ERROR
        assert obs.attributes["reason"] == "something bad"

    def test_unknown_kind_maps_to_transport_unknown_no_attributes(self):
        """Unknown ACP kinds produce TRANSPORT_UNKNOWN with NO attributes."""
        ev = self._make_acp_event("some-unknown-native-event")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TRANSPORT_UNKNOWN
        assert obs.attributes == {}  # no raw kind name leaked

    def test_file_change_unknown(self):
        """file-change is not mapped; falls to TRANSPORT_UNKNOWN."""
        ev = self._make_acp_event("file-change")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TRANSPORT_UNKNOWN

    def test_plan_update_unknown(self):
        """plan-update is not mapped; falls to TRANSPORT_UNKNOWN."""
        ev = self._make_acp_event("plan-update")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TRANSPORT_UNKNOWN

    def test_terminal_output_unknown(self):
        """terminal-output is not mapped; falls to TRANSPORT_UNKNOWN."""
        ev = self._make_acp_event("terminal-output")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TRANSPORT_UNKNOWN


# ── Raw-event redaction / no-native-leakage ─────────────────────

class TestNoNativeLeakage:
    """ACP session refs, extension payload, and native kind names never
    leak into neutral observations."""

    def test_acp_session_id_not_in_observation(self):
        """Raw ACP session id is NOT used in the neutral ag_session_id."""
        ev = self._make_acp_event("assistant-message")
        obs = _map_acp_event_to_observation(ev, "ag-s-canonical", "turn-t-1")
        assert obs.ag_session_id == "ag-s-canonical"  # not "acp-session-42"

    def test_no_raw_kind_in_attributes(self):
        """No raw ACP kind value appears in observation attributes."""
        ev = self._make_acp_event("assistant-message", raw_kind="agent_message_chunk")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert "raw_kind" not in obs.attributes

    def test_no_payload_in_attributes(self):
        """Raw ACP payload never appears in observation attributes."""
        ev = self._make_acp_event("tool-call", status="pending", tool_call_id="tc-5",
                                   payload={"deep": {"nested": "data"}})
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert "payload" not in obs.attributes

    def test_transport_unknown_no_raw_kind(self):
        """TRANSPORT_UNKNOWN carries no raw kind name."""
        ev = self._make_acp_event("unknown-native-event")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.kind == TransportObservationKind.TRANSPORT_UNKNOWN
        # No attribute key could carry the raw kind
        for key in obs.attributes:
            assert "native" not in key.lower()
            assert "raw" not in key.lower()

    def test_turn_id_comes_from_request_not_acp(self):
        """turn_id is from the neutral SessionPrompt, not ACP internal."""
        ev = self._make_acp_event("assistant-message")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "my-neutral-turn-id")
        assert obs.turn_id == "my-neutral-turn-id"

    def test_sequence_preserved(self):
        """ACP sequence number is preserved as-is in the observation."""
        ev = self._make_acp_event("assistant-message")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.sequence == 1

    def test_timestamp_preserved(self):
        """ACP timestamp is preserved as-is."""
        ev = self._make_acp_event("assistant-message")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.observed_at == "2025-01-01T00:00:00Z"

    def test_correlation_quality_is_request_scoped(self):
        """ACP doesn't provide native correlation; quality is REQUEST_SCOPED."""
        ev = self._make_acp_event("assistant-message")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        assert obs.correlation_quality == CorrelationQuality.REQUEST_SCOPED

    def test_no_tool_arguments_leak(self):
        """Tool arguments from ACP payload never appear in neutral attrs."""
        ev = self._make_acp_event(
            "tool-call", status="pending", tool_call_id="tc-5",
            payload={"arguments": {"path": "/secret"}},
        )
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        for key in obs.attributes:
            assert key not in ("tool_arguments", "arguments", "payload")

    def test_no_prompt_text_in_observation(self):
        """No prompt text leaks into any observation attribute."""
        ev = self._make_acp_event("assistant-message")
        obs = _map_acp_event_to_observation(ev, "ag-s-1", "turn-t-1")
        for key in obs.attributes:
            assert key != "prompt"

    def _make_acp_event(self, kind: str, **ext_kwargs) -> AcpEvent:
        ext = {"acp": {**ext_kwargs}}
        return AcpEvent(
            sequence=1, kind=kind, timestamp="2025-01-01T00:00:00Z",
            session_id="acp-session-42", text=None, terminal=False, error=None,
            ext=ext,
        )


# ── Full integration tests with mocked ACP SDK ─────────────────

class TestAcpAgentSessionTransportOpenClose:
    """Lifecycle: open, is_alive, close, idempotent close."""

    @pytest.mark.asyncio
    async def test_open_returns_ag_session_id(self, tmp_path, monkeypatch):
        _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        result = await transport.open()
        assert result.ag_session_id == "ag-gateway-1"
        assert result.provider_session_ref == ProviderSessionRef("acp-s-1")
        assert transport.is_alive()

    @pytest.mark.asyncio
    async def test_open_applies_initial_configuration_before_exposure(self, tmp_path, monkeypatch):
        conn, _ = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(
            AcpLaunch("agent", initial_config_options=(("model", "brutus/qwen"),)),
            cwd=tmp_path,
        )

        result = await transport.open()

        assert result.provider_session_ref == ProviderSessionRef("acp-s-1")
        conn.set_config_option.assert_awaited_once_with(
            config_id="model", session_id="acp-s-1", value="brutus/qwen"
        )

    @pytest.mark.asyncio
    async def test_open_fails_closed_when_initial_configuration_is_rejected(self, tmp_path, monkeypatch):
        conn, _ = _install_sdk(monkeypatch)
        conn.set_config_option.side_effect = RuntimeError("unknown selected model")
        transport = AcpAgentSessionTransport(
            AcpLaunch("agent", initial_config_options=(("model", "brutus/missing"),)),
            cwd=tmp_path,
        )

        with pytest.raises(AudiaGenticError, match="ACP agent execution failed"):
            await transport.open()

        assert not transport.is_alive()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, tmp_path, monkeypatch):
        _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()
        await transport.close()
        await transport.close()  # no-op, never raises

    @pytest.mark.asyncio
    async def test_is_alive_false_after_close(self, tmp_path, monkeypatch):
        _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()
        assert transport.is_alive()
        await transport.close()
        assert not transport.is_alive()

    @pytest.mark.asyncio
    async def test_prompt_before_open_raises(self, tmp_path, monkeypatch):
        _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        with pytest.raises(AudiaGenticError):
            await transport.prompt(
                SimpleNamespace(turn_id="t-1", body="hello"),  # type: ignore
                lambda observation: None,  # type: ignore
            )

    @pytest.mark.asyncio
    async def test_pre_spawn_hook_forwarded_to_inner_transport(self, tmp_path, monkeypatch):
        """AS41: the wrapper forwards pre_spawn_hook unchanged to the inner
        AcpSessionTransport — it does not intercept or wrap it."""
        _install_sdk(monkeypatch)

        seen = {}

        class _Hook:
            def on_environment_ready(self, environment):
                seen["environment"] = dict(environment)
                return "hook-state"

            def on_close(self, hook_state):
                seen["closed_with"] = hook_state

        launch = AcpLaunch("agent", args=(), environment={"TAP_ADDRESS": "127.0.0.1:9"})
        transport = AcpAgentSessionTransport(launch, cwd=tmp_path, pre_spawn_hook=_Hook())
        await transport.open()
        assert seen["environment"] == {"TAP_ADDRESS": "127.0.0.1:9"}

        await transport.close()
        assert seen["closed_with"] == "hook-state"

    @pytest.mark.asyncio
    async def test_auxiliary_observation_source_drained_through_same_sink(self, tmp_path, monkeypatch):
        """AS41: an AuxiliaryObservationSource returned as hook_state is
        drained during the turn and its observations arrive through the
        SAME sink as native ACP events — the caller sees one stream."""
        from audiagentic.foundation.transports.acp import TransportObservation
        from audiagentic.foundation.transports.agent_session import (
            CorrelationQuality,
            SessionPrompt,
            TransportObservationKind,
        )

        _install_sdk(monkeypatch)

        class _FakeAuxSource:
            def __init__(self):
                self._emitted = False
                self.closed = False

            async def poll(self, ag_session_id, turn_id):
                if not self._emitted:
                    self._emitted = True
                    return TransportObservation(
                        ag_session_id=ag_session_id,
                        turn_id=turn_id,
                        sequence=0,
                        kind=TransportObservationKind.ACTIVITY,
                        observed_at="2026-01-01T00:00:00Z",
                        correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                        attributes={},
                    )
                return None

            def close(self):
                self.closed = True

        class _Hook:
            def __init__(self, source):
                self._source = source

            def on_environment_ready(self, environment):
                return self._source

            def on_close(self, hook_state):
                if hook_state is not None:
                    hook_state.close()

        aux_source = _FakeAuxSource()
        transport = AcpAgentSessionTransport(
            AcpLaunch("agent"), cwd=tmp_path, pre_spawn_hook=_Hook(aux_source),
        )
        await transport.open()

        delivered: list[TransportObservation] = []

        async def sink(observation: TransportObservation) -> None:
            delivered.append(observation)

        await transport.prompt(SessionPrompt(turn_id="t-aux", body="hello"), sink)

        # At least one observation came from the auxiliary source, correctly
        # correlated to this turn, delivered through the same sink as ACP's
        # own native events (which also fire for this prompt).
        aux_delivered = [
            o for o in delivered
            if o.turn_id == "t-aux" and o.sequence == 0 and o.observed_at == "2026-01-01T00:00:00Z"
        ]
        assert len(aux_delivered) == 1

        await transport.close()
        assert aux_source.closed


class TestAcpAgentSessionTransportPrompt:
    """prompt() maps ACP events to TransportObservation and delivers via sink."""

    @pytest.mark.asyncio
    async def test_prompt_delivers_observations(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        delivered: list[TransportObservation] = []

        async def sink(observation: TransportObservation) -> None:
            delivered.append(observation)

        from audiagentic.foundation.transports.agent_session import SessionPrompt
        result = await transport.prompt(SessionPrompt(turn_id="t-1", body="hello"), sink)

        assert isinstance(result, SessionTurnResult)
        assert len(delivered) >= 1
        # The ACP event "assistant-message" → ACTIVITY
        activity_obs = [o for o in delivered if o.kind == TransportObservationKind.ACTIVITY]
        assert len(activity_obs) >= 1

        await transport.close()

    @pytest.mark.asyncio
    async def test_prompt_turn_id_in_observations(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        delivered: list[TransportObservation] = []

        async def sink(observation: TransportObservation) -> None:
            delivered.append(observation)

        from audiagentic.foundation.transports.agent_session import SessionPrompt
        result = await transport.prompt(
            SessionPrompt(turn_id="my-turn-42", body="hello"), sink,
        )
        for obs in delivered:
            assert obs.turn_id == "my-turn-42"

        await transport.close()

    @pytest.mark.asyncio
    async def test_prompt_ag_session_id_in_observations(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        delivered: list[TransportObservation] = []

        async def sink(observation: TransportObservation) -> None:
            delivered.append(observation)

        from audiagentic.foundation.transports.agent_session import SessionPrompt
        result = await transport.prompt(
            SessionPrompt(turn_id="t-1", body="hello"), sink,
        )
        for obs in delivered:
            assert obs.ag_session_id == "ag-gateway-1"

        await transport.close()

    @pytest.mark.asyncio
    async def test_prompt_stop_reason_passthrough(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        from audiagentic.foundation.transports.agent_session import SessionPrompt

        async def sink(observation: TransportObservation) -> None:
            pass

        result = await transport.prompt(
            SessionPrompt(turn_id="t-1", body="hello"), sink,
        )
        assert result.stop_reason == "end_turn"

        await transport.close()

    @pytest.mark.asyncio
    async def test_prompt_counts_observations_delivered(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        from audiagentic.foundation.transports.agent_session import SessionPrompt

        async def sink(observation: TransportObservation) -> None:
            pass

        result = await transport.prompt(
            SessionPrompt(turn_id="t-1", body="hello"), sink,
        )
        assert result.observations_delivered >= 1  # at least assistant-message + terminal

        await transport.close()

    @pytest.mark.asyncio
    async def test_prompt_with_tool_events(self, tmp_path, monkeypatch):
        """Tool-call events map to TOOL_REQUESTED / TOOL_FINISHED."""
        async def prompt_with_tools(session_id, prompt):
            client = captured["client"]
            # Emit a tool start and end
            await client.session_update(
                session_id,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "tc-tool-test",
                    "status": "pending",
                },
            )
            await client.session_update(
                session_id,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "tc-tool-test",
                    "status": "completed",
                },
            )
            return SimpleNamespace(stop_reason="end_turn")

        conn, captured = _install_sdk(monkeypatch, prompt_side_effect=prompt_with_tools)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        delivered: list[TransportObservation] = []

        async def sink(observation: TransportObservation) -> None:
            delivered.append(observation)

        from audiagentic.foundation.transports.agent_session import SessionPrompt
        result = await transport.prompt(
            SessionPrompt(turn_id="t-tools", body="use tool"), sink,
        )

        requested = [o for o in delivered if o.kind == TransportObservationKind.TOOL_REQUESTED]
        finished = [o for o in delivered if o.kind == TransportObservationKind.TOOL_FINISHED]
        assert len(requested) >= 1
        assert len(finished) >= 1
        assert requested[0].attributes["tool_call_id"] == "tc-tool-test"
        assert finished[0].attributes["tool_status"] == "completed"

        await transport.close()

    @pytest.mark.asyncio
    async def test_prompt_records_provider_tool_failure_on_cancelled_result(self, tmp_path, monkeypatch):
        """Provider cancellation after a failed tool is not a clean cancel."""
        async def prompt_with_failed_tool(session_id, prompt):
            client = captured["client"]
            await client.session_update(
                session_id,
                {"sessionUpdate": "agent_message_chunk", "text": "partial answer"},
            )
            await client.session_update(
                session_id,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "tc-failed",
                    "status": "failed",
                },
            )
            return SimpleNamespace(stop_reason="cancelled")

        conn, captured = _install_sdk(monkeypatch, prompt_side_effect=prompt_with_failed_tool)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        from audiagentic.foundation.transports.agent_session import SessionPrompt

        result = await transport.prompt(SessionPrompt(turn_id="t-provider-cancel", body="run it"), lambda _obs: None)

        assert result.stop_reason == "cancelled"
        assert result.error_code == "EXT-ACP-TOOL-001"
        assert result.final_summary == "partial answer"
        assert result.metadata["cancelled-by-signal"] is False
        assert result.metadata["failed-tool-call-count"] == 1
        assert result.metadata["failed-tool-call-ids"] == ("tc-failed",)

        await transport.close()

    @pytest.mark.asyncio
    async def test_prompt_two_turns_share_session(self, tmp_path, monkeypatch):
        """Two prompts on the same session reuse the connection."""
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        from audiagentic.foundation.transports.agent_session import SessionPrompt

        async def sink(observation: TransportObservation) -> None:
            pass

        r1 = await transport.prompt(SessionPrompt(turn_id="t-1", body="one"), sink)
        r2 = await transport.prompt(SessionPrompt(turn_id="t-2", body="two"), sink)

        assert r1.turn_id == "t-1"
        assert r2.turn_id == "t-2"
        # Same session for both turns
        assert r1.stop_reason == "end_turn"
        assert r2.stop_reason == "end_turn"

        await transport.close()


# ── Sink callback exception isolation ───────────────────────────

class TestSinkCallbackExceptionIsolation:
    """Sink failures never kill the turn."""

    @pytest.mark.asyncio
    async def test_sink_exception_does_not_kill_turn(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        sink_called = [0]

        async def failing_sink(observation: TransportObservation) -> None:
            sink_called[0] += 1
            raise RuntimeError("sink error")

        from audiagentic.foundation.transports.agent_session import SessionPrompt
        result = await transport.prompt(
            SessionPrompt(turn_id="t-1", body="hello"), failing_sink,
        )
        # Turn completes despite sink failures
        assert result.stop_reason == "end_turn"
        assert sink_called[0] >= 1
        # Output is captured before observation delivery.  A caller's broken
        # activity sink must never erase the provider's terminal reply.
        assert result.final_summary == "turn-1"

        await transport.close()

    @pytest.mark.asyncio
    async def test_partial_sink_failures_still_deliver(self, tmp_path, monkeypatch):
        """If some observations fail in the sink but others succeed, turn continues."""
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        call_count = [0]

        async def intermittent_sink(observation: TransportObservation) -> None:
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("intermittent error")

        from audiagentic.foundation.transports.agent_session import SessionPrompt
        result = await transport.prompt(
            SessionPrompt(turn_id="t-1", body="hello"), intermittent_sink,
        )
        assert result.stop_reason == "end_turn"

        await transport.close()


# ── Control semantics ───────────────────────────────────────────

class TestControlCancelTurn:
    """CANCEL_TURN control semantics."""

    @pytest.mark.asyncio
    async def test_cancel_turn_accepted_when_alive(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        req = SessionControlRequest(
            ag_session_id="acp-s-1", turn_id=None,
            action=SessionControlAction.CANCEL_TURN,
        )
        result = await transport.control(req)
        assert result.disposition == ControlDisposition.ACCEPTED

        await transport.close()

    @pytest.mark.asyncio
    async def test_cancel_turn_unsupported_when_not_alive(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()
        await transport.close()

        req = SessionControlRequest(
            ag_session_id="acp-s-1", turn_id=None,
            action=SessionControlAction.CANCEL_TURN,
        )
        result = await transport.control(req)
        assert result.disposition == ControlDisposition.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_cancel_during_active_turn(self, tmp_path, monkeypatch):
        """CANCEL_TURN sets the signal during an active turn."""
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        from audiagentic.foundation.transports.agent_session import SessionPrompt

        async def slow_prompt(session_id, prompt):
            """Holds the turn long enough for cancel to be issued."""
            await asyncio.sleep(0.2)
            return SimpleNamespace(stop_reason="end_turn")

        # Replace conn.prompt with slow version
        conn.prompt = AsyncMock(side_effect=slow_prompt)

        async def sink(observation: TransportObservation) -> None:
            pass

        prompt_task = asyncio.ensure_future(
            transport.prompt(SessionPrompt(turn_id="t-1", body="hello"), sink),
        )

        # Cancel during the turn
        await asyncio.sleep(0.05)
        req = SessionControlRequest(
            ag_session_id="acp-s-1", turn_id=None,
            action=SessionControlAction.CANCEL_TURN,
        )
        ctrl_result = await transport.control(req)
        assert ctrl_result.disposition == ControlDisposition.ACCEPTED

        result = await prompt_task
        # The ACP protocol-level cancel sets stop_reason to "cancelled"
        assert result.stop_reason in ("cancelled", "end_turn")

        await transport.close()


class TestControlUnsupportedActions:
    """Interrupt, steer, and permission are unsupported on ACP."""

    @pytest.mark.asyncio
    async def test_interrupt_turn_unsupported(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        req = SessionControlRequest(
            ag_session_id="acp-s-1", turn_id=None,
            action=SessionControlAction.INTERRUPT_TURN,
        )
        result = await transport.control(req)
        assert result.disposition == ControlDisposition.UNSUPPORTED

        await transport.close()

    @pytest.mark.asyncio
    async def test_steer_turn_unsupported(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        req = SessionControlRequest(
            ag_session_id="acp-s-1", turn_id=None,
            action=SessionControlAction.STEER_TURN,
            payload={"steer_text": "try again"},
        )
        result = await transport.control(req)
        assert result.disposition == ControlDisposition.UNSUPPORTED

        await transport.close()

    @pytest.mark.asyncio
    async def test_respond_permission_unsupported(self, tmp_path, monkeypatch):
        """Permission response is unsupported without versioned ACP proof."""
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        req = SessionControlRequest(
            ag_session_id="acp-s-1", turn_id=None,
            action=SessionControlAction.RESPOND_PERMISSION,
            payload={"permission": "allow"},
        )
        result = await transport.control(req)
        assert result.disposition == ControlDisposition.UNSUPPORTED

        await transport.close()


class TestControlCloseSession:
    """CLOSE_SESSION delegates to inner close."""

    @pytest.mark.asyncio
    async def test_close_session_accepted(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        req = SessionControlRequest(
            ag_session_id="acp-s-1", turn_id=None,
            action=SessionControlAction.CLOSE_SESSION,
        )
        result = await transport.control(req)
        assert result.disposition == ControlDisposition.ACCEPTED
        assert not transport.is_alive()

    @pytest.mark.asyncio
    async def test_close_session_is_idempotent(self, tmp_path, monkeypatch):
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()
        await transport.close()

        req = SessionControlRequest(
            ag_session_id="acp-s-1", turn_id=None,
            action=SessionControlAction.CLOSE_SESSION,
        )
        result = await transport.control(req)
        assert result.disposition == ControlDisposition.ACCEPTED


# ── Protocol conformance ───────────────────────────────────────

class TestProtocolConformance:
    """AcpAgentSessionTransport satisfies AgentSessionTransport protocol."""

    @pytest.mark.asyncio
    async def test_is_agent_session_transport_protocol(self, tmp_path, monkeypatch):
        """Runtime type check: AcpAgentSessionTransport is an AgentSessionTransport."""
        conn, captured = _install_sdk(monkeypatch)
        transport: AgentSessionTransport = AcpAgentSessionTransport(  # type: ignore[assignment]
            AcpLaunch("agent"), cwd=tmp_path,
        )
        await transport.open()
        assert transport is not None

        from audiagentic.foundation.transports.agent_session import SessionPrompt

        async def sink(observation: TransportObservation) -> None:
            pass

        result = await transport.prompt(
            SessionPrompt(turn_id="t-1", body="hello"), sink,
        )
        assert isinstance(result, SessionTurnResult)

        await transport.close()

    @pytest.mark.asyncio
    async def test_full_lifecycle_via_protocol(self, tmp_path, monkeypatch):
        """Full open → prompt → control → close lifecycle via protocol."""
        conn, captured = _install_sdk(monkeypatch)
        transport: AgentSessionTransport = AcpAgentSessionTransport(  # type: ignore[assignment]
            AcpLaunch("agent"), cwd=tmp_path,
        )

        open_result = await transport.open()
        assert open_result.ag_session_id == "ag-gateway-1"

        from audiagentic.foundation.transports.agent_session import SessionPrompt

        async def sink(observation: TransportObservation) -> None:
            pass

        prompt_result = await transport.prompt(
            SessionPrompt(turn_id="t-full", body="lifecycle test"), sink,
        )
        assert prompt_result.turn_id == "t-full"

        ctrl_result = await transport.control(
            SessionControlRequest(
                ag_session_id=open_result.ag_session_id,
                turn_id=None,
                action=SessionControlAction.CANCEL_TURN,
            ),
        )
        assert ctrl_result.disposition in (
            ControlDisposition.ACCEPTED,
            ControlDisposition.UNSUPPORTED,
        )

        await transport.close()
        assert not transport.is_alive()


# ── ACP regression parity ───────────────────────────────────────

class TestAcpRegressionParity:
    """AcpAgentSessionTransport preserves existing ACP session behavior."""

    @pytest.mark.asyncio
    async def test_two_turns_same_session_id(self, tmp_path, monkeypatch):
        """Two prompts through the wrapper share the same underlying ACP session."""
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        from audiagentic.foundation.transports.agent_session import SessionPrompt

        delivered_1: list[TransportObservation] = []
        delivered_2: list[TransportObservation] = []

        async def sink_1(observation: TransportObservation) -> None:
            delivered_1.append(observation)

        async def sink_2(observation: TransportObservation) -> None:
            delivered_2.append(observation)

        r1 = await transport.prompt(SessionPrompt(turn_id="t-1", body="one"), sink_1)
        r2 = await transport.prompt(SessionPrompt(turn_id="t-2", body="two"), sink_2)

        # Same session id across turns
        assert all(o.ag_session_id == "ag-gateway-1" for o in delivered_1 + delivered_2)
        # Different turn ids
        assert all(o.turn_id == "t-1" for o in delivered_1)
        assert all(o.turn_id == "t-2" for o in delivered_2)

        await transport.close()

    @pytest.mark.asyncio
    async def test_terminal_observation_delivered(self, tmp_path, monkeypatch):
        """The terminal 'result' ACP event maps to TERMINAL observation."""
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        delivered: list[TransportObservation] = []

        async def sink(observation: TransportObservation) -> None:
            delivered.append(observation)

        from audiagentic.foundation.transports.agent_session import SessionPrompt
        result = await transport.prompt(
            SessionPrompt(turn_id="t-1", body="hello"), sink,
        )

        terminal_obs = [o for o in delivered if o.kind == TransportObservationKind.TERMINAL]
        assert len(terminal_obs) >= 1
        assert terminal_obs[0].attributes.get("stop_reason") == "end_turn"

        await transport.close()


# ── Request correlation ────────────────────────────────────────

class TestRequestCorrelation:
    """Canonical AG session/turn IDs come from neutral request/context."""

    @pytest.mark.asyncio
    async def test_ag_session_id_from_open_result(self, tmp_path, monkeypatch):
        """ag_session_id in observations matches open() return value."""
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        open_result = await transport.open()

        delivered: list[TransportObservation] = []

        async def sink(observation: TransportObservation) -> None:
            delivered.append(observation)

        from audiagentic.foundation.transports.agent_session import SessionPrompt
        await transport.prompt(
            SessionPrompt(turn_id="t-corr", body="correlate"), sink,
        )

        for obs in delivered:
            assert obs.ag_session_id == open_result.ag_session_id

        await transport.close()

    @pytest.mark.asyncio
    async def test_turn_id_from_prompt_request(self, tmp_path, monkeypatch):
        """turn_id in observations matches the SessionPrompt.turn_id."""
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        delivered: list[TransportObservation] = []

        async def sink(observation: TransportObservation) -> None:
            delivered.append(observation)

        from audiagentic.foundation.transports.agent_session import SessionPrompt
        my_turn_id = "gateway-turn-99"
        await transport.prompt(
            SessionPrompt(turn_id=my_turn_id, body="correlate"), sink,
        )

        for obs in delivered:
            assert obs.turn_id == my_turn_id

        await transport.close()


# ── Control disposition discipline ─────────────────────────────

class TestControlDispositionDiscipline:
    """Control results never imply durable session state."""

    @pytest.mark.asyncio
    async def test_cancel_accepted_does_not_imply_terminal(self, tmp_path, monkeypatch):
        """CANCEL_TURN → ACCEPTED does not mean the session is terminal.
        The transport could still be alive if the turn was cancelled but
        the child process survived (protocol-level cancel)."""
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        req = SessionControlRequest(
            ag_session_id="acp-s-1", turn_id=None,
            action=SessionControlAction.CANCEL_TURN,
        )
        result = await transport.control(req)
        assert result.disposition == ControlDisposition.ACCEPTED
        # The disposition says "accepted" but does NOT mean the session is
        # terminal — only a correlated TERMINAL observation or process-death
        # evidence can release the turn.

    @pytest.mark.asyncio
    async def test_unsupported_is_not_an_error(self, tmp_path, monkeypatch):
        """UNSUPPORTED disposition is not an error/state change."""
        conn, captured = _install_sdk(monkeypatch)
        transport = AcpAgentSessionTransport(AcpLaunch("agent"), cwd=tmp_path)
        await transport.open()

        req = SessionControlRequest(
            ag_session_id="acp-s-1", turn_id=None,
            action=SessionControlAction.STEER_TURN,
            payload={"steer_text": "try again"},
        )
        result = await transport.control(req)
        assert result.disposition == ControlDisposition.UNSUPPORTED
        # Transport is still alive after UNSUPPORTED
        assert transport.is_alive()

        await transport.close()
