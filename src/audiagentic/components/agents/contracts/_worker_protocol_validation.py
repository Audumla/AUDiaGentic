"""Validation primitives for the private worker protocol."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import Any, Literal, TypeAlias

from audiagentic.components.agents.contracts.execution_context import (
    IsolationTier,
    canonicalize_project_root,
)
from audiagentic.foundation.contracts.errors import (
    ERROR_CODE_PATTERN,
    ERROR_KIND_PATTERN,
    AudiaGenticError,
)

WORKER_PROTOCOL_VERSION = "gateway-worker-v1"

WorkerMessageType = Literal["execute", "handshake", "result", "error"]
JsonObject: TypeAlias = dict[str, Any]

ISOLATION_TIERS = frozenset(("full-isolation", "partial-isolation", "no-isolation"))
CONTEXT_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
COMPONENT_PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CREDENTIAL_VALUE = re.compile(
    r"(?i)(?:bearer\s+[A-Za-z0-9\-._~+/]+=*|(?:sk-|ghp_|xoxb-)[A-Za-z0-9\-._~+/]{10,})"
)
EXECUTION_REQUEST_FIELDS = frozenset(
    {
        "project-root",
        "provider-id",
        "model-id",
        "model-alias",
        "packet-data",
        "worker-id",
        "attempt-epoch",
        "provider-isolation-tier",
    }
)
EXECUTION_RESULT_FIELDS = frozenset(
    {"provider-id", "model-id", "worker-id", "attempt-epoch", "result-data"}
)
FORBIDDEN_RUNTIME_KEYS = frozenset(
    {
        "api-key",
        "api_key",
        "authorization",
        "config",
        "configuration",
        "credential",
        "credentials",
        "env",
        "environment",
        "secret",
        "secrets",
        "token",
    }
)


def protocol_error(code: str, message: str, **details: Any) -> AudiaGenticError:
    return AudiaGenticError(code=code, kind="agents", message=message, details=details)


def require_exact_fields(value: Mapping[str, Any], expected: frozenset[str]) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown or missing:
        raise protocol_error(
            "VAL-AGW-074",
            "worker protocol envelope fields do not match the message contract",
            unknown_fields=unknown,
            missing_fields=missing,
        )


def require_protocol(value: Any) -> None:
    if value != WORKER_PROTOCOL_VERSION:
        raise protocol_error(
            "VER-AGW-001",
            "worker protocol version is incompatible",
            expected=WORKER_PROTOCOL_VERSION,
            actual=value,
        )


def require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise protocol_error(
            "VAL-AGW-074", "worker protocol field must be a non-empty string", field=field_name
        )
    return value


def require_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise protocol_error(
            "VAL-AGW-074", "worker protocol field must be a positive integer", field=field_name
        )
    return value


def require_fingerprint(value: Any) -> str:
    fingerprint = require_string(value, "context-fingerprint")
    if not CONTEXT_FINGERPRINT.fullmatch(fingerprint):
        raise protocol_error(
            "VAL-AGW-074",
            "worker context fingerprint must be a lowercase SHA-256 digest",
            field="context-fingerprint",
        )
    return fingerprint


def require_component_profile(value: Any) -> str:
    if not isinstance(value, str):
        raise protocol_error("VAL-AGW-074", "worker component profile identity must be a string")
    if value and (value in {".", ".."} or not COMPONENT_PROFILE.fullmatch(value)):
        raise protocol_error("VAL-AGW-074", "worker component profile identity is invalid")
    return value


def require_isolation_tier(value: Any, field_name: str) -> IsolationTier:
    if value not in ISOLATION_TIERS:
        raise protocol_error(
            "VAL-AGW-074", "worker isolation tier is not supported", field=field_name
        )
    return value


def require_canonical_root(value: Any) -> str:
    raw = require_string(value, "project-root")
    try:
        canonical = canonicalize_project_root(raw).display
    except AudiaGenticError as exc:
        raise protocol_error(
            "VAL-AGW-074", "worker project root must be absolute and canonical"
        ) from exc
    if os.path.normcase(raw) != os.path.normcase(canonical):
        raise protocol_error("VAL-AGW-074", "worker project root must be absolute and canonical")
    return canonical


def json_object(value: Any, field_name: str, *, reject_runtime_material: bool) -> JsonObject:
    if not isinstance(value, Mapping):
        raise protocol_error(
            "VAL-AGW-074", "worker protocol field must be a JSON object", field=field_name
        )
    try:
        normalized = json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise protocol_error(
            "VAL-AGW-074", "worker protocol field must contain only JSON values", field=field_name
        ) from exc
    if not isinstance(normalized, dict):
        raise protocol_error(
            "VAL-AGW-074", "worker protocol field must be a JSON object", field=field_name
        )
    if reject_runtime_material:
        forbidden = sorted(find_forbidden_keys(normalized))
        if forbidden:
            raise protocol_error(
                "VAL-AGW-075",
                "worker execution request must not carry environment, configuration, or secret fields",
                fields=forbidden,
            )
    return normalized


def find_forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold()
            if normalized in FORBIDDEN_RUNTIME_KEYS:
                found.add(normalized)
            found.update(find_forbidden_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(find_forbidden_keys(item))
    return found


def require_safe_error(error_code: Any, error_kind: Any, message: Any) -> tuple[str, str, str]:
    code = require_string(error_code, "error-code")
    kind = require_string(error_kind, "error-kind")
    safe_message = require_string(message, "message")
    if not ERROR_CODE_PATTERN.fullmatch(code):
        raise protocol_error("VAL-AGW-074", "worker error code is invalid")
    if not ERROR_KIND_PATTERN.fullmatch(kind):
        raise protocol_error("VAL-AGW-074", "worker error kind is invalid")
    if (
        len(safe_message) > 512
        or "\n" in safe_message
        or "\r" in safe_message
        or CREDENTIAL_VALUE.search(safe_message)
    ):
        raise protocol_error("VAL-AGW-075", "worker error message must be concise and redacted")
    return code, kind, safe_message


__all__ = [
    "EXECUTION_REQUEST_FIELDS",
    "EXECUTION_RESULT_FIELDS",
    "JsonObject",
    "WORKER_PROTOCOL_VERSION",
    "WorkerMessageType",
    "json_object",
    "protocol_error",
    "require_canonical_root",
    "require_component_profile",
    "require_exact_fields",
    "require_fingerprint",
    "require_isolation_tier",
    "require_positive_int",
    "require_protocol",
    "require_safe_error",
    "require_string",
]
