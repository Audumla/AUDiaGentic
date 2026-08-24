"""AS31 Stage-2 — Agent output relay and persistence.

Owns the agents-side relay that handles streaming output delivery and
persistence. Sits between provider adapters (which produce raw output events)
and the OutputSink contract (AS31 Stage-1). Enforces fragment bounds,
sequence monotonicity, per-turn byte caps, and graceful degradation.

Design principles:
- Relay failure NEVER fails the turn — log and degrade silently
- Fragment bounds are enforced (64KiB text max, configurable)
- Sequence is strictly increasing or None within a turn
- Per-turn byte cap prevents runaway output (512KB default, configurable)
- Each event write is atomic (crash-safe via temp+replace)
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import gateway_final_response_path
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.foundation.io import (
    atomic_write_bytes,
    atomic_write_json,
    load_ndjson,
)
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.agent_output import (
    AgentOutputEvent,
    OutputSink,
)
from audiagentic.foundation.transports.session_surface import (
    ContentChannelId,
    ResolvedSessionSurface,
)

logger = logging.getLogger(__name__)

FINAL_RESPONSE_PREVIEW_BYTES = 4096


def _utf8_preview(text: str, limit: int = FINAL_RESPONSE_PREVIEW_BYTES) -> tuple[str, bool]:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text, False
    marker = "\n…[truncated]"
    marker_bytes = marker.encode("utf-8")
    body_limit = max(0, limit - len(marker_bytes))
    body = raw[:body_limit].decode("utf-8", errors="ignore")
    preview = (body + marker).encode("utf-8")[:limit].decode("utf-8", errors="ignore")
    return preview, True


def persist_final_response(project_root: Path, request_id: str, text: str) -> dict[str, Any]:
    """Persist the exact terminal UTF-8 response before terminal record commit."""
    if not isinstance(text, str):
        text = str(text)
    path = gateway_final_response_path(project_root, request_id)
    raw = text.encode("utf-8")
    atomic_write_bytes(path, raw)
    preview, truncated = _utf8_preview(text)
    return {
        "artifact-id": "final-response",
        "request-id": request_id,
        "media-type": "text/plain; charset=utf-8",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "output-preview": preview,
        "output-truncated": truncated,
    }


def read_final_response(project_root: Path, request_id: str, artifact: dict[str, Any]) -> str:
    """Read and verify the fixed request-owned terminal artifact."""
    path = gateway_final_response_path(project_root, request_id)
    raw = path.read_bytes()
    if len(raw) != artifact.get("bytes") or hashlib.sha256(raw).hexdigest() != artifact.get("sha256"):
        raise AudiaGenticError(code="CON-AGW-140", kind="agents", message="gateway response artifact integrity check failed", details={})
    return raw.decode("utf-8")

# ── Coded error constants ────────────────────────────────────────────────

ERR_OUTPUT_SEQUENCE_NOT_MONOTONIC = "VAL-OUTPUT-RELAY-001"
ERR_OUTPUT_OVERSIZED_FRAGMENT = "VAL-OUTPUT-RELAY-002"
ERR_OUTPUT_TURN_CAP_EXCEEDED = "VAL-OUTPUT-RELAY-003"
ERR_OUTPUT_RELAY_DISABLED = "VAL-OUTPUT-RELAY-004"
ERR_OUTPUT_CHANNEL_UNAUTHORIZED = "VAL-OUTPUT-RELAY-005"

# ── Default policy constants ─────────────────────────────────────────────

DEFAULT_MAX_FRAGMENT_BYTES = 65_536       # 64 KiB per fragment
DEFAULT_MAX_TURN_BYTES = 524_288          # 512 KiB per turn
_DEFAULT_ENABLED = False                   # disabled until surface validated


# ── Policy configuration ─────────────────────────────────────────────────

@dataclass(frozen=True)
class OutputPolicy:
    """Immutable output relay policy.

    Loaded from component config at startup; validated at construction.
    Default: disabled with 64KiB fragment cap and 512KiB turn cap.
    """

    enabled: bool
    max_fragment_bytes: int
    max_turn_bytes: int

    def __post_init__(self) -> None:
        # Validate bounds are positive integers (not bools)
        if self.max_fragment_bytes <= 0 or isinstance(self.max_fragment_bytes, bool):
            raise make_error(
                prefix="VAL", component="OUTPUT-RELAY", number=3,
                kind="output-relay-policy",
                message="max_fragment_bytes must be a positive integer",
                details={"value": self.max_fragment_bytes},
            )
        if self.max_turn_bytes <= 0 or isinstance(self.max_turn_bytes, bool):
            raise make_error(
                prefix="VAL", component="OUTPUT-RELAY", number=3,
                kind="output-relay-policy",
                message="max_turn_bytes must be a positive integer",
                details={"value": self.max_turn_bytes},
            )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> OutputPolicy:
        """Build policy from component config mapping.

        Expected shape::

            agents.gateway.output:
              enabled: false
              max-fragment-bytes: 65536
              max-turn-bytes: 524288

        Missing keys use defaults.
        """
        enabled = config.get("enabled", _DEFAULT_ENABLED)
        max_fragment = config.get(
            "max-fragment-bytes",
            config.get("max_fragment_bytes", DEFAULT_MAX_FRAGMENT_BYTES),
        )
        max_turn = config.get(
            "max-turn-bytes",
            config.get("max_turn_bytes", DEFAULT_MAX_TURN_BYTES),
        )
        # Coerce to int (config may carry YAML ints or strings)
        try:
            enabled = bool(enabled)
            max_fragment = int(max_fragment)
            max_turn = int(max_turn)
        except (TypeError, ValueError):
            logger.warning(
                "output relay policy has non-integer bounds; using defaults",
                extra={"config": config},
            )
            return cls(
                enabled=_DEFAULT_ENABLED,
                max_fragment_bytes=DEFAULT_MAX_FRAGMENT_BYTES,
                max_turn_bytes=DEFAULT_MAX_TURN_BYTES,
            )
        return cls(enabled=enabled, max_fragment_bytes=max_fragment, max_turn_bytes=max_turn)

    @classmethod
    def disabled(cls) -> OutputPolicy:
        """Return a policy that blocks all streaming output."""
        return cls(enabled=False, max_fragment_bytes=DEFAULT_MAX_FRAGMENT_BYTES,
                   max_turn_bytes=DEFAULT_MAX_TURN_BYTES)

    @classmethod
    def default_enabled(cls) -> OutputPolicy:
        """Return the default policy with relay enabled."""
        return cls(enabled=True, max_fragment_bytes=DEFAULT_MAX_FRAGMENT_BYTES,
                   max_turn_bytes=DEFAULT_MAX_TURN_BYTES)


# ── Index state tracking ─────────────────────────────────────────────────

@dataclass
class _OutputIndexState:
    """Mutable per-request output index tracked in-memory during relay lifetime."""

    seq_start: int | None = None
    seq_end: int | None = None
    total_bytes: int = 0
    event_count: int = 0
    is_truncated: bool = False

    def update(self, sequence: int, text_bytes: int) -> None:
        if self.seq_start is None:
            self.seq_start = sequence
        self.seq_end = sequence
        self.total_bytes += text_bytes
        self.event_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq-start": self.seq_start,
            "seq-end": self.seq_end,
            "total-bytes": self.total_bytes,
            "event-count": self.event_count,
            "is-truncated": self.is_truncated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _OutputIndexState:
        if not isinstance(data, dict):
            return cls()
        return cls(
            seq_start=data.get("seq-start"),
            seq_end=data.get("seq-end"),
            total_bytes=data.get("total-bytes", 0),
            event_count=data.get("event-count", 0),
            is_truncated=data.get("is-truncated", False),
        )


# ── OutputRelay (per-turn relay instance) ────────────────────────────────

class OutputRelay(OutputSink):
    """Per-turn output relay enforcing bounds and persistence.

    Registers per-request before dispatch, receives AgentOutputEvent instances
    from the provider adapter pipeline, enforces schema validation, sequence
    monotonicity, fragment bounds, and per-turn byte cap. Persists each
    event atomically under the request directory.

    Graceful degradation: relay failure (disk full, lock timeout, etc.) logs
    but never fails the turn. When degraded, the relay continues accepting
    events in-memory only (no persistence).

    Parameters
    ----------
    project_root : Path
        The project root (absolute).
    request_id : str
        The gateway request ID.
    session_id : str
        The session ID for this turn.
    turn_id : str
        The turn ID for this relay instance.
    policy : OutputPolicy
        Relay policy governing bounds and enabled state.
    """

    def __init__(
        self,
        project_root: Path,
        request_id: str,
        session_id: str,
        turn_id: str,
        policy: OutputPolicy,
        surface: ResolvedSessionSurface | None = None,
    ) -> None:
        self._project_root = project_root
        self._request_id = request_id
        self._session_id = session_id
        self._turn_id = turn_id
        self._policy = policy
        # A supplied AS29 snapshot is authoritative.  Keep ``None`` as a
        # compatibility mode for callers that have not yet migrated to the
        # public preparation path; those callers retain the pre-AS31 behavior.
        self._surface = surface
        self._content_authorized = (
            surface is None
            or (
                surface.validation.evidence.validated
                and surface.content.has_channel(ContentChannelId.ASSISTANT_TEXT)
            )
        )

        # Sequence tracking for monotonicity enforcement
        self._last_sequence: int | None = None

        # Turn-level byte accumulator (respects per-turn cap)
        self._turn_bytes: int = 0

        # In-memory index state (persisted to disk on each write)
        self._index_state = _OutputIndexState()

        # Degradation flag — once True, events are accepted but not persisted
        self._degraded: bool = False

        # Track if any event was received
        self._has_events: bool = False

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def is_enabled(self) -> bool:
        """Whether the relay policy allows output streaming."""
        return self._policy.enabled and not self._degraded

    @property
    def is_degraded(self) -> bool:
        """Whether the relay has entered graceful degradation mode."""
        return self._degraded

    @property
    def has_events(self) -> bool:
        """Whether any events have been received by this relay."""
        return self._has_events

    # ── OutputSink protocol implementation ───────────────────────────────

    async def __call__(self, event: AgentOutputEvent) -> None:
        """Receive and process a single AgentOutputEvent.

        Enforces schema validation (via the frozen dataclass), sequence
        monotonicity, fragment bounds, and per-turn byte cap. Persists
        each valid event atomically. On any failure, degrades gracefully
        without propagating the error.

        Parameters
        ----------
        event : AgentOutputEvent
            A validated output event from the provider adapter pipeline.

        Raises
        ------
        Nothing — relay failures are logged and degrade silently.
        """
        try:
            await self._accept_event(event)
        except Exception:  # noqa: BLE001
            self._degraded = True
            logger.debug(
                "output relay degraded; accepting events in-memory only",
                extra={
                    "request-id": self._request_id,
                    "session-id": self._session_id,
                    "turn-id": self._turn_id,
                },
                exc_info=True,
            )

    async def _accept_event(self, event: AgentOutputEvent) -> None:
        """Core event acceptance with validation and persistence."""
        # Policy check: disabled policy blocks all streaming output
        if not self._policy.enabled:
            logger.debug(
                "output relay policy disabled; rejecting event",
                extra={"request-id": self._request_id},
            )
            return

        if not self._content_authorized:
            raise AudiaGenticError(
                code=ERR_OUTPUT_CHANNEL_UNAUTHORIZED,
                kind="output-relay",
                message="resolved session surface does not authorize assistant text output",
                details={
                    "surface-id": self._surface.ref.surface_id if self._surface else None,
                },
            )

        # Validate sequence monotonicity (strictly increasing or None)
        self._validate_sequence(event.sequence)

        # Calculate text bytes for this fragment
        text_bytes = len(event.text.encode("utf-8"))

        # Enforce fragment bound (per-event max)
        if text_bytes > self._policy.max_fragment_bytes:
            raise AudiaGenticError(
                code=ERR_OUTPUT_OVERSIZED_FRAGMENT,
                kind="output-relay",
                message=(
                    f"fragment text exceeds maximum of {self._policy.max_fragment_bytes} bytes "
                    f"({text_bytes} bytes)"
                ),
                details={
                    "max-fragment-bytes": self._policy.max_fragment_bytes,
                    "actual-bytes": text_bytes,
                    "sequence": event.sequence,
                },
            )

        # Enforce per-turn byte cap
        if (self._turn_bytes + text_bytes) > self._policy.max_turn_bytes:
            raise AudiaGenticError(
                code=ERR_OUTPUT_TURN_CAP_EXCEEDED,
                kind="output-relay",
                message=(
                    f"per-turn byte cap exceeded: "
                    f"{self._turn_bytes + text_bytes} / {self._policy.max_turn_bytes}"
                ),
                details={
                    "max-turn-bytes": self._policy.max_turn_bytes,
                    "current-turn-bytes": self._turn_bytes,
                    "fragment-bytes": text_bytes,
                    "sequence": event.sequence,
                },
            )

        # Update in-memory state
        self._turn_bytes += text_bytes
        self._has_events = True
        if event.sequence is not None:
            self._last_sequence = event.sequence
            self._index_state.update(event.sequence, text_bytes)

        # Persist after updating the index state so index.json describes the
        # event just written, rather than lagging by one event.
        if not self._degraded:
            self._persist_event(event, text_bytes)

    def _validate_sequence(self, sequence: int | None) -> None:
        """Validate sequence monotonicity within this turn.

        Rules:
        - None is always valid (no monotonicity to enforce)
        - Non-negative integers must be strictly increasing
        - Once a non-None sequence is seen, subsequent None values are allowed
          but the next integer must still be > last integer
        """
        if sequence is None:
            return

        if not isinstance(sequence, int) or sequence < 0:
            raise AudiaGenticError(
                code=ERR_OUTPUT_SEQUENCE_NOT_MONOTONIC,
                kind="output-relay",
                message="sequence must be a non-negative integer or None",
                details={"value": sequence},
            )

        if self._last_sequence is not None and sequence <= self._last_sequence:
            raise AudiaGenticError(
                code=ERR_OUTPUT_SEQUENCE_NOT_MONOTONIC,
                kind="output-relay",
                message=(
                    f"sequence {sequence} is not strictly greater than "
                    f"previous sequence {self._last_sequence}"
                ),
                details={
                    "current-sequence": sequence,
                    "previous-sequence": self._last_sequence,
                },
            )

    def _persist_event(self, event: AgentOutputEvent, text_bytes: int) -> None:
        """Persist a single event atomically under the request directory.

        Uses the per-request StartupLock to serialize writes. Writes both
        the individual event file and updates the index.json.
        """
        lock_path = self._get_lock_path()
        events_dir = self._get_events_dir()

        try:
            with StartupLock(lock_path, timeout=10.0):
                # Write the individual event file (atomic via temp+replace)
                if event.sequence is not None:
                    event_path = events_dir / f"{event.sequence}.json"
                    self._atomic_write_event(event_path, event)

                # Update the index
                self._update_index()
        except Exception:  # noqa: BLE001
            # Degradation: lock timeout, disk full, etc.
            self._degraded = True
            logger.warning(
                "output relay persistence failed; degrading to in-memory only",
                extra={
                    "request-id": self._request_id,
                    "sequence": event.sequence,
                },
                exc_info=True,
            )

    def _atomic_write_event(self, target_path: Path, event: AgentOutputEvent) -> None:
        """Write an event file atomically using temp+replace pattern."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "session-id": event.session_id,
            "turn-id": event.turn_id,
            "sequence": event.sequence,
            "kind": event.kind.value,
            "text": event.text,
            "observed-at": event.observed_at,
            "is-final": event.is_final,
        }
        atomic_write_json(target_path, payload)

    def _update_index(self) -> None:
        """Write the output index.json atomically."""
        index_path = self._get_output_dir() / "index.json"
        payload = {
            **self._index_state.to_dict(),
            "updated-at": now_iso_z(),
        }
        atomic_write_json(index_path, payload)

    # ── Read operations ──────────────────────────────────────────────────

    def read_output_events(self) -> list[dict[str, Any]]:
        """Read all persisted output events for this request.

        Returns a list of event dicts ordered by file name (sequence number).
        Graceful on missing files — returns empty list if no events exist.
        """
        events_dir = self._get_events_dir()
        if not events_dir.exists():
            return []

        events: list[dict[str, Any]] = []
        for path in sorted(events_dir.iterdir()):
            if path.suffix == ".json":
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        events.append(data)
                except (json.JSONDecodeError, OSError):
                    logger.debug(
                        "failed to read output event file",
                        extra={"path": str(path)},
                        exc_info=True,
                    )
        return events

    def read_output_index(self) -> dict[str, Any]:
        """Read the output index for this request.

        Returns empty dict if no index exists (no events persisted yet).
        """
        index_path = self._get_output_dir() / "index.json"
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            return {}
        except (json.JSONDecodeError, OSError):
            return {}

    def get_turn_summary(self) -> dict[str, Any]:
        """Return a summary of the relay's in-memory turn state."""
        return {
            "has-events": self._has_events,
            "turn-bytes": self._turn_bytes,
            "max-turn-bytes": self._policy.max_turn_bytes,
            "is-degraded": self._degraded,
            "last-sequence": self._last_sequence,
        }

    # ── Path helpers ─────────────────────────────────────────────────────

    def _get_lock_path(self) -> Path:
        """Return the per-request output lock path."""
        from audiagentic.components.agents.agents_paths import gateway_output_lock_path
        return gateway_output_lock_path(self._project_root, self._request_id)

    def _get_output_dir(self) -> Path:
        """Return the output directory for this request."""
        from audiagentic.components.agents.agents_paths import gateway_output_dir
        return gateway_output_dir(self._project_root, self._request_id)

    def _get_events_dir(self) -> Path:
        """Return the output events subdirectory for this request."""
        from audiagentic.components.agents.agents_paths import gateway_output_events_dir
        return gateway_output_events_dir(self._project_root, self._request_id)


