"""AS19 Stage-2 Slice B: agents-side evidence sink for StatusEvidence.

Receives canonical StatusEvidence from the observer lease and performs:
  - exact binding correlation validation (rejects mismatched session/request)
  - monotonic sequence deduplication (rejects duplicates and lower sequences)
  - scalar allowlist enforcement (no raw/native payloads persist or publish)
  - redacted timeline append via existing session timeline helper
  - exactly one agents.turn.status.observed event publish

The sink is best-effort: it returns AcceptedEvidence / RejectedEvidence so the
caller can log but never block or raise. It never transitions requests, mutates
output, cancels turns, or projects lifecycle state — those belong to AS21.

No provider-native types (e.g. AcpResult) are imported in this module
(AS19 validation rule).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from audiagentic.components.agents import agents_gateway_sessions_store as session_store
from audiagentic.components.agents.agents_event_topics import (
    TURN_STATUS_OBSERVED_TOPIC,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scalar allowlist: only these fields are persisted/published from StatusEvidence.
# No raw payload, no provider-native event names, no tool details leak through.
# ---------------------------------------------------------------------------

_SCALAR_ALLOWLIST_KEYS = frozenset({
    "status",
    "session_id",
    "request_id",
    "correlation_id",
    "observed_at",
    "sequence",
    "source_kind",
    "semantic_strength",
    "verification_tier",
})

# ---------------------------------------------------------------------------
# Acceptance/rejection result types (immutable, best-effort contract)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AcceptedEvidence:
    """StatusEvidence was validated and consumed by the sink."""

    status_evidence: Any  # StatusEvidence — re-exported for subscriber use
    timeline_recorded: bool = True
    event_published: bool = True


@dataclass(frozen=True)
class RejectedEvidence:
    """StatusEvidence was rejected; carries a rejection reason for diagnostics."""

    reason: str  # e.g. "binding-mismatch", "duplicate-sequence", "lower-sequence"
    status_evidence: Any | None = None


# ---------------------------------------------------------------------------
# Evidence sink — stateful per-turn dedup, owned by SessionRuntime
# ---------------------------------------------------------------------------

class StatusEvidenceSink:
    """Sole agents-side sink for canonical StatusEvidence.

    Validates exact binding correlation, enforces monotonic sequence ordering
    within a turn, persists only bounded scalars to the session timeline, and
    publishes exactly one ``agents.turn.status.observed`` event per accepted
    evidence item.

    Usage (best-effort):
        sink = StatusEvidenceSink(session_id="ses_X", request_id="req_1")
        result = sink.accept(evidence)
        # result is AcceptedEvidence or RejectedEvidence — never raises

    Invariants:
        - No Acp* type is imported or received.
        - No raw/native payloads are persisted, published, or returned.
        - No lifecycle transitions, no output mutation, no cancellation.
    """

    def __init__(
        self,
        *,
        session_id: str,
        request_id: str | None,
        correlation_id: str | None = None,
        project_root: Any | None = None,  # Path or None (for test isolation)
    ) -> None:
        self._session_id = session_id
        self._request_id = request_id
        self._correlation_id = correlation_id
        self._project_root = project_root
        # Monotonic sequence tracker: highest accepted sequence for this turn.
        # None means no evidence has been accepted yet (sequence is optional).
        self._highest_sequence: int | None = None

    def accept(self, evidence: Any) -> AcceptedEvidence | RejectedEvidence:
        """Accept one StatusEvidence through the sink.

        Validates exact binding correlation, monotonic sequence ordering, and
        scalar allowlist. On success, records a redacted timeline event and
        publishes exactly one ``agents.turn.status.observed`` event.

        Always returns — never raises (best-effort contract).

        Args:
            evidence: A StatusEvidence instance from the observer lease.

        Returns:
            AcceptedEvidence on success, RejectedEvidence with a reason on failure.
        """
        # 1. Reject None / missing evidence.
        if evidence is None:
            return RejectedEvidence(reason="missing-evidence")

        try:
            # 2. Validate exact binding correlation: session_id must match.
            ev_session = getattr(evidence, "session_id", None)
            if ev_session != self._session_id:
                logger.debug(
                    "evidence sink rejected: session mismatch",
                    extra={
                        "expected-session": self._session_id,
                        "evidence-session": ev_session,
                    },
                )
                return RejectedEvidence(reason="binding-mismatch")

            # 3. Validate exact binding correlation: request_id must match
            #    (or both be None). A request_id mismatch means the evidence
            #    belongs to a different turn — reject conservatively.
            ev_request = getattr(evidence, "request_id", None)
            if self._request_id is not None and ev_request != self._request_id:
                logger.debug(
                    "evidence sink rejected: request mismatch",
                    extra={
                        "expected-request": self._request_id,
                        "evidence-request": ev_request,
                    },
                )
                return RejectedEvidence(reason="request-mismatch")

            # 4. Monotonic sequence validation: reject lower sequences and
            #    exact duplicates. Sequences must be strictly increasing within
            #    a turn; None sequences are accepted (they carry no ordering).
            ev_sequence = getattr(evidence, "sequence", None)
            if ev_sequence is not None:
                if not isinstance(ev_sequence, int) or ev_sequence < 0:
                    return RejectedEvidence(reason="invalid-sequence")
                # Strict monotonic: reject if sequence <= highest seen.
                if (
                    self._highest_sequence is not None
                    and ev_sequence <= self._highest_sequence
                ):
                    if ev_sequence == self._highest_sequence:
                        return RejectedEvidence(reason="duplicate-sequence")
                    else:
                        return RejectedEvidence(reason="lower-sequence")
                # Update the highest sequence for this turn.
                self._highest_sequence = ev_sequence

            # 5. Scalar allowlist enforcement: only allowed scalar fields pass
            #    through to timeline and publish. Build a redacted evidence dict.
            redacted = _extract_scalar_allowlist(evidence, _SCALAR_ALLOWLIST_KEYS)

            # 6. Redacted timeline append — persist only bounded scalars.
            timeline_recorded = False
            if self._project_root is not None:
                timeline_recorded = _append_redacted_timeline(
                    project_root=self._project_root,
                    session_id=self._session_id,
                    redacted_evidence=redacted,
                )

            # 7. Publish exactly one agents.turn.status.observed event.
            event_published = _publish_status_observed_event(
                session_id=self._session_id,
                request_id=self._request_id,
                correlation_id=self._correlation_id,
                redacted_evidence=redacted,
            )

            return AcceptedEvidence(
                status_evidence=evidence,
                timeline_recorded=timeline_recorded,
                event_published=event_published,
            )

        except Exception:  # noqa: BLE001 — sink must never raise
            logger.warning(
                "evidence sink exception isolated",
                extra={"session-id": self._session_id},
                exc_info=True,
            )
            return RejectedEvidence(reason="sink-exception")

    @property
    def highest_sequence(self) -> int | None:
        """Return the highest accepted sequence for this turn."""
        return self._highest_sequence


# ---------------------------------------------------------------------------
# Internal helpers — scalar extraction, timeline, event publish
# ---------------------------------------------------------------------------

def _extract_scalar_allowlist(evidence: Any, allowed_keys: frozenset[str]) -> dict[str, Any]:
    """Extract only allowed scalar fields from StatusEvidence.

    Rejects non-scalar values (dicts, lists, callables) to prevent any raw
    payload or provider-native data from leaking through the sink.
    """
    redacted: dict[str, Any] = {}
    for key in allowed_keys:
        raw_value = getattr(evidence, key, None)
        # Enforce scalar-only discipline: only str, int, float, bool, None pass.
        if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
            redacted[key] = raw_value
        elif hasattr(raw_value, "value"):
            # StrEnum values: extract the string value
            if isinstance(raw_value.value, str):
                redacted[key] = raw_value.value
    return redacted


def _append_redacted_timeline(
    project_root: Any,
    session_id: str,
    redacted_evidence: dict[str, Any],
) -> bool:
    """Append a redacted status.observed event to the session timeline.

    Only bounded scalar fields are written — no raw payload, no provider-native
    event names. Never raises (best-effort).
    """
    try:
        attrs: dict[str, Any] = {}
        for key in (
            "status",
            "request_id",
            "correlation_id",
            "observed_at",
            "sequence",
            "source_kind",
            "semantic_strength",
            "verification_tier",
        ):
            value = redacted_evidence.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                attrs[key] = value

        session_store.record_session_timeline(
            project_root,
            session_id,
            "session.status.observed",
            state="active",
            attributes=attrs,
        )
        return True
    except Exception:  # noqa: BLE001 — timeline failure is best-effort
        logger.debug(
            "failed to append redacted status.observed timeline",
            extra={"session-id": session_id},
            exc_info=True,
        )
        return False


def _publish_status_observed_event(
    session_id: str,
    request_id: str | None,
    correlation_id: str | None,
    redacted_evidence: dict[str, Any],
) -> bool:
    """Publish exactly one agents.turn.status.observed event.

    The payload carries only bounded scalar fields extracted from the evidence.
    Never raises (best-effort).
    """
    try:
        from audiagentic.foundation.event import get_bus

        # Build redacted event payload — scalar allowlist only.
        payload: dict[str, Any] = {
            "session-id": session_id,
        }
        if request_id is not None:
            payload["request-id"] = request_id

        for key in (
            "status",
            "correlation_id",
            "observed_at",
            "sequence",
            "source_kind",
            "semantic_strength",
            "verification_tier",
        ):
            value = redacted_evidence.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value

        metadata = {}
        if correlation_id:
            metadata["correlation_id"] = correlation_id

        get_bus().publish(TURN_STATUS_OBSERVED_TOPIC, payload, metadata=metadata)
        return True
    except Exception:  # noqa: BLE001 — event publish failure is best-effort
        logger.debug(
            "failed to publish agents.turn.status.observed",
            extra={"session-id": session_id},
            exc_info=True,
        )
        return False
