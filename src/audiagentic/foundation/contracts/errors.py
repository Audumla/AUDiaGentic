"""Error envelope contract and helpers.

Error code format: PREFIX-COMPONENT-NNN

Prefixes (fixed, error-type classification):
    VAL - Validation: bad input shape, schema failure, type mismatch.
    CON - Constraint: state invariant, workflow rule, precondition violation.
    RES - Resource: not found, quota exceeded, rate limited, empty result.
    IO  - I/O: local file read/write, path resolution, disk failure.
    NET - Network: connection refused, DNS failure, HTTP transport error.
    TO  - Timeout: operation exceeded its deadline.
    EXT - External: provider subprocess, third-party API, CLI tool failure.
    CFG - Configuration: missing config, bad setup, environment not ready.
    VER - Version: incompatible version, migration required.
    INT - Internal: unexpected state, unhandled branch, bug.

Kinds are open-ended and owned by each component. A kind identifies the
component or functional area that raised the error, e.g. "agent-jobs",
"providers", "release", "lifecycle", "state-store".

Codes must be unique within their prefix.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Fixed set of error-type prefixes.
ERROR_CODE_PREFIXES = {
    "VAL": "Validation: bad input shape, schema failure, type mismatch",
    "CON": "Constraint: state invariant, workflow rule, precondition violation",
    "RES": "Resource: not found, quota exceeded, rate limited, empty result",
    "IO": "I/O: local file read/write, path resolution, disk failure",
    "NET": "Network: connection refused, DNS failure, HTTP transport error",
    "TO": "Timeout: operation exceeded its deadline",
    "EXT": "External: provider subprocess, third-party API, CLI tool failure",
    "CFG": "Configuration: missing config, bad setup, environment not ready",
    "VER": "Version: incompatible version, migration required",
    "INT": "Internal: unexpected state, unhandled branch, bug",
}

# Validates PREFIX-COMPONENT-NNN format.
ERROR_CODE_PATTERN = re.compile(r"^[A-Z]{2,}-[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-\d{3}$")


@dataclass(eq=True)
class AudiaGenticError(Exception):
    code: str
    kind: str
    message: str
    details: Mapping[str, Any] | None = None

    def __str__(self) -> str:  # pragma: no cover - readable stderr
        base = f"{self.code}: {self.message}"
        if self.details:
            import json
            return f"{base} details={json.dumps(dict(self.details))}"
        return base


def make_error_code(prefix: str, kind: str, number: int) -> str:
    code = f"{prefix}-{kind.upper()}-{number:03d}"
    if not ERROR_CODE_PATTERN.match(code):
        raise ValueError(f"invalid error code format: {code!r} (expected PREFIX-KIND-NNN)")
    return code


def to_error_envelope(error: AudiaGenticError) -> dict[str, Any]:
    if not error.code or not ERROR_CODE_PATTERN.match(error.code):
        raise ValueError(f"invalid error code format: {error.code!r}")
    if not error.kind:
        raise ValueError("error kind is required")
    return {
        "contract-version": "v1",
        "ok": False,
        "error-code": error.code,
        "error-kind": error.kind,
        "message": error.message,
        "details": dict(error.details or {}),
    }


ERROR_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": [
        "contract-version",
        "ok",
        "error-code",
        "error-kind",
        "message",
        "details",
    ],
    "properties": {
        "contract-version": {"const": "v1"},
        "ok": {"const": False},
        "error-code": {"type": "string", "pattern": "^[A-Z]{2,}-[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-\\d{3}$"},
        "error-kind": {"type": "string"},
        "message": {"type": "string"},
        "details": {"type": "object"},
    },
}
