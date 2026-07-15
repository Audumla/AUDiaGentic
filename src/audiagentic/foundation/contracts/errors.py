"""Error envelope contract and helpers."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

ERROR_CODE_PREFIXES: dict[str, str] = {
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
    "UNS": "Unsupported: feature not implemented by this component",
}

ERROR_CODE_PATTERN = re.compile(r"^[A-Z]{2,}-[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-\d{3}$")
ERROR_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9]{0,38}([a-z0-9]+-[a-z0-9]+)*$")
_REDACT_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)(?:sk-|ghp_|xoxb-)[A-Za-z0-9\-._~+/]{10,}"),
]
_DETAILS_MAX_OUTPUT = 1024


def _redact_value(key: str, value: Any) -> Any:
    if isinstance(value, str):
        for pat in _REDACT_PATTERNS:
            if pat.search(value):
                return "[REDACTED]"
        if key in ("stdout", "stderr") and len(value) > _DETAILS_MAX_OUTPUT:
            return value[:_DETAILS_MAX_OUTPUT] + f"... (truncated, {len(value)} total chars)"
        return value
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(key, item) for item in value]
    return value


def redact_details(details: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if details is None:
        return None
    return {k: _redact_value(k, v) for k, v in details.items()}


def _validate_code(code: str) -> None:
    if not code or not ERROR_CODE_PATTERN.match(code):
        raise ValueError(f"invalid error code format: {code!r} (expected PREFIX-COMPONENT-NNN)")
    prefix = code.split("-")[0]
    if prefix not in ERROR_CODE_PREFIXES:
        raise ValueError(f"unknown error prefix {prefix!r} in code {code!r}; valid prefixes: {sorted(ERROR_CODE_PREFIXES)}")


def _validate_kind(kind: str) -> None:
    if not kind or not ERROR_KIND_PATTERN.match(kind):
        raise ValueError(f"invalid error kind {kind!r}; must be lowercase-hyphenated identifier")


@dataclass(eq=False)
class _Error(Exception):
    code: str
    kind: str
    message: str
    details: Mapping[str, Any] | None = None
    _validated: bool = field(default=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self._validated:
            return
        object.__setattr__(self, "_validated", True)
        _validate_code(self.code)
        _validate_kind(self.kind)
        if not self.message:
            raise ValueError("error message must not be empty")
        object.__setattr__(self, "details", redact_details(self.details))
        if _ERROR_RESOLUTIONS_LOADED and self.code not in _ERROR_RESOLUTIONS:
            _error_code_blocker(self.code)

    def __str__(self) -> str:
        base = f"{self.code}: {self.message}"
        if self.details:
            import json

            return f"{base} details={json.dumps(dict(self.details))}"
        return base


AudiaGenticError = _Error


def make_error(
    *,
    prefix: str,
    component: str,
    number: int,
    kind: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> AudiaGenticError:
    if prefix not in ERROR_CODE_PREFIXES:
        raise ValueError(f"unknown error prefix {prefix!r}; valid prefixes: {sorted(ERROR_CODE_PREFIXES)}")
    _validate_kind(kind)
    if not message:
        raise ValueError("error message must not be empty")

    code = f"{prefix}-{component.upper()}-{number:03d}"
    _validate_code(code)
    return _Error(
        code=code,
        kind=kind,
        message=message,
        details=redact_details(details),
        _validated=True,
    )


def make_error_code(prefix: str, component: str, number: int) -> str:
    if prefix not in ERROR_CODE_PREFIXES:
        raise ValueError(f"unknown error prefix {prefix!r}; valid prefixes: {sorted(ERROR_CODE_PREFIXES)}")
    code = f"{prefix}-{component.upper()}-{number:03d}"
    _validate_code(code)
    return code


def make_error_factory(prefix: str, component: str, kind: str) -> Callable[..., AudiaGenticError]:
    def _factory(code_number: int, message: str, **details: Any) -> AudiaGenticError:
        return make_error(
            prefix=prefix,
            component=component,
            number=code_number,
            kind=kind,
            message=message,
            details=details or None,
        )

    return _factory


def to_error_envelope(error: AudiaGenticError) -> dict[str, Any]:
    _validate_code(error.code)
    _validate_kind(error.kind)
    envelope: dict[str, Any] = {
        "contract-version": "v1",
        "ok": False,
        "error-code": error.code,
        "error-kind": error.kind,
        "message": error.message,
        "details": redact_details(error.details) or {},
    }
    resolution = get_error_resolution(error.code)
    if resolution:
        envelope["resolution"] = resolution
    return envelope


_ERROR_RESOLUTIONS: dict[str, str] = {}


def register_error_resolution(code: str, resolution: str) -> None:
    _ERROR_RESOLUTIONS[code] = resolution


def get_error_resolution(code: str) -> str | None:
    return _ERROR_RESOLUTIONS.get(code)


def get_error_message(code: str) -> str:
    return _ERROR_RESOLUTIONS.get(code, code)


_ERROR_RESOLUTIONS_LOADED = False


def _error_code_blocker(code: str) -> None:
    """Raise a ValueError when an error code is used without being registered.

    This enforces Standard 8 (ARCHITECTURE_STANDARDS.md §4) and the
    ARCHITECTURE_GUIDELINES.md §3 rule: register each public error code in
    the owning component's error-resolutions.yaml before use.
    """
    raise ValueError(
        f"Error code {code!r} is not registered in any component's error-resolutions.yaml. "
        f"Before use, add it to src/audiagentic/config/components/<component>/error-resolutions.yaml. "
        f"See ARCHITECTURE_STANDARDS.md §4 and ARCHITECTURE_GUIDELINES.md §3."
    )


def _mark_error_resolutions_loaded() -> None:
    global _ERROR_RESOLUTIONS_LOADED
    _ERROR_RESOLUTIONS_LOADED = True


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
        "error-code": {"type": "string", "pattern": "^[A-Z]{2,}-[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-\d{3}$"},
        "error-kind": {"type": "string", "pattern": "^[a-z][a-z0-9]{0,38}([a-z0-9]+-[a-z0-9]+)*$"},
        "message": {"type": "string"},
        "details": {"type": "object"},
    },
}