# ── Module-level API functions ─────────────────────────────────────────────

def create_relay(
    project_root: Path,
    request_id: str,
    session_id: str,
    turn_id: str,
    policy: OutputPolicy,
    surface: ResolvedSessionSurface | None = None,
) -> OutputRelay:
    """Factory: create a new OutputRelay for a given request/turn.

    This is the canonical entry point — relay instances are registered
    per-request before dispatch and used as the OutputSink during provider
    execution.
    """
    return OutputRelay(
        project_root=project_root,
        request_id=request_id,
        session_id=session_id,
        turn_id=turn_id,
        policy=policy,
        surface=surface,
    )


def read_request_output(project_root: Path, request_id: str) -> dict[str, Any]:
    """Read all persisted output events for a gateway request.

    Returns a mapping with 'events' (list of event dicts), 'index' (index.json
    data), and 'output-dir' (path string). Useful for post-dispatch read of
    streaming output without re-running the turn.
    """
    from audiagentic.components.agents.agents_paths import (
        gateway_output_dir,
        gateway_output_events_dir,
        gateway_output_index_path,
    )

    events: list[dict[str, Any]] = []
    events_dir = gateway_output_events_dir(project_root, request_id)
    if events_dir.exists():
        for path in sorted(events_dir.iterdir()):
            if path.suffix == ".json":
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        events.append(data)
                except (json.JSONDecodeError, OSError):
                    logger.debug(
                        "failed to read output event file",
                        extra={"path": str(path)},
                        exc_info=True,
                    )

    index: dict[str, Any] = {}
    index_path = gateway_output_index_path(project_root, request_id)
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                index = data
        except (json.JSONDecodeError, OSError):
            logger.debug(
                "failed to read output index",
                extra={"path": str(index_path)},
                exc_info=True,
            )

    return {
        "events": events,
        "index": index,
        "output-dir": str(gateway_output_dir(project_root, request_id)),
    }


