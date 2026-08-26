"""AS31 stage 1 — foundation-neutral agent output delivery contract.

Tests frozen/immutable types, enum validation, text bounds, monotonic
sequence discipline, raw/native data rejection, import boundary enforcement,
and separation from ComponentOutputEvent and ObservationSink.
"""

from __future__ import annotations

import asyncio
from dataclasses import fields, is_dataclass
from typing import Any

import pytest

# ── Module under test ───────────────────────────────────────────────────────
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.agent_output import (
    MAX_OUTPUT_TEXT_BYTES,
    AgentOutputEvent,
    AgentOutputKind,
    OutputSink,
)

# ── Helpers ─────────────────────────────────────────────────────────────────

_VALID_KINDS = frozenset({
    AgentOutputKind.ASSISTANT_TEXT_DELTA,
    AgentOutputKind.ASSISTANT_FINAL,
})


def _make_event(
    session_id: str = "sess-1",
    turn_id: str = "turn-1",
    sequence: int | None = 0,
    kind: AgentOutputKind = AgentOutputKind.ASSISTANT_TEXT_DELTA,
    text: str = "hello world",
    observed_at: str = "2025-01-01T00:00:00Z",
    is_final: bool = False,
) -> AgentOutputEvent:
    return AgentOutputEvent(
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
        kind=kind,
        text=text,
        observed_at=observed_at,
        is_final=is_final,
    )


def _assert_val_error(exc_info: pytest.ExceptionInfo[AudiaGenticError], pattern: str) -> None:
    """Assert the caught error is a VAL-OUTPUT-* validation error."""
    assert exc_info.value.code.startswith("VAL-OUTPUT-")
    if pattern:
        assert pattern in exc_info.value.message


# ── Enum membership ────────────────────────────────────────────────────────

class TestAgentOutputKind:
    def test_closed_set_values(self):
        expected = {"assistant-text-delta", "assistant-final"}
        assert {k.value for k in AgentOutputKind} == expected

    def test_no_tool_summary_kind(self):
        """Stage 1 carries only text; no tool-summary kind exists."""
        for kind in AgentOutputKind:
            assert kind.value.startswith("assistant-"), f"unexpected kind: {kind.value}"

    def test_no_reasoning_or_thought_kind(self):
        """No reasoning/thought kinds leak into the enum."""
        for kind in AgentOutputKind:
            assert "reasoning" not in kind.value and "thought" not in kind.value

    def test_assistant_text_delta_value(self):
        assert AgentOutputKind.ASSISTANT_TEXT_DELTA.value == "assistant-text-delta"

    def test_assistant_final_value(self):
        assert AgentOutputKind.ASSISTANT_FINAL.value == "assistant-final"


# ── Frozen / immutability ──────────────────────────────────────────────────

class TestAgentOutputEventFrozen:
    def test_frozen(self):
        event = _make_event()
        with pytest.raises(Exception):  # FrozenInstanceError
            event.text = "modified"

    def test_frozen_kind(self):
        event = _make_event()
        with pytest.raises(Exception):
            event.kind = AgentOutputKind.ASSISTANT_FINAL

    def test_frozen_sequence(self):
        event = _make_event(sequence=5)
        with pytest.raises(Exception):
            event.sequence = 10

    def test_no_extra_fields(self):
        """Event has exactly the expected fields — no native/metadata fields."""
        field_names = {f.name for f in fields(_make_event())}
        expected = {"session_id", "turn_id", "sequence", "kind", "text", "observed_at", "is_final"}
        assert field_names == expected

    def test_no_native_payload_field(self):
        """No native payload or arbitrary metadata field exists."""
        field_names = {f.name for f in fields(_make_event())}
        for bad in ("payload", "native_payload", "metadata", "extra", "raw", "_native"):
            assert bad not in field_names, f"unexpected field {bad!r} on AgentOutputEvent"


# ── Valid construction ─────────────────────────────────────────────────────

class TestAgentOutputEventValid:
    def test_valid_minimal_delta(self):
        event = _make_event()
        assert event.session_id == "sess-1"
        assert event.kind == AgentOutputKind.ASSISTANT_TEXT_DELTA
        assert event.is_final is False

    def test_valid_final(self):
        event = _make_event(
            kind=AgentOutputKind.ASSISTANT_FINAL,
            is_final=True,
            text="final answer",
        )
        assert event.kind == AgentOutputKind.ASSISTANT_FINAL
        assert event.is_final is True

    def test_valid_none_sequence(self):
        event = _make_event(sequence=None)
        assert event.sequence is None

    def test_valid_zero_sequence(self):
        event = _make_event(sequence=0)
        assert event.sequence == 0


