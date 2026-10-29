"""Machine-owned execution watchdog policy (SH22)."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WatchdogPolicy:
    activity_lease_seconds: float
    absolute_safety_ceiling_seconds: float
    diagnostic_grace_seconds: float
    initial_activity_grace_seconds: float
    policy_id: str
    digest: str
    available: bool

    @property
    def snapshot(self) -> dict[str, Any]:
        return {
            "policy-id": self.policy_id,
            "policy-digest": self.digest,
            "activity-lease-seconds": self.activity_lease_seconds,
            "absolute-safety-ceiling-seconds": self.absolute_safety_ceiling_seconds,
            "diagnostic-grace-seconds": self.diagnostic_grace_seconds,
            "initial-activity-grace-seconds": self.initial_activity_grace_seconds,
            "available": self.available,
        }


def load_watchdog_policy() -> WatchdogPolicy:
    """The ``gateway.watchdog`` settings as a policy; unavailable when unset, invalid when it fails validation."""
    from audiagentic.components.agents.gateway.settings import gateway_policy

    fallback = WatchdogPolicy(300.0, 0.0, 30.0, 30.0, "unavailable", "unavailable", False)
    try:
        raw = gateway_policy("watchdog")
        if raw is None:
            return fallback
        if not isinstance(raw, dict):
            raise ValueError
        lease = float(raw.get("activity-lease-seconds", 300.0))
        ceiling = float(raw.get("absolute-safety-ceiling-seconds", 0.0))
        grace = float(raw.get("diagnostic-grace-seconds", 30.0))
        initial_grace = float(raw.get("initial-activity-grace-seconds", 30.0))
        if not math.isfinite(lease) or lease <= 0 or not math.isfinite(ceiling) or ceiling < 0 or not math.isfinite(grace) or grace <= 0 or not math.isfinite(initial_grace) or initial_grace <= 0:
            raise ValueError
        canonical = json.dumps(
            {
                "activity-lease-seconds": lease,
                "absolute-safety-ceiling-seconds": ceiling,
                "diagnostic-grace-seconds": grace,
                "initial-activity-grace-seconds": initial_grace,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return WatchdogPolicy(lease, ceiling, grace, initial_grace, str(raw.get("policy-id", "machine-default")), digest, True)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return WatchdogPolicy(300.0, 0.0, 30.0, 30.0, "invalid", "invalid", False)


__all__ = ["WatchdogPolicy", "load_watchdog_policy"]