# ── Store extension: atomic append operations ─────────────────────────────

def append_agent_output_record(
    project_root: Path,
    request_id: str,
    event: AgentOutputEvent,
) -> None:
    """Atomically append an AgentOutputEvent to the output store.

    Uses per-request StartupLock for crash-safe writes. The event is written
    to <request-dir>/output/events/<seq>.json and the index.json is updated.

    This function exists as a standalone entry point for callers that need
    direct store access without going through OutputRelay (e.g. recovery).
    """
    from audiagentic.components.agents.agents_paths import (
        gateway_output_events_dir,
        gateway_output_index_path,
        gateway_output_lock_path,
    )

    lock_path = gateway_output_lock_path(project_root, request_id)
    events_dir = gateway_output_events_dir(project_root, request_id)
    index_path = gateway_output_index_path(project_root, request_id)

    # Build the event payload (same shape as OutputRelay._atomic_write_event)
    payload = {
        "session-id": event.session_id,
        "turn-id": event.turn_id,
        "sequence": event.sequence,
        "kind": event.kind.value,
        "text": event.text,
        "observed-at": event.observed_at,
        "is-final": event.is_final,
    }

    with StartupLock(lock_path, timeout=10.0):
        # Write the individual event file atomically
        if event.sequence is not None:
            event_path = events_dir / f"{event.sequence}.json"
            atomic_write_json(event_path, payload)

        # Update the index
        text_bytes = len(event.text.encode("utf-8"))
        state = _OutputIndexState.from_dict(load_ndjson(index_path)[-1] if index_path.exists() else {})
        # load_ndjson returns a list; we want the last entry as the current index
        # Actually, index.json is a single JSON object, not ndjson
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
            state = _OutputIndexState.from_dict(raw if isinstance(raw, dict) else {})
        except (json.JSONDecodeError, OSError):
            state = _OutputIndexState()

        if event.sequence is not None:
            state.update(event.sequence, text_bytes)

        atomic_write_json(index_path, {
            **state.to_dict(),
            "updated-at": now_iso_z(),
        })


def _get_output_policy_from_config(project_root: Path) -> OutputPolicy:
    """Load output relay policy from component config.

    Reads the 'output' sub-section of the agents component config.
    Falls back to disabled policy if config is missing or invalid.
    """
    try:
        from audiagentic.foundation.io import load_yaml_file

        # Component policy is packaged/global; agent definitions are not
        # project-local authorities.
        config_path = (
            Path(__file__).parent.parent.parent.parent
            / "config"
            / "components"
            / "agents.yaml"
        )
        if config_path.exists():
            config = load_yaml_file(config_path)
            gateway_config = config.get("gateway", {})
            output_config = gateway_config.get("output", {})
            return OutputPolicy.from_config(output_config)
    except Exception:  # noqa: BLE001
        logger.debug(
            "failed to load output relay policy from component config; using disabled default",
            exc_info=True,
        )

    return OutputPolicy.disabled()