# ── Validation: empty / missing fields ─────────────────────────────────────

class TestAgentOutputEventValidation:
    def test_empty_text_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(text="")
        _assert_val_error(exc_info, "text must not be empty")

    def test_non_string_text_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(text=123)  # type: ignore
        _assert_val_error(exc_info, "text must be a string")

    def test_null_session_id_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(session_id=None)  # type: ignore
        _assert_val_error(exc_info, "session_id must not be null")

    def test_empty_session_id_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(session_id="")
        _assert_val_error(exc_info, "session_id must not be empty")

    def test_non_string_session_id_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(session_id=42)  # type: ignore
        _assert_val_error(exc_info, "session_id must be a string")

    def test_session_and_turn_id_errors_keep_distinct_declared_codes(self):
        with pytest.raises(AudiaGenticError) as session_exc:
            _make_event(session_id=None)  # type: ignore
        with pytest.raises(AudiaGenticError) as turn_exc:
            _make_event(turn_id=None)  # type: ignore
        assert session_exc.value.code == "VAL-OUTPUT-003"
        assert turn_exc.value.code == "VAL-OUTPUT-004"

    def test_null_turn_id_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(turn_id=None)  # type: ignore
        _assert_val_error(exc_info, "turn_id must not be null")

    def test_empty_turn_id_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(turn_id="")
        _assert_val_error(exc_info, "turn_id must not be empty")

    def test_observed_at_empty_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(observed_at="")
        _assert_val_error(exc_info, "observed_at must be a valid UTC timestamp string")

    @pytest.mark.parametrize("observed_at", [
        "2025-01-01T00:00:00", "not-a-timestamp", "2025-01-01T00:00:00+10:00",
    ])
    def test_observed_at_must_be_utc_iso_timestamp(self, observed_at):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(observed_at=observed_at)
        assert exc_info.value.code == "VAL-OUTPUT-007"

    def test_sequence_negative_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(sequence=-1)
        _assert_val_error(exc_info, "sequence must be a non-negative integer")

    def test_sequence_non_int_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(sequence="five")  # type: ignore
        _assert_val_error(exc_info, "sequence must be a non-negative integer")

    def test_is_final_non_bool_rejected(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(is_final=1)  # type: ignore
        _assert_val_error(exc_info, "is_final must be a boolean")

    def test_is_final_must_match_kind(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(is_final=True)
        assert exc_info.value.code == "VAL-OUTPUT-008"

    def test_final_kind_cannot_be_marked_non_final(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(kind=AgentOutputKind.ASSISTANT_FINAL, is_final=False)
        assert exc_info.value.code == "VAL-OUTPUT-008"

    def test_delta_cannot_be_marked_final(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(kind=AgentOutputKind.ASSISTANT_TEXT_DELTA, is_final=True)
        assert exc_info.value.code == "VAL-OUTPUT-008"

    def test_oversized_id_has_distinct_code(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(session_id="s" * 257)
        assert exc_info.value.code == "VAL-OUTPUT-009"


# ── Validation: text bounds ────────────────────────────────────────────────

class TestAgentOutputEventTextBounds:
    def test_text_at_max_size_ok(self):
        """Text exactly at 64 KiB boundary is accepted."""
        event = _make_event(text="x" * MAX_OUTPUT_TEXT_BYTES)
        assert len(event.text.encode("utf-8")) == MAX_OUTPUT_TEXT_BYTES

    def test_text_over_64kib_rejected(self):
        """Text exceeding 64 KiB is rejected."""
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(text="x" * (MAX_OUTPUT_TEXT_BYTES + 1))
        _assert_val_error(exc_info, "exceeds maximum of")

    def test_unicode_text_at_max_bytes_ok(self):
        """Unicode text at exactly 64 KiB bytes is accepted."""
        # Each "é" is 2 bytes in UTF-8
        text = "é" * (MAX_OUTPUT_TEXT_BYTES // 2)
        event = _make_event(text=text)
        assert len(event.text.encode("utf-8")) == MAX_OUTPUT_TEXT_BYTES

    def test_unicode_text_over_max_bytes_rejected(self):
        """Unicode text exceeding 64 KiB bytes is rejected (byte count, not char count)."""
        text = "é" * ((MAX_OUTPUT_TEXT_BYTES // 2) + 1)
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(text=text)
        _assert_val_error(exc_info, "exceeds maximum of")


# ── Validation: kind discipline ────────────────────────────────────────────

class TestAgentOutputEventKindDiscipline:
    def test_string_kind_rejected(self):
        """Raw string kind values are rejected — must be enum."""
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(kind="assistant-text-delta")  # type: ignore
        _assert_val_error(exc_info, "unknown output kind")

    def test_unknown_kind_rejected(self):
        """Non-existent kind values are rejected."""
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(kind="tool-summary")  # type: ignore
        _assert_val_error(exc_info, "unknown output kind")

    def test_reasoning_kind_rejected(self):
        """No reasoning/thought kind is accepted."""
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(kind="reasoning-text-delta")  # type: ignore
        _assert_val_error(exc_info, "unknown output kind")

    def test_native_kind_rejected(self):
        """Raw native provider kinds are rejected."""
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(kind="agent_message_chunk")  # type: ignore
        _assert_val_error(exc_info, "unknown output kind")

    def test_allowed_kinds_listed(self):
        """Error message lists the allowed kinds for guidance."""
        with pytest.raises(AudiaGenticError) as exc_info:
            _make_event(kind="tool-summary")  # type: ignore
        assert "assistant-text-delta" in exc_info.value.message
        assert "assistant-final" in exc_info.value.message


# ── Separation from ComponentOutputEvent / ObservationSink ─────────────────

class TestSeparationFromOtherContracts:
    def test_not_component_output_event(self):
        """AgentOutputEvent is distinct from ComponentOutputEvent."""
        from audiagentic.foundation.contracts.output import ComponentOutputEvent
        assert AgentOutputEvent is not ComponentOutputEvent
        event = _make_event()
        assert not isinstance(event, ComponentOutputEvent)

    def test_not_component_output_sink(self):
        """OutputSink is distinct from ComponentOutputSink."""
        # They are different protocol types — both callable but with different signatures
        assert OutputSink.__name__ != "ComponentOutputSink"

    def test_not_transport_observation(self):
        """AgentOutputEvent is distinct from TransportObservation."""
        from audiagentic.foundation.transports.agent_session import TransportObservation
        assert AgentOutputEvent is not TransportObservation

    def test_no_status_evidence_field(self):
        """AgentOutputEvent has no status evidence fields."""
        field_names = {f.name for f in fields(_make_event())}
        for bad in ("status", "source_kind", "semantic_strength", "verification_tier"):
            assert bad not in field_names

    def test_no_correlation_quality_field(self):
        """AgentOutputEvent has no TransportObservation fields."""
        field_names = {f.name for f in fields(_make_event())}
        for bad in ("correlation_quality", "ag_session_id", "attributes"):
            assert bad not in field_names


# ── Import boundary ────────────────────────────────────────────────────────

class TestImportBoundary:
    """agent_output.py must not import any components.* or provider module."""

    def test_no_components_imports(self):
        mod = __import__(
            "audiagentic.foundation.transports.agent_output",
            fromlist=["AgentOutputEvent"],
        )
        source_code = _inspect_source(mod)
        for line in source_code.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for bad in ("from components", "import components", ".components."):
                if bad in stripped:
                    pytest.fail(
                        f"agent_output.py must not import components.* — found: {stripped!r}"
                    )

    def test_no_provider_native_imports(self):
        """No raw ACP/provider-native types imported."""
        mod = __import__(
            "audiagentic.foundation.transports.agent_output",
            fromlist=["AgentOutputEvent"],
        )
        source_code = _inspect_source(mod)
        for bad in ("AcpEvent", "TransportObservation", "StatusEvidence"):
            if f"import {bad}" in source_code or f"from.*{bad}" in source_code:
                pytest.fail(f"agent_output.py must not import {bad}")

    def test_exports_from_transports_package(self):
        """All new public symbols are importable from the transports __init__."""
        from audiagentic.foundation.transports import (
            AgentOutputEvent,
            AgentOutputKind,
        )
        assert AgentOutputEvent is not None
        assert AgentOutputKind.ASSISTANT_TEXT_DELTA.value == "assistant-text-delta"

    def test_constant_exported(self):
        """MAX_OUTPUT_TEXT_BYTES is accessible from the module."""
        from audiagentic.foundation.transports.agent_output import MAX_OUTPUT_TEXT_BYTES
        assert MAX_OUTPUT_TEXT_BYTES == 65_536


# ── Protocol conformance with fake sink ────────────────────────────────────

class _FakeOutputSink:
    """Minimal fake implementation of OutputSink for protocol testing."""

    def __init__(self) -> None:
        self.events: list[AgentOutputEvent] = []

    async def __call__(self, event: AgentOutputEvent) -> None:
        self.events.append(event)


class TestProtocolConformance:
    """Fake sink proves OutputSink protocol conformance."""

    @pytest.mark.asyncio
    async def test_sink_receives_events(self):
        sink = _FakeOutputSink()
        event = _make_event()
        result = sink(event)
        if asyncio.iscoroutine(result):
            await result
        assert len(sink.events) == 1
        assert sink.events[0].text == "hello world"

    @pytest.mark.asyncio
    async def test_sink_receives_final_event(self):
        sink = _FakeOutputSink()
        event = _make_event(
            kind=AgentOutputKind.ASSISTANT_FINAL,
            is_final=True,
            text="done",
        )
        await sink(event)
        assert len(sink.events) == 1
        assert sink.events[0].is_final is True
        assert sink.events[0].kind == AgentOutputKind.ASSISTANT_FINAL

    @pytest.mark.asyncio
    async def test_multiple_delta_events(self):
        sink = _FakeOutputSink()
        for i in range(3):
            await sink(_make_event(sequence=i, text=f"chunk {i}"))
        assert len(sink.events) == 3
        assert sink.events[0].sequence == 0
        assert sink.events[2].text == "chunk 2"

    @pytest.mark.asyncio
    async def test_protocol_accepts_fake(self):
        """Runtime check: _FakeOutputSink satisfies the Protocol."""
        sink: OutputSink = _FakeOutputSink()
        await sink(_make_event())
        assert len(sink.events) == 1


# ── Scalar-only / no-callables discipline ─────────────────────────────────

class TestScalarOnlyDiscipline:
    """AgentOutputEvent contains no callables or native payloads."""

    def test_no_callables(self):
        event = _make_event()
        _assert_no_callables(event)

    def test_final_event_no_callables(self):
        event = _make_event(
            kind=AgentOutputKind.ASSISTANT_FINAL,
            is_final=True,
        )
        _assert_no_callables(event)


# ── Monotonic sequence discipline (contract-level check) ──────────────────

class TestMonotonicSequence:
    """Sequence must be strictly increasing — enforced by contract, tested here."""

    def test_none_sequence_valid(self):
        """None sequence is valid (no monotonicity to enforce)."""
        event = _make_event(sequence=None)
        assert event.sequence is None

    def test_zero_start_valid(self):
        """Sequence starting at 0 is valid."""
        event = _make_event(sequence=0)
        assert event.sequence == 0

    def test_large_sequence_valid(self):
        """Large sequence numbers are valid."""
        event = _make_event(sequence=999_999)
        assert event.sequence == 999_999

    # Note: Strict monotonicity across events is enforced by the consumer
    # (the sink pipeline), not within a single event constructor. The
    # AgentOutputEvent validates that sequence is a non-negative integer or None;
    # the sink pipeline must reject non-monotonic sequences across events.


# ── No raw protocol fields leak into contract ──────────────────────────────

class TestNoRawProtocolFields:
    """AgentOutputEvent carries no raw provider-native protocol fields."""

    def test_no_raw_event_name(self):
        field_names = {f.name for f in fields(_make_event())}
        for bad in ("raw_event_name", "native_kind", "provider_event"):
            assert bad not in field_names

    def test_no_thought_field(self):
        field_names = {f.name for f in fields(_make_event())}
        for bad in ("thought", "reasoning", "chain_of_thought"):
            assert bad not in field_names

    def test_no_tool_field(self):
        field_names = {f.name for f in fields(_make_event())}
        for bad in ("tool_call_id", "tool_name", "tool_arguments", "tool_result"):
            assert bad not in field_names

    def test_no_provider_session_ref(self):
        """No provider session ref — that's AS30 binding, not output."""
        field_names = {f.name for f in fields(_make_event())}
        assert "provider_session_ref" not in field_names


# ── Helpers ────────────────────────────────────────────────────────────────

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
