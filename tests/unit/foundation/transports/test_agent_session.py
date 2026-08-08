"""AS28 stage 1 — foundation-neutral agent session transport contract.

Tests frozen/immutable values, enum validation, scalar-only discipline,
raw/native data rejection, bounded unknown-kind containment, control
payload default-deny, import boundary enforcement, protocol conformance
with a fake transport, and exported symbol completeness.
"""

from __future__ import annotations

import asyncio
from dataclasses import fields, is_dataclass
from typing import Any

import pytest

# ── Module under test ───────────────────────────────────────────────────────
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.agent_session import (
    _MAX_PROMPT_BODY_BYTES,
    AgentSessionTransport,
    ControlDisposition,
    CorrelationQuality,
    ObservationSink,
    SessionControlAction,
    SessionControlRequest,
    SessionControlResult,
    SessionOpenResult,
    SessionPrompt,
    SessionTurnResult,
    TransportObservation,
    TransportObservationKind,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _assert_val_error(exc_info: pytest.ExceptionInfo[AudiaGenticError], pattern: str) -> None:
    """Assert the caught error is a VAL-TRANSPORT-* validation error."""
    assert exc_info.value.code.startswith("VAL-TRANSPORT-")
    if pattern:
        assert pattern in exc_info.value.message


# ── Enum membership ────────────────────────────────────────────────────────


class TestTransportObservationKind:
    def test_closed_set_values(self):
        expected = {
            "turn-accepted",
            "activity",
            "tool-requested",
            "tool-finished",
            "permission-requested",
            "terminal",
            "transport-error",
            "transport-closed",
            "transport-unknown",  # bounded unknown / drop-safe
            "in-progress",  # intermediate in-progress marker (AS19)
        }
        assert {k.value for k in TransportObservationKind} == expected

    def test_transport_unknown_exists(self):
        """Explicit bounded unknown is present (not raw native kind)."""
        assert TransportObservationKind.TRANSPORT_UNKNOWN.value == "transport-unknown"

    def test_no_raw_native_kinds(self):
        """No raw ACP/native kind values leak into the enum."""
        for kind in TransportObservationKind:
            assert (
                kind.value.startswith("turn-")
                or kind.value.startswith("activity")
                or kind.value.startswith("tool-")
                or kind.value.startswith("permission-")
                or kind.value.startswith("terminal")
                or kind.value.startswith("transport-")
                or kind.value == "in-progress"
            ), f"unexpected kind value: {kind.value}"


class TestControlDisposition:
    def test_all_dispositions_present(self):
        expected = {"accepted", "unsupported", "already-terminal", "rejected", "uncertain"}
        assert {d.value for d in ControlDisposition} == expected

    def test_acceptable_values(self):
        assert ControlDisposition.ACCEPTED.value == "accepted"
        assert ControlDisposition.UNSUPPORTED.value == "unsupported"
        assert ControlDisposition.ALREADY_TERMINAL.value == "already-terminal"
        assert ControlDisposition.REJECTED.value == "rejected"
        assert ControlDisposition.UNCERTAIN.value == "uncertain"


class TestCorrelationQuality:
    def test_all_qualities_present(self):
        expected = {"correlated", "request-scoped", "uncertain"}
        assert {q.value for q in CorrelationQuality} == expected

    def test_values(self):
        assert CorrelationQuality.CORRELATED.value == "correlated"
        assert CorrelationQuality.REQUEST_SCOPED.value == "request-scoped"
        assert CorrelationQuality.UNCERTAIN.value == "uncertain"


class TestSessionControlAction:
    """SessionControlAction is now defined in agent_session and re-exported from session_surface."""

    def test_all_actions_present(self):
        expected = {
            "cancel-turn",
            "interrupt-turn",
            "steer-turn",
            "respond-permission",
            "close-session",
        }
        assert {a.value for a in SessionControlAction} == expected

    def test_canonical_values(self):
        assert SessionControlAction.CANCEL_TURN.value == "cancel-turn"
        assert SessionControlAction.INTERRUPT_TURN.value == "interrupt-turn"
        assert SessionControlAction.STEER_TURN.value == "steer-turn"
        assert SessionControlAction.RESPOND_PERMISSION.value == "respond-permission"
        assert SessionControlAction.CLOSE_SESSION.value == "close-session"


# ── Frozen / immutability ──────────────────────────────────────────────────


class TestTransportObservation:
    def test_frozen(self):
        obs = TransportObservation(
            ag_session_id="ag-s-1",
            turn_id=None,
            sequence=0,
            kind=TransportObservationKind.TURN_ACCEPTED,
            observed_at="2025-01-01T00:00:00Z",
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            obs.kind = TransportObservationKind.ACTIVITY

    def test_valid_minimal(self):
        obs = TransportObservation(
            ag_session_id="ag-s-1",
            turn_id=None,
            sequence=None,
            kind=TransportObservationKind.TURN_ACCEPTED,
            observed_at="2025-01-01T00:00:00Z",
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
        )
        assert obs.ag_session_id == "ag-s-1"

    def test_valid_with_allowed_attributes(self):
        obs = TransportObservation(
            ag_session_id="ag-s-1",
            turn_id="turn-42",
            sequence=5,
            kind=TransportObservationKind.TOOL_REQUESTED,
            observed_at="2025-01-01T00:00:00Z",
            correlation_quality=CorrelationQuality.CORRELATED,
            attributes={"tool_call_id": "tc-1", "tool_status": "started"},
        )
        assert obs.attributes["tool_call_id"] == "tc-1"

    def test_empty_ag_session_id_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            )
        _assert_val_error(exc_info, "ag_session_id must not be empty")

    def test_non_string_ag_session_id_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id=12345,  # type: ignore
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            )
        _assert_val_error(exc_info, "ag_session_id must be a string")

    def test_sequence_negative_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=-1,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            )
        _assert_val_error(exc_info, "sequence must be a non-negative integer")

    def test_sequence_non_int_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence="five",  # type: ignore
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            )
        _assert_val_error(exc_info, "sequence must be a non-negative integer")

    def test_observed_at_empty_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            )
        _assert_val_error(exc_info, "observed_at must be a non-empty string")

    def test_turn_id_empty_string_ok_when_none(self):
        """turn_id=None is valid; turn_id="" should also fail validation."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id="",
                sequence=None,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            )
        _assert_val_error(exc_info, "turn_id must not be empty")


class TestRejectionOfRawNativeUnsafeAttributes:
    """TransportObservation rejects raw/native/unsafe attributes."""

    def test_rejects_unallowed_attribute_key_for_kind(self):
        """Only keys in the allowed set for the kind are accepted."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={"raw_kind": "agent_message_chunk"},  # not allowed for turn-accepted
            )
        _assert_val_error(exc_info, "attribute 'raw_kind' is not allowed")

    def test_rejects_provider_session_ref_as_attribute(self):
        """No provider session ref leaks into observation."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.ACTIVITY,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={"provider_session_ref": "some-ref"},
            )
        _assert_val_error(exc_info, "attribute 'provider_session_ref' is not allowed")

    def test_rejects_prompt_text_as_attribute(self):
        """No prompt text in observation attributes."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={"prompt": "hello world"},
            )
        _assert_val_error(exc_info, "attribute 'prompt' is not allowed")

    def test_rejects_output_text_as_attribute(self):
        """No output text in observation attributes."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TERMINAL,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={"output": "result text"},
            )
        _assert_val_error(exc_info, "attribute 'output' is not allowed")

    def test_rejects_callable_as_attribute_value(self):
        """Callables are rejected in attribute values."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={"reason": lambda: "callback"},  # type: ignore
            )
        _assert_val_error(exc_info, "carries a callable value")

    def test_rejects_dict_as_attribute_value(self):
        """Dicts are rejected in attribute values."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={"reason": {"nested": "dict"}},  # type: ignore
            )
        _assert_val_error(exc_info, "composite value")

    def test_rejects_list_as_attribute_value(self):
        """Lists are rejected in attribute values."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={"reason": ["list", "of", "values"]},  # type: ignore
            )
        _assert_val_error(exc_info, "composite value")

    def test_rejects_tool_arguments_as_attribute(self):
        """No tool arguments/results in observation attributes."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TOOL_REQUESTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={"tool_call_id": "tc-1", "tool_arguments": {"path": "/foo"}},  # type: ignore
            )
        _assert_val_error(exc_info, "attribute 'tool_arguments' is not allowed")

    def test_rejects_raw_event_payload_as_attribute(self):
        """Raw event payload keys are rejected."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.ACTIVITY,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={"payload": {"raw": "data"}},  # type: ignore
            )
        _assert_val_error(exc_info, "attribute 'payload' is not allowed")

    def test_transport_unknown_no_attributes(self):
        """TRANSPORT_UNKNOWN kind accepts no attributes — bounded unknown."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TRANSPORT_UNKNOWN,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.UNCERTAIN,
                attributes={"raw_kind": "some-native-event"},
            )
        _assert_val_error(exc_info, "attribute 'raw_kind' is not allowed")

    def test_transport_unknown_no_raw_kind_leak(self):
        """TRANSPORT_UNKNOWN never carries raw event name."""
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TRANSPORT_UNKNOWN,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.UNCERTAIN,
                attributes={"native_event": "agent_message_chunk"},
            )
        _assert_val_error(exc_info, "attribute 'native_event' is not allowed")

    def test_too_many_attributes_rejected(self):
        """Exceeding max attribute key count is rejected."""
        attrs = {f"reason_{i}": f"value_{i}" for i in range(20)}  # exceeds 16
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes=attrs,
            )
        # The first disallowed key error or too-many error should surface
        assert exc_info.value.code.startswith("VAL-TRANSPORT-")

    def test_attribute_value_exceeds_byte_bound(self):
        """Attribute string values exceeding 4 KiB are rejected."""
        big_value = "x" * 5000  # exceeds _MAX_SINGLE_ATTRIBUTE_VALUE_BYTES
        with pytest.raises(AudiaGenticError) as exc_info:
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id=None,
                sequence=None,
                kind=TransportObservationKind.TURN_ACCEPTED,
                observed_at="2025-01-01T00:00:00Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={"reason": big_value},
            )
        _assert_val_error(exc_info, "exceeds")


# ── SessionPrompt ───────────────────────────────────────────────────────────


class TestSessionPrompt:
    def test_frozen(self):
        prompt = SessionPrompt(turn_id="turn-1", body="hello")
        with pytest.raises(Exception):
            prompt.body = "world"

    def test_valid_minimal(self):
        prompt = SessionPrompt(turn_id="turn-1", body="hello world")
        assert prompt.turn_id == "turn-1"
        assert prompt.body == "hello world"
        assert prompt.cancel_token is None

    def test_turn_id_empty_rejected(self):
        with pytest.raises(AudiaGenticError):
            SessionPrompt(turn_id="", body="hello")

    def test_body_non_string_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionPrompt(turn_id="turn-1", body=b"binary")  # type: ignore
        _assert_val_error(exc_info, "body must be a string")

    def test_body_exceeds_byte_bound(self):
        big_body = "x" * (_MAX_PROMPT_BODY_BYTES + 1)
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionPrompt(turn_id="turn-1", body=big_body)
        _assert_val_error(exc_info, "exceeds")


# ── SessionOpenResult ──────────────────────────────────────────────────────


class TestSessionOpenResult:
    def test_frozen(self):
        result = SessionOpenResult(ag_session_id="ag-s-1")
        with pytest.raises(Exception):
            result.ag_session_id = "other"

    def test_valid(self):
        result = SessionOpenResult(ag_session_id="ag-s-1")
        assert result.ag_session_id == "ag-s-1"

    def test_empty_rejected(self):
        with pytest.raises(AudiaGenticError):
            SessionOpenResult(ag_session_id="")


# ── SessionTurnResult ──────────────────────────────────────────────────────


class TestSessionTurnResult:
    def test_frozen(self):
        result = SessionTurnResult(
            turn_id="turn-1",
            stop_reason=None,
            observations_delivered=5,
            dropped_observations=0,
        )
        with pytest.raises(Exception):
            result.stop_reason = "stopped"

    def test_valid_minimal(self):
        result = SessionTurnResult(
            turn_id="turn-1",
            stop_reason=None,
            observations_delivered=3,
            dropped_observations=0,
        )
        assert result.turn_id == "turn-1"
        assert result.observations_delivered == 3
        assert result.correlation_quality == CorrelationQuality.REQUEST_SCOPED

    def test_negative_delivered_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionTurnResult(
                turn_id="turn-1",
                stop_reason=None,
                observations_delivered=-1,
                dropped_observations=0,
            )
        _assert_val_error(exc_info, "non-negative integer")

    def test_negative_dropped_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionTurnResult(
                turn_id="turn-1",
                stop_reason=None,
                observations_delivered=0,
                dropped_observations=-1,
            )
        _assert_val_error(exc_info, "non-negative integer")

    def test_with_stop_reason(self):
        result = SessionTurnResult(
            turn_id="turn-1",
            stop_reason="stop",
            observations_delivered=5,
            dropped_observations=1,
        )
        assert result.stop_reason == "stop"
        assert result.dropped_observations == 1


# ── SessionControlRequest payload validation (default-deny) ────────────────


class TestSessionControlRequestPayloadValidation:
    """Control payload is default-deny: only canonical keys for specific actions."""

    def test_cancel_turn_no_payload(self):
        req = SessionControlRequest(
            ag_session_id="ag-s-1",
            turn_id=None,
            action=SessionControlAction.CANCEL_TURN,
        )
        assert req.payload == {}

    def test_cancel_turn_rejects_payload(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionControlRequest(
                ag_session_id="ag-s-1",
                turn_id=None,
                action=SessionControlAction.CANCEL_TURN,
                payload={"extra": "value"},
            )
        _assert_val_error(exc_info, "does not accept a payload")

    def test_close_session_no_payload(self):
        req = SessionControlRequest(
            ag_session_id="ag-s-1",
            turn_id=None,
            action=SessionControlAction.CLOSE_SESSION,
        )
        assert req.payload == {}

    def test_interruption_no_payload(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionControlRequest(
                ag_session_id="ag-s-1",
                turn_id=None,
                action=SessionControlAction.INTERRUPT_TURN,
                payload={"native_command": "stop"},
            )
        _assert_val_error(exc_info, "does not accept a payload")

    def test_respond_permission_allow(self):
        req = SessionControlRequest(
            ag_session_id="ag-s-1",
            turn_id=None,
            action=SessionControlAction.RESPOND_PERMISSION,
            payload={"permission": "allow"},
        )
        assert req.payload["permission"] == "allow"

    def test_respond_permission_deny(self):
        req = SessionControlRequest(
            ag_session_id="ag-s-1",
            turn_id=None,
            action=SessionControlAction.RESPOND_PERMISSION,
            payload={"permission": "deny"},
        )
        assert req.payload["permission"] == "deny"

    def test_respond_permission_invalid_value(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionControlRequest(
                ag_session_id="ag-s-1",
                turn_id=None,
                action=SessionControlAction.RESPOND_PERMISSION,
                payload={"permission": "maybe"},
            )
        _assert_val_error(exc_info, "must be one of")

    def test_respond_permission_missing_value(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionControlRequest(
                ag_session_id="ag-s-1",
                turn_id=None,
                action=SessionControlAction.RESPOND_PERMISSION,
                payload={},
            )
        _assert_val_error(exc_info, "requires a 'permission' value")

    def test_steer_turn_valid(self):
        req = SessionControlRequest(
            ag_session_id="ag-s-1",
            turn_id=None,
            action=SessionControlAction.STEER_TURN,
            payload={"steer_text": "try again with different approach"},
        )
        assert req.payload["steer_text"] == "try again with different approach"

    def test_steer_turn_missing_value(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionControlRequest(
                ag_session_id="ag-s-1",
                turn_id=None,
                action=SessionControlAction.STEER_TURN,
                payload={},
            )
        _assert_val_error(exc_info, "requires a 'steer_text' string value")

    def test_rejects_unknown_payload_key(self):
        """Default-deny: unknown keys in control payload are rejected."""
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionControlRequest(
                ag_session_id="ag-s-1",
                turn_id=None,
                action=SessionControlAction.RESPOND_PERMISSION,
                payload={"permission": "allow", "native_payload": {"raw": True}},  # type: ignore
            )
        _assert_val_error(exc_info, "not allowed")

    def test_rejects_native_escape_hatch_key(self):
        """No native escape hatch via arbitrary payload keys."""
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionControlRequest(
                ag_session_id="ag-s-1",
                turn_id=None,
                action=SessionControlAction.CANCEL_TURN,
                payload={"_native_command": "kill"},
            )
        _assert_val_error(exc_info, "does not accept a payload")

    def test_rejects_callable_payload_value(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionControlRequest(
                ag_session_id="ag-s-1",
                turn_id=None,
                action=SessionControlAction.RESPOND_PERMISSION,
                payload={"permission": lambda: True},  # type: ignore
            )
        _assert_val_error(exc_info, "callable")

    def test_rejects_composite_payload_value(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            SessionControlRequest(
                ag_session_id="ag-s-1",
                turn_id=None,
                action=SessionControlAction.RESPOND_PERMISSION,
                payload={"permission": ["allow"]},  # type: ignore
            )
        _assert_val_error(exc_info, "composite value")

    def test_frozen(self):
        req = SessionControlRequest(
            ag_session_id="ag-s-1",
            turn_id=None,
            action=SessionControlAction.CANCEL_TURN,
        )
        with pytest.raises(Exception):
            req.action = SessionControlAction.STEER_TURN


# ── SessionControlResult ───────────────────────────────────────────────────


class TestSessionControlResult:
    def test_frozen(self):
        result = SessionControlResult(disposition=ControlDisposition.ACCEPTED)
        with pytest.raises(Exception):
            result.disposition = ControlDisposition.REJECTED

    def test_valid_minimal(self):
        result = SessionControlResult(disposition=ControlDisposition.ACCEPTED)
        assert result.correlation_quality == CorrelationQuality.UNCERTAIN
        assert result.error_code is None

    def test_with_error_code(self):
        result = SessionControlResult(
            disposition=ControlDisposition.REJECTED,
            error_code="EXT-ACP-001",
        )
        assert result.disposition == ControlDisposition.REJECTED
        assert result.error_code == "EXT-ACP-001"

    def test_does_not_carry_session_state(self):
        """Result type has no field for session state — only disposition."""
        result = SessionControlResult(disposition=ControlDisposition.ACCEPTED)
        assert not any(f.name in ("session_state", "state", "is_active") for f in fields(result))


# ── Import boundary ────────────────────────────────────────────────────────


class TestImportBoundary:
    """agent_session.py must not import any components.* module."""

    def test_no_components_imports(self):
        mod = __import__(
            "audiagentic.foundation.transports.agent_session",
            fromlist=["AgentSessionTransport"],
        )
        source_code = _inspect_source(mod)
        for line in source_code.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for bad in ("from components", "import components", ".components."):
                if bad in stripped:
                    pytest.fail(
                        f"agent_session.py must not import components.* — found: {stripped!r}"
                    )

    def test_no_provider_native_imports(self):
        """No raw ACP/provider-native types imported."""
        mod = __import__(
            "audiagentic.foundation.transports.agent_session",
            fromlist=["AgentSessionTransport"],
        )
        source_code = _inspect_source(mod)
        for bad in ("AcpEvent", "AcpLaunch", "AcpResult", "AcpSessionTransport"):
            if f"import {bad}" in source_code or f"from.*{bad}" in source_code:
                pytest.fail(f"agent_session.py must not import {bad}")

    def test_exports_from_transports_package(self):
        """All new public symbols are importable from the transports __init__."""
        from audiagentic.foundation.transports import (
            AgentSessionTransport,
            ControlDisposition,
            CorrelationQuality,
            SessionControlAction,
        )

        assert AgentSessionTransport is not None
        assert ControlDisposition.ACCEPTED.value == "accepted"
        assert CorrelationQuality.CORRELATED.value == "correlated"
        assert SessionControlAction.CANCEL_TURN.value == "cancel-turn"

    def test_session_control_action_reexported_from_session_surface(self):
        """SessionControlAction is re-exportable from session_surface for backward compat."""
        # Must be the same class
        from audiagentic.foundation.transports.agent_session import (
            SessionControlAction as SCA_agent,
        )
        from audiagentic.foundation.transports.session_surface import (
            SessionControlAction as SCA,
        )

        assert SCA is SCA_agent


# ── Protocol conformance with fake transport ───────────────────────────────


class _FakeAgentSessionTransport:
    """Minimal fake implementation of AgentSessionTransport for protocol testing."""

    async def open(self) -> SessionOpenResult:
        return SessionOpenResult(ag_session_id="fake-s-1")

    async def prompt(
        self,
        request: SessionPrompt,
        sink: ObservationSink,
    ) -> SessionTurnResult:
        # Deliver a bounded observation to the sink
        obs = TransportObservation(
            ag_session_id="fake-s-1",
            turn_id=request.turn_id,
            sequence=0,
            kind=TransportObservationKind.TURN_ACCEPTED,
            observed_at="2025-01-01T00:00:00Z",
            correlation_quality=CorrelationQuality.CORRELATED,
        )
        result = sink(obs)
        if asyncio.iscoroutine(result):
            await result
        return SessionTurnResult(
            turn_id=request.turn_id,
            stop_reason="stop",
            observations_delivered=1,
            dropped_observations=0,
        )

    async def control(
        self,
        request: SessionControlRequest,
    ) -> SessionControlResult:
        return SessionControlResult(
            disposition=ControlDisposition.ACCEPTED,
            correlation_quality=CorrelationQuality.UNCERTAIN,
        )

    async def close(self) -> None:
        pass

    def is_alive(self) -> bool:
        return True


class TestProtocolConformance:
    """Fake transport proves AgentSessionTransport protocol conformance."""

    @pytest.mark.asyncio
    async def test_open_returns_ag_session_id(self):
        transport = _FakeAgentSessionTransport()
        result = await transport.open()
        assert isinstance(result, SessionOpenResult)
        assert result.ag_session_id == "fake-s-1"

    @pytest.mark.asyncio
    async def test_prompt_delivers_observations(self):
        transport = _FakeAgentSessionTransport()
        delivered: list[TransportObservation] = []

        async def sink(obs: TransportObservation) -> None:
            delivered.append(obs)

        prompt = SessionPrompt(turn_id="fake-turn-1", body="hello")
        result = await transport.prompt(prompt, sink)
        assert isinstance(result, SessionTurnResult)
        assert len(delivered) == 1
        assert delivered[0].kind == TransportObservationKind.TURN_ACCEPTED
        assert delivered[0].ag_session_id == "fake-s-1"

    @pytest.mark.asyncio
    async def test_control_returns_disposition(self):
        transport = _FakeAgentSessionTransport()
        req = SessionControlRequest(
            ag_session_id="fake-s-1",
            turn_id=None,
            action=SessionControlAction.CANCEL_TURN,
        )
        result = await transport.control(req)
        assert isinstance(result, SessionControlResult)
        assert result.disposition == ControlDisposition.ACCEPTED

    @pytest.mark.asyncio
    async def test_close_is_safe(self):
        transport = _FakeAgentSessionTransport()
        await transport.close()  # should not raise

    def test_is_alive(self):
        transport = _FakeAgentSessionTransport()
        assert transport.is_alive() is True

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        transport = _FakeAgentSessionTransport()
        open_result = await transport.open()
        assert open_result.ag_session_id == "fake-s-1"
        prompt = SessionPrompt(turn_id="t-1", body="test")

        async def sink(obs: TransportObservation) -> None:
            pass

        result = await transport.prompt(prompt, sink)
        assert result.observations_delivered >= 0
        req = SessionControlRequest(
            ag_session_id=open_result.ag_session_id,
            turn_id=None,
            action=SessionControlAction.CANCEL_TURN,
        )
        ctrl_result = await transport.control(req)
        assert ctrl_result.disposition in (
            ControlDisposition.ACCEPTED,
            ControlDisposition.ALREADY_TERMINAL,
        )
        await transport.close()

    @pytest.mark.asyncio
    async def test_protocol_accepts_fake(self):
        """Runtime check: _FakeAgentSessionTransport satisfies the Protocol."""
        transport: AgentSessionTransport = _FakeAgentSessionTransport()
        result = await transport.open()
        assert isinstance(result, SessionOpenResult)


# ── Scalar-only / redaction discipline ─────────────────────────────────────


class TestScalarOnlyDiscipline:
    """All foundation transport dataclasses contain no callables or native payloads."""

    def test_transport_observation_no_callables(self):
        obs = TransportObservation(
            ag_session_id="ag-s-1",
            turn_id=None,
            sequence=0,
            kind=TransportObservationKind.TURN_ACCEPTED,
            observed_at="2025-01-01T00:00:00Z",
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
        )
        _assert_no_callables(obs)

    def test_session_prompt_no_callables(self):
        prompt = SessionPrompt(turn_id="t-1", body="hello")
        _assert_no_callables(prompt)

    def test_session_open_result_no_callables(self):
        result = SessionOpenResult(ag_session_id="ag-s-1")
        _assert_no_callables(result)

    def test_session_turn_result_no_callables(self):
        result = SessionTurnResult(
            turn_id="t-1",
            stop_reason=None,
            observations_delivered=0,
            dropped_observations=0,
        )
        _assert_no_callables(result)

    def test_session_control_request_no_callables(self):
        req = SessionControlRequest(
            ag_session_id="ag-s-1",
            turn_id=None,
            action=SessionControlAction.CANCEL_TURN,
        )
        _assert_no_callables(req)

    def test_session_control_result_no_callables(self):
        result = SessionControlResult(disposition=ControlDisposition.ACCEPTED)
        _assert_no_callables(result)


def _inspect_source(module: Any) -> str:
    """Get source of a module as string."""
    import inspect

    return inspect.getsource(module)


def _assert_no_callables(obj: Any, path: str = "") -> None:
    """Recursively assert that no field of *obj* is a callable (function/method/lambdas)."""
    if is_dataclass(obj):
        for f in fields(obj):
            _assert_no_callables(getattr(obj, f.name), f"{path}.{f.name}")
    elif isinstance(obj, dict):
        for key, value in obj.items():
            _assert_no_callables(value, f"{path}[{key}]")
    elif isinstance(obj, (tuple, list)):
        for i, value in enumerate(obj):
            _assert_no_callables(value, f"{path}[{i}]")
    elif callable(obj) and not isinstance(obj, (str, int, float, bool, type(None))):
        import enum

        if isinstance(obj, enum.Enum):
            return
        raise AssertionError(f"Unexpected callable at {path or 'root'}: {obj!r}")
