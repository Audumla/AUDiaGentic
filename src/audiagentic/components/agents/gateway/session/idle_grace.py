"""Admission policy: chat identity is independent of live-handle retention."""
from math import isfinite
from typing import Any, Mapping

from audiagentic.foundation.contracts.errors import AudiaGenticError


def gpt_idle_grace(params: Mapping[str, Any]) -> float:
    """Use profile idle policy; false keep-alive always has a finite grace."""
    value = params.get("session-idle-timeout-seconds", params.get("session_idle_timeout_seconds", 1800))
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise AudiaGenticError("VAL-AGW-151", "agents", "session idle timeout must be a finite non-negative number", {})
    # Zero disables normal keep-alive expiry, not an explicit release request.
    return float(value) if value else 1800.0
