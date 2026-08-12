"""Machine-owned execution watchdog policy (SH22)."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import read_text_with_retry


@dataclass(frozen=True)
class WatchdogPolicy:
    activity_lease_seconds: float
    absolute_safety_ceiling_seconds: float
    diagnostic_grace_seconds: float
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
            "available": self.available,
        }


def policy_path() -> Path:
    override = os.environ.get("AUDIAGENTIC_GATEWAY_WATCHDOG_POLICY")
    return Path(override).expanduser() if override else Path.home() / ".audiagentic" / "gateway-watchdog.json"


def load_watchdog_policy() -> WatchdogPolicy:
    fallback = WatchdogPolicy(300.0, 0.0, 30.0, "unavailable", "unavailable", False)
    path = policy_path()
    if not path.is_file():
        return fallback
    try:
        raw = json.loads(read_text_with_retry(path))
        if not isinstance(raw, dict):
            raise ValueError
        lease = float(raw.get("activity-lease-seconds", 300.0))
        ceiling = float(raw.get("absolute-safety-ceiling-seconds", 0.0))
        grace = float(raw.get("diagnostic-grace-seconds", 30.0))
        if not math.isfinite(lease) or lease <= 0 or not math.isfinite(ceiling) or ceiling < 0 or not math.isfinite(grace) or grace <= 0:
            raise ValueError
        canonical = json.dumps(
            {
                "activity-lease-seconds": lease,
                "absolute-safety-ceiling-seconds": ceiling,
                "diagnostic-grace-seconds": grace,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return WatchdogPolicy(lease, ceiling, grace, str(raw.get("policy-id", "machine-default")), digest, True)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return WatchdogPolicy(300.0, 0.0, 30.0, "invalid", "invalid", False)


__all__ = ["WatchdogPolicy", "load_watchdog_policy", "policy_path"]
