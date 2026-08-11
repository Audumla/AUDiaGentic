"""Machine-owned retention policy for gateway destructive operations (SH26)."""

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
class RetentionPolicy:
    enabled: bool
    minimum_archive_age_seconds: float
    max_batch_size: int
    policy_id: str
    digest: str
    available: bool

    @property
    def snapshot(self) -> dict[str, Any]:
        return {
            "policy-id": self.policy_id,
            "policy-digest": self.digest,
            "purge-enabled": self.enabled,
            "minimum-archive-age-seconds": self.minimum_archive_age_seconds,
            "max-batch-size": self.max_batch_size,
            "available": self.available,
        }


def policy_path() -> Path:
    override = os.environ.get("AUDIAGENTIC_GATEWAY_RETENTION_POLICY")
    return Path(override).expanduser() if override else Path.home() / ".audiagentic" / "gateway-retention.json"


def load_retention_policy() -> RetentionPolicy:
    path = policy_path()
    if not path.is_file():
        return RetentionPolicy(False, 0.0, 100, "unavailable", "unavailable", False)
    try:
        raw = json.loads(read_text_with_retry(path))
        if not isinstance(raw, dict):
            raise ValueError
        enabled = raw.get("purge-enabled") is True
        minimum = float(raw.get("minimum-archive-age-seconds", 0))
        batch = int(raw.get("max-batch-size", 100))
        if not math.isfinite(minimum) or minimum < 0 or batch <= 0 or (enabled and minimum <= 0):
            raise ValueError
        canonical = json.dumps(
            {"purge-enabled": enabled, "minimum-archive-age-seconds": minimum, "max-batch-size": batch},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return RetentionPolicy(enabled, minimum, batch, str(raw.get("policy-id", "machine-default")), digest, True)
    except (OSError, ValueError, TypeError):
        return RetentionPolicy(False, 0.0, 100, "invalid", "invalid", False)


def policy_matches(snapshot: dict[str, Any]) -> bool:
    current = load_retention_policy()
    return current.available and current.digest == snapshot.get("policy-digest") and current.policy_id == snapshot.get("policy-id")


__all__ = ["RetentionPolicy", "load_retention_policy", "policy_matches", "policy_path"]
