"""Error envelope contract and helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

ERROR_KINDS = (
    "validation",
    "business-rule",
    "io",
    "external",
    "internal",
)

ERROR_CODE_PREFIXES = (
    "FND",
    "LFC",
    "RLS",
    "JOB",
    "PRV",
    "DSC",
    "MIG",
)


@dataclass(frozen=True)
class AudiaGenticError(Exception):
    code: str
    kind: str
    message: str
    details: Mapping[str, Any] | None = None

    def __str__(self) -> str:  # pragma: no cover - readable stderr
        return f"{self.code}: {self.message}"


def make_error_code(prefix: str, kind: str, number: int) -> str:
    if prefix not in ERROR_CODE_PREFIXES:
        raise ValueError(f"invalid prefix: {prefix}")
    if kind.upper() not in {"VALIDATION", "BUSINESS", "IO", "EXTERNAL", "INTERNAL"}:
        raise ValueError(f"invalid kind: {kind}")
    return f"{prefix}-{kind.upper()}-{number:03d}"


def to_error_envelope(error: AudiaGenticError) -> dict[str, Any]:
    if error.kind not in ERROR_KINDS:
        raise ValueError(f"invalid error kind: {error.kind}")
    prefix = error.code.split("-")[0]
    if prefix not in ERROR_CODE_PREFIXES:
        raise ValueError(f"invalid error code prefix: {prefix}")
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
        "error-code": {"type": "string"},
        "error-kind": {"type": "string", "enum": list(ERROR_KINDS)},
        "message": {"type": "string"},
        "details": {"type": "object"},
    },
}
