"""Neutral SHA-256 digest helpers shared by every component.

One definition of "a lowercase SHA-256 hex digest" and of canonical JSON for
hashing, so components stop re-implementing both. Callers keep their own error
codes: these helpers return booleans/bytes and raise only ``ValueError``.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def is_sha256_hex(value: Any) -> bool:
    """True only for a 64-character lowercase hex string (not bytes, not uppercase)."""
    return isinstance(value, str) and _SHA256_HEX.fullmatch(value) is not None


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic UTF-8 JSON: sorted keys, compact separators, no NaN/Infinity.

    Raises ``ValueError`` (or ``TypeError``) for values JSON cannot represent exactly.
    """
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def canonical_digest(value: Any) -> str:
    """SHA-256 of ``canonical_json_bytes(value)``."""
    return sha256_hex(canonical_json_bytes(value))
