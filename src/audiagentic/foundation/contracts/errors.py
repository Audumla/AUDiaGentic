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
    UNS - Unsupported: feature not implemented by this component.

Kinds identify the component or functional area that raised the error.
Kinds are structurally validated (lowercase-hyphens, 2-40 chars) so new
components can self-define without touching the foundation. Invalid formats
are rejected at construction time.

Codes must be unique within their (prefix, component) namespace.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

# Fixed set of error-type prefixes.
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

# Validates PREFIX-COMPONENT-NNN format.
ERROR_CODE_PATTERN = re.compile(r"^[A-Z]{2,}-[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-\d{3}$")

# Structural kind pattern: lowercase letters, digits, hyphens; 2-40 chars.
# Must start and end with a letter. No leading/trailing/multiple hyphens.
ERROR_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9]{0,38}([a-z0-9]+-[a-z0-9]+)*$")

# Sensitive-value patterns for error-detail redaction.
# Matches bearer tokens and known API-key prefixes (OpenAI sk-, GitHub ghp_, Slack xoxb-).
_REDACT_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)(?:sk-|ghp_|xoxb-)[A-Za-z0-9\-._~+/]{10,}"),
]

# Maximum length for stdout/stderr in error details before truncation.
_DETAILS_MAX_OUTPUT = 1024


def _redact_value(key: str, value: Any) -> Any:
    """Redact a single detail value.

    Redacts known sensitive patterns (bearer tokens, API-key prefixes) and
    truncates large stdout/stderr.  Does NOT redact arbitrary dict values
    (paths, counts, config keys are legitimate diagnostics).
    """
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
    """Redact sensitive values from an error details dict.

    Redacts known sensitive patterns (bearer tokens, API-key prefixes) and
    truncates large stdout/stderr.  Does NOT redact arbitrary dict values
    (paths, counts, config keys are legitimate diagnostics).

    Returns ``None`` when input is ``None``; otherwise a new dict.
    """
    if details is None:
        return None
    return {k: _redact_value(k, v) for k, v in details.items()}


def _validate_code(code: str) -> None:
    if not code or not ERROR_CODE_PATTERN.match(code):
        raise ValueError(f"invalid error code format: {code!r} (expected PREFIX-COMPONENT-NNN)")
    prefix = code.split("-")[0]
    if prefix not in ERROR_CODE_PREFIXES:
        raise ValueError(
            f"unknown error prefix {prefix!r} in code {code!r}; "
            f"valid prefixes: {sorted(ERROR_CODE_PREFIXES)}"
        )


def _validate_kind(kind: str) -> None:
    if not kind or not ERROR_KIND_PATTERN.match(kind):
        raise ValueError(
            f"invalid error kind {kind!r}; "
            f"must be lowercase-hyphenated identifier (e.g. 'providers', 'state-store')"
        )


@dataclass(eq=False)
class _Error(Exception):
    """Structured error — use make_error() to construct.

    Direct construction is validated: prefix, kind, and code format are
    checked in __post_init__.  Invalid values raise ValueError immediately.

    Not a frozen dataclass: Python's exception machinery assigns
    ``__traceback__``/``__cause__``/``__context__`` on raise and during
    propagation through ``contextlib`` ``with`` blocks, which a frozen
    ``__setattr__`` would reject with ``FrozenInstanceError``. ``eq=False`` keeps
    identity-based equality and hashing (the convention for exceptions); error
    identity is the code/kind/message carried in the envelope, not value equality.
    """
    code: str
    kind: str
    message: str
    details: Mapping[str, Any] | None = None
    _validated: bool = field(default=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self._validated:
            return  # make_error() already validated + redacted
        object.__setattr__(self, "_validated", True)
        _validate_code(self.code)
        _validate_kind(self.kind)
        if not self.message:
            raise ValueError("error message must not be empty")
        object.__setattr__(self, "details", redact_details(self.details))

    def __str__(self) -> str:  # pragma: no cover - readable stderr
        base = f"{self.code}: {self.message}"
        if self.details:
            import json
            return f"{base} details={json.dumps(dict(self.details))}"
        return base


# Public alias so existing `except AudiaGenticError` clauses keep working.
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
    """Construct a validated error.

    All fields are checked at construction time:
      - prefix must be in ERROR_CODE_PREFIXES
      - kind must be a valid lowercase-hyphenated identifier
      - code is assembled as PREFIX-COMPONENT-NNN and validated against the pattern
      - message must be non-empty

    Raises ValueError if any field is invalid.

    Example:
        raise make_error(
            prefix="IO",
            component="PCFG",
            number=1,
            kind="providers",
            message="failed to read provider config",
            details={"path": str(path)},
        )
    """
    if prefix not in ERROR_CODE_PREFIXES:
        raise ValueError(
            f"unknown error prefix {prefix!r}; "
            f"valid prefixes: {sorted(ERROR_CODE_PREFIXES)}"
        )
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
    """Assemble and validate a raw error code string.

    Prefer make_error() for raising — this helper exists for cases where
    the code string is needed independently (e.g. documentation, test assertions).
    """
    if prefix not in ERROR_CODE_PREFIXES:
        raise ValueError(
            f"unknown error prefix {prefix!r}; "
            f"valid prefixes: {sorted(ERROR_CODE_PREFIXES)}"
        )
    code = f"{prefix}-{component.upper()}-{number:03d}"
    _validate_code(code)
    return code


def make_error_factory(prefix: str, component: str, kind: str) -> Callable[..., AudiaGenticError]:
    """Return a bound error-construction function for a component.

    Each module calls this once at module scope to create its local
    ``_xxx_error`` helper, replacing the duplicated 8-line pattern:

        def _xxx_error(code_number, message, **details):
            return make_error(prefix=..., component=..., number=code_number,
                              kind=..., message=message, details=details)

    Usage::

        _my_error = make_error_factory("VAL", "COMP", "components")
        raise _my_error(1, "something failed", path=str(path))
    """
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


# ---------------------------------------------------------------------------
# Error resolution registry — maps error codes to agent-facing resolution text.
# ---------------------------------------------------------------------------

_ERROR_RESOLUTIONS: dict[str, str] = {}


def register_error_resolution(code: str, resolution: str) -> None:
    """Register an agent-facing resolution for an error code.

    The resolution is included automatically in error envelopes returned to
    agents, and is also available via the ``error_resolve`` MCP tool.

    Args:
        code: Full error code (e.g. "VAL-PROJFILE-001").
        resolution: Human-readable instructions the agent can follow.
    """
    _ERROR_RESOLUTIONS[code] = resolution


def get_error_resolution(code: str) -> str | None:
    """Return the registered resolution for an error code, or None."""
    return _ERROR_RESOLUTIONS.get(code)


def get_error_message(code: str) -> str:
    """Return the human-readable message for an error code.

    Looks up the resolution registry. Falls back to the code itself when
    no message is registered, so callers never get an empty string.
    """
    return _ERROR_RESOLUTIONS.get(code, code)


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
        "error-kind": {"type": "string", "pattern": "^[a-z][a-z0-9]{0,38}([a-z0-9]+-[a-z0-9]+)*$"},
        "message": {"type": "string"},
        "details": {"type": "object"},
    },
}
