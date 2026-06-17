"""Shared time utilities."""
from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format (``+00:00`` offset)."""
    return datetime.now(timezone.utc).isoformat()


def now_iso_z(timespec: str = "auto") -> str:
    """Return current UTC timestamp in ISO 8601 with a ``Z`` suffix.

    Equivalent to ``now_iso()`` but renders the UTC offset as ``Z`` instead of
    ``+00:00``. Pass ``timespec`` to control sub-second precision (e.g.
    ``"microseconds"``); defaults to ``"auto"`` to match a bare ``isoformat()``.
    """
    return datetime.now(timezone.utc).isoformat(timespec=timespec).replace("+00:00", "Z")


def now_compact_z() -> str:
    """Return current UTC timestamp as ``YYYYMMDDTHHMMSSZ`` (filename-safe)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
