"""Shared utilities for the streaming protocol package (internal)."""
from __future__ import annotations

from datetime import datetime, timezone


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_now_us() -> str:
    """Microsecond-precision variant used by completion metadata."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
