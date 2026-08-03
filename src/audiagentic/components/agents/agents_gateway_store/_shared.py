"""Shared constants and workflow for the gateway store (SH18).

All module-level constants are defined here to avoid duplication across
_admission, _records, and _transitions sub-modules.
"""
from __future__ import annotations

import logging
from pathlib import Path

from audiagentic.components.agents.agents_paths import (
    gateway_admission_lock_path,
    gateway_request_path,
    gateway_timeline_path,
)
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.observability import record_timeline_event
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.workflow import (
    is_known_state,
    load_workflow,
    states_in_set,
    transition_allowed,
)

_SCHEMA_STEM = "agent-execution-record"
_CONTRACT_VERSION = "v2"
_WORKFLOW = load_workflow(Path(__file__).parent.parent / "workflows.yaml", "gateway-request")
TERMINAL_STATES: set[str] = set(states_in_set(_WORKFLOW, "terminal"))

_REDACTED_ERROR_KEYS = {"code", "message", "kind"}

# Result fields a workflow transition may update; everything else on the
# record is admission identity or fenced ownership (SH review C12).
_MUTABLE_RESULT_FIELDS = {
    "provider-id", "model-id", "output", "completion", "usage", "error",
    "worker-evidence",
    "started-at", "finished-at", "session-id", "recovery",
    "replay-required", "replay-reason", "replayed-by-request-id",
}

_COMPONENT_ID = "agents"
_RESOURCE_KIND = "agent-execution-gateway-request"
ACTIVE_WORK_DIR = "active-work"

logger = logging.getLogger(__name__)


def record_gateway_timeline(
    project_root: Path,  # noqa: F821
    request_id: str,
    event: str,
    *,
    state: str | None = None,
    attributes: dict | None = None,
) -> dict:
    return record_timeline_event(
        gateway_timeline_path(project_root, request_id),
        component=_COMPONENT_ID,
        resource_kind=_RESOURCE_KIND,
        resource_id=request_id,
        event=event,
        state=state,
        attributes=attributes,
        correlation_id=(attributes or {}).get("correlation_id") or (attributes or {}).get("correlation-id"),
    )


def _request_lock(project_root: Path, request_id: str) -> StartupLock:
    """Return the foundation cross-process lock for one request record."""
    return StartupLock(gateway_request_path(project_root, request_id).with_name("mutation.lock"))


def _admission_lock(project_root: Path) -> StartupLock:
    """Serialize project-local idempotency reservation and record creation."""
    return StartupLock(gateway_admission_lock_path(project_root))


def validate_with_schema_fn(payload: dict) -> list[str]:
    """Thin wrapper so sub-modules don't import schema_registry directly."""
    return validate_with_schema(_SCHEMA_STEM, payload)


def is_known_state_fn(state: str) -> bool:
    """Thin wrapper so _transitions doesn't import workflow directly."""
    return is_known_state(_WORKFLOW, state)


def transition_allowed_fn(current: str, new: str) -> bool:
    """Thin wrapper so _transitions doesn't import workflow directly."""
    return transition_allowed(_WORKFLOW, current, new)


def extract_worker_evidence(error: BaseException | dict | None) -> dict | None:
    """Extract bounded redacted worker diagnostic evidence from an error.

    For INT-AGW-076 errors that carry a ``worker-diagnostic`` in their
    details (the bounded stderr traceback from the isolated worker host),
    return a private evidence dict for operator-only persistence.  Only
    the error type and the redacted diagnostic string are captured — no
    raw prompt, secret, or unbounded data survives this boundary.

    Returns None when there is no INT-AGW-076 worker diagnostic to extract.
    """
    if error is None:
        return None
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    if not isinstance(error, AudiaGenticError):
        return None
    if error.code != "INT-AGW-076":
        return None
    details = getattr(error, "details", None)
    if not isinstance(details, dict):
        return None
    diag = details.get("worker-diagnostic")
    if not isinstance(diag, str) or not diag:
        return None
    # Bounded: enforce 2 KB limit on persisted diagnostic (same as the
    # parent worker pipe limit in agents_gateway_worker.py).
    _MAX_EVIDENCE = 2 * 1024
    if len(diag) > _MAX_EVIDENCE:
        diag = diag[:_MAX_EVIDENCE] + "\n<truncated>"
    return {
        "error-type": type(error).__name__,
        "worker-diagnostic": diag,
    }
