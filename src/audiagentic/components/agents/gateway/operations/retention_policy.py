"""Machine-owned retention policy for gateway observability and destructive operations."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REQUEST_HISTORY_LIMIT = 100
DEFAULT_TIMELINE_MAX_BYTES = 1 * 1024 * 1024
DEFAULT_OBSERVATION_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_RECOVERY_MAX_BYTES = 1 * 1024 * 1024
DEFAULT_CONSOLE_TRACE_MAX_BYTES = 4 * 1024 * 1024
DEFAULT_JOURNAL_RETENTION_DAYS = 5
_MAX_CONFIGURED_BYTES = 256 * 1024 * 1024
_MAX_REQUEST_HISTORY_LIMIT = 10_000
_POLICY_ENV = "AUDIAGENTIC_GATEWAY_RETENTION_POLICY"


@dataclass(frozen=True)
class RetentionPolicy:
    enabled: bool
    minimum_archive_age_seconds: float
    max_batch_size: int
    request_history_limit: int
    timeline_max_bytes: int
    observation_max_bytes: int
    recovery_max_bytes: int
    console_trace_max_bytes: int
    policy_id: str
    digest: str
    available: bool
    journal_retention_days: int = DEFAULT_JOURNAL_RETENTION_DAYS

    @property
    def snapshot(self) -> dict[str, Any]:
        return {
            "policy-id": self.policy_id,
            "policy-digest": self.digest,
            "purge-enabled": self.enabled,
            "minimum-archive-age-seconds": self.minimum_archive_age_seconds,
            "max-batch-size": self.max_batch_size,
            "request-history-limit": self.request_history_limit,
            "timeline-max-bytes": self.timeline_max_bytes,
            "observation-max-bytes": self.observation_max_bytes,
            "recovery-max-bytes": self.recovery_max_bytes,
            "console-trace-max-bytes": self.console_trace_max_bytes,
            "journal-retention-days": self.journal_retention_days,
            "available": self.available,
        }


def policy_path() -> Path:
    """The legacy JSON policy file (read when ``gateway.retention`` is not in settings)."""
    override = os.environ.get(_POLICY_ENV)
    return Path(override).expanduser() if override else Path.home() / ".audiagentic" / "gateway-retention.json"


def _positive_int(raw: Any, default: int, maximum: int) -> int:
    value = default if raw is None else int(raw)
    if value <= 0 or value > maximum:
        raise ValueError
    return value


def _policy_values(raw: dict[str, Any]) -> tuple[bool, float, int, int, int, int, int, int]:
    enabled = raw.get("purge-enabled") is True
    minimum = float(raw.get("minimum-archive-age-seconds", 0))
    batch = _positive_int(raw.get("max-batch-size", 100), 100, _MAX_REQUEST_HISTORY_LIMIT)
    history_limit = _positive_int(
        raw.get("request-history-limit", DEFAULT_REQUEST_HISTORY_LIMIT),
        DEFAULT_REQUEST_HISTORY_LIMIT,
        _MAX_REQUEST_HISTORY_LIMIT,
    )
    timeline_max = _positive_int(
        raw.get("timeline-max-bytes", DEFAULT_TIMELINE_MAX_BYTES),
        DEFAULT_TIMELINE_MAX_BYTES,
        _MAX_CONFIGURED_BYTES,
    )
    observation_max = _positive_int(
        raw.get("observation-max-bytes", DEFAULT_OBSERVATION_MAX_BYTES),
        DEFAULT_OBSERVATION_MAX_BYTES,
        _MAX_CONFIGURED_BYTES,
    )
    recovery_max = _positive_int(
        raw.get("recovery-max-bytes", DEFAULT_RECOVERY_MAX_BYTES),
        DEFAULT_RECOVERY_MAX_BYTES,
        _MAX_CONFIGURED_BYTES,
    )
    console_max = _positive_int(
        raw.get("console-trace-max-bytes", DEFAULT_CONSOLE_TRACE_MAX_BYTES),
        DEFAULT_CONSOLE_TRACE_MAX_BYTES,
        _MAX_CONFIGURED_BYTES,
    )
    if not math.isfinite(minimum) or minimum < 0 or (enabled and minimum <= 0):
        raise ValueError
    return enabled, minimum, batch, history_limit, timeline_max, observation_max, recovery_max, console_max


def load_retention_policy() -> RetentionPolicy:
    """``gateway.retention`` from settings, else the legacy JSON file (see ``policy_mapping``)."""
    from audiagentic.components.agents.gateway.settings import policy_mapping

    try:
        raw = policy_mapping("retention", _POLICY_ENV, policy_path())
    except (OSError, ValueError, TypeError):
        raw = []  # not a mapping: reported as an invalid policy below
    if raw is None:
        return RetentionPolicy(
            False,
            0.0,
            100,
            DEFAULT_REQUEST_HISTORY_LIMIT,
            DEFAULT_TIMELINE_MAX_BYTES,
            DEFAULT_OBSERVATION_MAX_BYTES,
            DEFAULT_RECOVERY_MAX_BYTES,
            DEFAULT_CONSOLE_TRACE_MAX_BYTES,
            "unavailable",
            "unavailable",
            False,
        )
    try:
        if not isinstance(raw, dict):
            raise ValueError
        enabled, minimum, batch, history_limit, timeline_max, observation_max, recovery_max, console_max = _policy_values(raw)
        retention_days = raw.get("journal-retention-days", DEFAULT_JOURNAL_RETENTION_DAYS)
        if isinstance(retention_days, bool) or not isinstance(retention_days, int) or not 1 <= retention_days <= 3650:
            raise ValueError
        canonical = json.dumps(
            {
                "purge-enabled": enabled,
                "minimum-archive-age-seconds": minimum,
                "max-batch-size": batch,
                "request-history-limit": history_limit,
                "timeline-max-bytes": timeline_max,
                "observation-max-bytes": observation_max,
                "recovery-max-bytes": recovery_max,
                "console-trace-max-bytes": console_max,
                "journal-retention-days": retention_days,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return RetentionPolicy(
            enabled,
            minimum,
            batch,
            history_limit,
            timeline_max,
            observation_max,
            recovery_max,
            console_max,
            str(raw.get("policy-id", "machine-default")),
            digest,
            True,
            retention_days,
        )
    except (OSError, ValueError, TypeError):
        return RetentionPolicy(
            False,
            0.0,
            100,
            DEFAULT_REQUEST_HISTORY_LIMIT,
            DEFAULT_TIMELINE_MAX_BYTES,
            DEFAULT_OBSERVATION_MAX_BYTES,
            DEFAULT_RECOVERY_MAX_BYTES,
            DEFAULT_CONSOLE_TRACE_MAX_BYTES,
            "invalid",
            "invalid",
            False,
        )


def policy_matches(snapshot: dict[str, Any]) -> bool:
    current = load_retention_policy()
    return current.available and current.digest == snapshot.get("policy-digest") and current.policy_id == snapshot.get("policy-id")


__all__ = [
    "DEFAULT_JOURNAL_RETENTION_DAYS",
    "DEFAULT_CONSOLE_TRACE_MAX_BYTES",
    "DEFAULT_OBSERVATION_MAX_BYTES",
    "DEFAULT_RECOVERY_MAX_BYTES",
    "DEFAULT_REQUEST_HISTORY_LIMIT",
    "DEFAULT_TIMELINE_MAX_BYTES",
    "RetentionPolicy",
    "load_retention_policy",
    "policy_matches",
    "policy_path",
]
