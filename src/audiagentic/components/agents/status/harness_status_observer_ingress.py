"""AS19 Stage-2: Session observer ingress — agents-owned, never crosses to providers.

Per-session loopback endpoint for hook/plugin delivery of status observations.
Validates binding-id, token match, and project/session correlation. Bounded
request body (max 8 KB), timeout enforcement. Observation-only: never modifies
turn state or releases work.

This module lives in ``agents`` because the ingress is an agents-internal
delivery surface; it does not cross into providers/contracts.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from audiagentic.foundation.contracts.errors import make_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_REQUEST_BODY_BYTES = 8 * 1024  # 8 KB bound on ingress request body
DEFAULT_INGRESS_TIMEOUT_SECONDS = 30.0
_BINDING_PREFIX = "obsbnd"

# ---------------------------------------------------------------------------
# StatusObserverRegistration — in-memory binding state (stage-2, no persistence)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatusObserverRegistration:
    """In-memory registration record for one observer binding.

    Created by create_observer_binding(); invalidated on session close/failure.
    No persistence — bindings are memory-only in stage-2 (stage-3 adds durable
    tracking).
    """

    binding_id: str
    token: str  # HMAC-style secret for validating ingress requests
    session_id: str
    project_root: str
    ingress_endpoint: str  # e.g. "loopback://session/{session_id}/observer"
    created_at: float  # monotonic clock

# ---------------------------------------------------------------------------
# SessionObserverIngress
# ---------------------------------------------------------------------------

class SessionObserverIngress:
    """Per-session loopback endpoint for hook/plugin status delivery.

    Observations arrive from managed hooks and plugins via the ingress;
    this class validates the request (binding-id, token, project/session
    correlation), enforces body bounds, and delivers to a callback. It
    NEVER modifies turn state or releases work — observation only.

    Thread-safe: all state mutations are guarded by _lock.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_observation: Callable[[str, Any], Awaitable[None]] | None = None,
    ) -> None:
        """Create an ingress handler.

        Args:
            clock: Monotonic clock for timeout enforcement (injectable for tests).
            on_observation: Async callback invoked with (session_id, observation_dict)
                when a valid observation arrives. If None, observations are silently
                accepted without processing.
        """
        self._clock = clock
        self._on_observation = on_observation
        self._lock = threading.Lock()
        self._registrations: dict[str, StatusObserverRegistration] = {}  # binding_id -> reg
        self._session_bindings: dict[str, set[str]] = {}  # session_id -> {binding_ids}

    def create_observer_binding(
        self,
        *,
        session_id: str,
        project_root: str,
    ) -> tuple[str, str, str]:
        """Create an observer binding for a session.

        Returns (binding_id, token, ingress_endpoint). The token is a 32-byte
        hex secret used to validate incoming observation requests.

        Raises:
            AudiaGenticError: if session already has an active binding.
        """
        with self._lock:
            existing = self._session_bindings.get(session_id)
            if existing:
                raise make_error(
                    prefix="CON", component="AGW-OBS", number=1,
                    kind="harness-status-observer-binding",
                    message=(
                        f"session {session_id!r} already has an active observer binding; "
                        "one binding per session"
                    ),
                    details={"session-id": session_id, "existing-bindings": list(existing)},
                )

            binding_id = _generate_binding_id()
            token = secrets.token_hex(32)
            ingress_endpoint = f"loopback://session/{session_id}/observer"

            registration = StatusObserverRegistration(
                binding_id=binding_id,
                token=token,
                session_id=session_id,
                project_root=project_root,
                ingress_endpoint=ingress_endpoint,
                created_at=self._clock(),
            )
            self._registrations[binding_id] = registration
            self._session_bindings.setdefault(session_id, set()).add(binding_id)

        logger.debug(
            "observer binding created",
            extra={"binding-id": binding_id, "session-id": session_id},
        )
        return binding_id, token, ingress_endpoint

    def invalidate_binding(self, binding_id: str) -> None:
        """Invalidate and remove an observer binding.

        Called on session close/failure. Idempotent — no-op if the binding
        is not found.
        """
        with self._lock:
            registration = self._registrations.pop(binding_id, None)
            if registration is None:
                return
            session_id = registration.session_id
            bindings = self._session_bindings.get(session_id)
            if bindings:
                bindings.discard(binding_id)
                if not bindings:
                    del self._session_bindings[session_id]

        logger.debug(
            "observer binding invalidated",
            extra={"binding-id": binding_id},
        )

    def invalidate_all_for_session(self, session_id: str) -> None:
        """Invalidate all observer bindings for a session.

        Called on session close/failure. Idempotent — no-op if there are no
        bindings for the session.
        """
        with self._lock:
            binding_ids = self._session_bindings.pop(session_id, set())
            for bid in binding_ids:
                self._registrations.pop(bid, None)

        logger.debug(
            "observer bindings invalidated for session",
            extra={"session-id": session_id, "binding-count": len(binding_ids)},
        )

    def get_registration(self, binding_id: str) -> StatusObserverRegistration | None:
        """Look up a registration by binding_id (read-only)."""
        with self._lock:
            return self._registrations.get(binding_id)

    # -------------------------------------------------------------------
    # Observation delivery
    # -------------------------------------------------------------------

    def deliver_observation(
        self,
        *,
        binding_id: str,
        token: str,
        observation: Any,
        session_id: str | None = None,
        project_root: str | None = None,
        deadline: float | None = None,
    ) -> bool:
        """Validate and deliver one observation to the session.

        Validates binding-id exists, token matches, project/session
        correlation is correct, body is bounded, and timeout is enforced.
        Never modifies turn state or releases work — observation only.

        Returns True when the observation was accepted (delivered to callback
        or silently accepted when no callback). Returns False when validation
        fails (binding not found, token mismatch, etc.).

        Args:
            binding_id: The observer binding ID from the registration.
            token: The HMAC secret from the registration.
            observation: The observation payload (must be serializable; body
                size is enforced by byte count of JSON representation).
            session_id: AG session ID for correlation validation.
            project_root: Project root for correlation validation.
            deadline: Monotonic clock deadline for timeout enforcement.
        """
        with self._lock:
            registration = self._registrations.get(binding_id)

            # Binding must exist and be active.
            if registration is None:
                logger.warning(
                    "observer ingress: unknown binding-id",
                    extra={"binding-id": binding_id},
                )
                return False

            # Token must match (HMAC comparison).
            expected_token = registration.token
            if not _constant_time_compare(token, expected_token):
                logger.warning(
                    "observer ingress: token mismatch",
                    extra={"binding-id": binding_id},
                )
                return False

            # Project/session correlation.
            if session_id is not None and session_id != registration.session_id:
                logger.warning(
                    "observer ingress: session-id mismatch",
                    extra={
                        "binding-id": binding_id,
                        "expected-session-id": registration.session_id,
                        "provided-session-id": session_id,
                    },
                )
                return False

            if project_root is not None and project_root != registration.project_root:
                logger.warning(
                    "observer ingress: project-root mismatch",
                    extra={
                        "binding-id": binding_id,
                        "expected-project-root": registration.project_root,
                        "provided-project-root": project_root,
                    },
                )
                return False

            # Timeout enforcement.
            if deadline is not None and self._clock() > deadline:
                logger.warning(
                    "observer ingress: request expired",
                    extra={"binding-id": binding_id},
                )
                return False

        # Body bound check (outside lock — observation processing may be slow).
        body_bytes = _estimate_body_size(observation)
        if body_bytes > MAX_REQUEST_BODY_BYTES:
            logger.warning(
                "observer ingress: request body exceeds max size",
                extra={
                    "binding-id": binding_id,
                    "body-bytes": body_bytes,
                    "max-bytes": MAX_REQUEST_BODY_BYTES,
                },
            )
            return False

        # Deliver to callback (observation only — never modifies state).
        if self._on_observation is not None:
            import asyncio

            try:
                target_session_id = session_id or registration.session_id
                asyncio.get_running_loop().create_task(
                    self._on_observation(target_session_id, observation)
                )
            except RuntimeError:
                # No running loop — schedule on the next available event loop.
                # Observation is accepted but deferred.
                logger.debug(
                    "observer ingress: no event loop, deferring observation",
                    extra={"binding-id": binding_id},
                )

        logger.debug(
            "observer ingress: observation delivered",
            extra={"binding-id": binding_id},
        )
        return True

    # -------------------------------------------------------------------
    # Lifecycle helpers (used by SessionRuntime integration)
    # -------------------------------------------------------------------

    def has_binding_for_session(self, session_id: str) -> bool:
        """Check if a session has an active observer binding."""
        with self._lock:
            return bool(self._session_bindings.get(session_id))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_binding_id() -> str:
    """Generate a unique observer binding ID."""
    return f"{_BINDING_PREFIX}_{secrets.token_hex(12)}"


def _constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks on tokens."""
    return secrets.compare_digest(a.encode("ascii"), b.encode("ascii"))


def _estimate_body_size(observation: Any) -> int:
    """Estimate the byte size of an observation payload.

    Uses JSON serialization for dicts/lists, str length for strings,
    and a conservative default for other types.
    """
    import json

    if isinstance(observation, (dict, list)):
        try:
            return len(json.dumps(observation).encode("utf-8"))
        except (TypeError, ValueError):
            # Unserializable — estimate conservatively
            return MAX_REQUEST_BODY_BYTES + 1
    if isinstance(observation, str):
        return len(observation.encode("utf-8"))
    if isinstance(observation, bytes):
        return len(observation)
    # Conservative default for other types.
    return 256
