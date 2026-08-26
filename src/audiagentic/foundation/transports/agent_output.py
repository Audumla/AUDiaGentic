"""AS31 — Bounded agent output delivery contract (Stage 1: foundation).

Defines frozen, scalar-safe value types for streaming assistant text output.
No ``components.*`` imports, no provider-native payloads, no tool details,
no thought/reasoning fields, no arbitrary metadata.

This contract is intentionally separate from:
- StatusEvidence (AS19) — lifecycle evidence with different retention rules
- SessionTurnResult (AS28) — carries bounded final_summary but not streaming
  output fragments
- ComponentOutputEvent — component logging/progress, not assistant content
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from audiagentic.foundation.contracts.errors import make_error

# ---------------------------------------------------------------------------
# Coded error constants (registered in foundation/error-resolutions.yaml)
# ---------------------------------------------------------------------------

ERR_OUTPUT_EMPTY_TEXT = "VAL-OUTPUT-001"
ERR_OUTPUT_OVERSIZED_TEXT = "VAL-OUTPUT-002"
ERR_OUTPUT_INVALID_SESSION_ID = "VAL-OUTPUT-003"
ERR_OUTPUT_INVALID_TURN_ID = "VAL-OUTPUT-004"
ERR_OUTPUT_NON_MONOTONIC_SEQUENCE = "VAL-OUTPUT-005"
ERR_OUTPUT_UNKNOWN_KIND = "VAL-OUTPUT-006"
ERR_OUTPUT_INVALID_OBSERVED_AT = "VAL-OUTPUT-007"
ERR_OUTPUT_INVALID_IS_FINAL = "VAL-OUTPUT-008"

# ---------------------------------------------------------------------------
# Bounded constants
# ---------------------------------------------------------------------------

_MAX_ID_LENGTH = 256
MAX_OUTPUT_TEXT_BYTES = 65_536  # 64 KiB per fragment


# ---------------------------------------------------------------------------
# AgentOutputKind (closed set — Stage 1: text only, no tool-summary)
# ---------------------------------------------------------------------------

class AgentOutputKind(StrEnum):
    """Bounded neutral output kind vocabulary.

    Closed set; new kinds require a plan review. Stage 1 carries only
    assistant text deltas and final markers — no reasoning, tool details,
    or metadata.
    """

    ASSISTANT_TEXT_DELTA = "assistant-text-delta"
    ASSISTANT_FINAL = "assistant-final"


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def _validate_id(value: str | None, name: str) -> None:
    """Validate an ID string is non-empty and bounded, or None where allowed."""
    if value is None:
        if name == "session_id":
            raise make_error(prefix="VAL", component="OUTPUT", number=3, kind="agent-output-validation", message=f"{name} must not be null", details={"field": name})
        raise make_error(prefix="VAL", component="OUTPUT", number=4, kind="agent-output-validation", message=f"{name} must not be null", details={"field": name})
    if not isinstance(value, str):
        if name == "session_id":
            raise make_error(prefix="VAL", component="OUTPUT", number=3, kind="agent-output-validation", message=f"{name} must be a string", details={"field": name})
        raise make_error(prefix="VAL", component="OUTPUT", number=4, kind="agent-output-validation", message=f"{name} must be a string", details={"field": name})
    if not value:
        if name == "session_id":
            raise make_error(prefix="VAL", component="OUTPUT", number=3, kind="agent-output-validation", message=f"{name} must not be empty", details={"field": name})
        raise make_error(prefix="VAL", component="OUTPUT", number=4, kind="agent-output-validation", message=f"{name} must not be empty", details={"field": name})
    if len(value) > _MAX_ID_LENGTH:
        raise make_error(
            prefix="VAL", component="OUTPUT", number=5,
            kind="agent-output-validation",
            message=f"{name} exceeds maximum length of {_MAX_ID_LENGTH}",
            details={"field": name, "length": len(value)},
        )


# ---------------------------------------------------------------------------
# AgentOutputEvent (frozen dataclass)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentOutputEvent:
    """A single bounded agent output event.

    Carries only session/turn IDs, a monotonic sequence number, a closed-set
    kind, and text content. No thought, tool arguments/results, native payload,
    native event name, callables, or arbitrary metadata.

    ``text`` is bounded to 64 KiB per fragment. ``sequence`` must be
    strictly increasing within a turn (or None). ``kind`` is from the closed
    :class:`AgentOutputKind` enum.

    This type is foundation-neutral: no provider-specific imports or types.
    """

    session_id: str
    turn_id: str
    sequence: int | None
    kind: AgentOutputKind
    text: str
    observed_at: str
    is_final: bool

    def __post_init__(self) -> None:
        # Validate IDs
        _validate_id(self.session_id, "session_id")
        _validate_id(self.turn_id, "turn_id")

        # Validate sequence: non-negative integer or None
        if self.sequence is not None:
            if not isinstance(self.sequence, int) or self.sequence < 0:
                raise make_error(
                    prefix="VAL", component="OUTPUT", number=5,
                    kind="agent-output-validation",
                    message="sequence must be a non-negative integer or None",
                    details={"value": self.sequence},
                )

        # Validate kind is from the closed enum (type narrowing)
        if not isinstance(self.kind, AgentOutputKind):
            raise make_error(
                prefix="VAL", component="OUTPUT", number=6,
                kind="agent-output-validation",
                message=f"unknown output kind {self.kind!r}; "
                        f"allowed: {[k.value for k in AgentOutputKind]}",
                details={"value": self.kind, "allowed": [k.value for k in AgentOutputKind]},
            )

        # Validate text: non-empty, bounded to 64 KiB
        if not isinstance(self.text, str):
            raise make_error(
                prefix="VAL", component="OUTPUT", number=1,
                kind="agent-output-validation",
                message="text must be a string",
            )
        if not self.text:
            raise make_error(
                prefix="VAL", component="OUTPUT", number=1,
                kind="agent-output-validation",
                message="text must not be empty",
            )
        text_bytes = len(self.text.encode("utf-8"))
        if text_bytes > MAX_OUTPUT_TEXT_BYTES:
            raise make_error(
                prefix="VAL", component="OUTPUT", number=2,
                kind="agent-output-validation",
                message=f"text exceeds maximum of {MAX_OUTPUT_TEXT_BYTES} bytes "
                        f"({text_bytes} bytes)",
                details={"byte-length": text_bytes},
            )

        # Validate observed_at: non-empty ISO-8601 string
        if not isinstance(self.observed_at, str) or not self.observed_at:
            raise make_error(
                prefix="VAL", component="OUTPUT", number=7,
                kind="agent-output-validation",
                message="observed_at must be a non-empty string (ISO-8601)",
            )

        # Validate is_final: boolean
        if not isinstance(self.is_final, bool):
            raise make_error(
                prefix="VAL", component="OUTPUT", number=8,
                kind="agent-output-validation",
                message="is_final must be a boolean",
            )


# ---------------------------------------------------------------------------
# OutputSink (Protocol)
# ---------------------------------------------------------------------------

class OutputSink(Protocol):
    """Callable that receives bounded agent output events.

    Used by provider adapters to deliver streaming assistant text
    fragments to the gateway session pipeline without exposing raw
    provider events.

    This is a simple async callback protocol — distinct from
    :class:`ObservationSink` (AS28, transport observations) and
    ``ComponentOutputSink`` (component logging/progress).
    """

    def __call__(self, event: AgentOutputEvent) -> Awaitable[None] | None: ...
