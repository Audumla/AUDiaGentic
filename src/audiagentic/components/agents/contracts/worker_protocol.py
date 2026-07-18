"""Private gateway-to-worker JSON protocol.

The protocol carries one MA17 provider execution request over a private pipe.
That request and its result are runtime-only: callers must never persist or log
the encoded envelopes.  Environment shaping, provider configuration, and
credential material are deliberately absent; the worker resolves those from
the frozen execution identity through provider-owned APIs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from audiagentic.components.agents.contracts._worker_protocol_validation import (
    EXECUTION_REQUEST_FIELDS,
    EXECUTION_RESULT_FIELDS,
    WORKER_PROTOCOL_VERSION,
    JsonObject,
    WorkerMessageType,
    json_object,
    protocol_error,
    require_canonical_root,
    require_component_profile,
    require_exact_fields,
    require_fingerprint,
    require_isolation_tier,
    require_positive_int,
    require_protocol,
    require_safe_error,
    require_string,
)
from audiagentic.components.agents.contracts.execution_context import IsolationTier


@dataclass(frozen=True)
class WorkerExecutionIdentity:
    """Frozen attempt and execution-context identity shared by all messages."""

    worker_id: str
    attempt_epoch: int
    manifest_id: str
    context_fingerprint: str
    project_root: str
    component_profile: str
    provider_isolation_tier: IsolationTier

    def __post_init__(self) -> None:
        object.__setattr__(self, "worker_id", require_string(self.worker_id, "worker-id"))
        object.__setattr__(
            self, "attempt_epoch", require_positive_int(self.attempt_epoch, "attempt-epoch")
        )
        object.__setattr__(self, "manifest_id", require_string(self.manifest_id, "manifest-id"))
        object.__setattr__(
            self, "context_fingerprint", require_fingerprint(self.context_fingerprint)
        )
        object.__setattr__(self, "project_root", require_canonical_root(self.project_root))
        object.__setattr__(
            self, "component_profile", require_component_profile(self.component_profile)
        )
        object.__setattr__(
            self,
            "provider_isolation_tier",
            require_isolation_tier(self.provider_isolation_tier, "provider-isolation-tier"),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, tier_field: str) -> WorkerExecutionIdentity:
        return cls(
            worker_id=value.get("worker-id"),
            attempt_epoch=value.get("attempt-epoch"),
            manifest_id=value.get("manifest-id"),
            context_fingerprint=value.get("context-fingerprint"),
            project_root=value.get("project-root"),
            component_profile=value.get("component-profile"),
            provider_isolation_tier=value.get(tier_field),
        )

    def to_mapping(self, *, tier_field: str) -> JsonObject:
        return {
            "worker-id": self.worker_id,
            "attempt-epoch": self.attempt_epoch,
            "manifest-id": self.manifest_id,
            "context-fingerprint": self.context_fingerprint,
            "project-root": self.project_root,
            "component-profile": self.component_profile,
            tier_field: self.provider_isolation_tier,
        }


@dataclass(frozen=True)
class WorkerProcessEvidence:
    """Child-reported process identity and effective working directory."""

    pid: int
    process_creation_identity: str
    working_directory: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "pid", require_positive_int(self.pid, "pid"))
        object.__setattr__(
            self,
            "process_creation_identity",
            require_string(self.process_creation_identity, "process-creation-identity"),
        )
        object.__setattr__(
            self,
            "working_directory",
            require_canonical_root(self.working_directory),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> WorkerProcessEvidence:
        return cls(
            pid=value.get("pid"),
            process_creation_identity=value.get("process-creation-identity"),
            working_directory=value.get("working-directory"),
        )

    def to_mapping(self) -> JsonObject:
        return {
            "pid": self.pid,
            "process-creation-identity": self.process_creation_identity,
            "working-directory": self.working_directory,
        }


_IDENTITY_FIELDS = frozenset(
    {
        "worker-id",
        "attempt-epoch",
        "manifest-id",
        "context-fingerprint",
        "project-root",
        "component-profile",
    }
)
_PROCESS_FIELDS = frozenset(
    {"pid", "process-creation-identity", "working-directory"}
)


@dataclass(frozen=True)
class WorkerExecuteEnvelope:
    identity: WorkerExecutionIdentity
    execution_request: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        request = json_object(
            self.execution_request, "execution-request", reject_runtime_material=True
        )
        require_exact_fields(request, EXECUTION_REQUEST_FIELDS)
        _require_inner_attempt_identity(request, self.identity)
        object.__setattr__(
            self,
            "execution_request",
            request,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> WorkerExecuteEnvelope:
        expected = _IDENTITY_FIELDS | {
            "protocol-version",
            "message-type",
            "provider-isolation-tier",
            "execution-request",
        }
        require_exact_fields(value, frozenset(expected))
        require_protocol(value["protocol-version"])
        if value["message-type"] != "execute":
            raise protocol_error(
                "VAL-AGW-074", "worker message type does not match execute envelope"
            )
        return cls(
            identity=WorkerExecutionIdentity.from_mapping(
                value, tier_field="provider-isolation-tier"
            ),
            execution_request=value["execution-request"],
        )

    def to_mapping(self) -> JsonObject:
        return {
            "protocol-version": WORKER_PROTOCOL_VERSION,
            "message-type": "execute",
            **self.identity.to_mapping(tier_field="provider-isolation-tier"),
            "execution-request": dict(self.execution_request),
        }


@dataclass(frozen=True)
class WorkerHandshakeEnvelope:
    identity: WorkerExecutionIdentity
    process: WorkerProcessEvidence

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> WorkerHandshakeEnvelope:
        _require_response_fields(value, "handshake", frozenset())
        return cls(
            identity=WorkerExecutionIdentity.from_mapping(
                value, tier_field="accepted-isolation-tier"
            ),
            process=WorkerProcessEvidence.from_mapping(value),
        )

    def to_mapping(self) -> JsonObject:
        return _response_mapping("handshake", self.identity, self.process)


@dataclass(frozen=True)
class WorkerResultEnvelope:
    identity: WorkerExecutionIdentity
    process: WorkerProcessEvidence
    execution_result: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        result = json_object(
            self.execution_result, "execution-result", reject_runtime_material=False
        )
        require_exact_fields(result, EXECUTION_RESULT_FIELDS)
        if (
            result.get("worker-id") != self.identity.worker_id
            or result.get("attempt-epoch") != self.identity.attempt_epoch
        ):
            raise protocol_error(
                "CON-AGW-074", "worker result attempt identity does not match its envelope"
            )
        object.__setattr__(
            self,
            "execution_result",
            result,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> WorkerResultEnvelope:
        _require_response_fields(value, "result", frozenset({"execution-result"}))
        return cls(
            identity=WorkerExecutionIdentity.from_mapping(
                value, tier_field="accepted-isolation-tier"
            ),
            process=WorkerProcessEvidence.from_mapping(value),
            execution_result=value["execution-result"],
        )

    def to_mapping(self) -> JsonObject:
        return {
            **_response_mapping("result", self.identity, self.process),
            "execution-result": dict(self.execution_result),
        }


@dataclass(frozen=True)
class WorkerErrorEnvelope:
    """Redacted terminal failure; raw exceptions and process output are forbidden."""

    identity: WorkerExecutionIdentity
    process: WorkerProcessEvidence
    error_code: str
    error_kind: str
    message: str

    def __post_init__(self) -> None:
        code, kind, message = require_safe_error(self.error_code, self.error_kind, self.message)
        object.__setattr__(self, "error_code", code)
        object.__setattr__(self, "error_kind", kind)
        object.__setattr__(self, "message", message)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> WorkerErrorEnvelope:
        _require_response_fields(value, "error", frozenset({"error-code", "error-kind", "message"}))
        return cls(
            identity=WorkerExecutionIdentity.from_mapping(
                value, tier_field="accepted-isolation-tier"
            ),
            process=WorkerProcessEvidence.from_mapping(value),
            error_code=value["error-code"],
            error_kind=value["error-kind"],
            message=value["message"],
        )

    def to_mapping(self) -> JsonObject:
        return {
            **_response_mapping("error", self.identity, self.process),
            "error-code": self.error_code,
            "error-kind": self.error_kind,
            "message": self.message,
        }


WorkerMessage: TypeAlias = (
    WorkerExecuteEnvelope | WorkerHandshakeEnvelope | WorkerResultEnvelope | WorkerErrorEnvelope
)


def _require_response_fields(
    value: Mapping[str, Any], message_type: WorkerMessageType, additional: frozenset[str]
) -> None:
    expected = (
        _IDENTITY_FIELDS
        | _PROCESS_FIELDS
        | {
            "protocol-version",
            "message-type",
            "accepted-isolation-tier",
        }
        | additional
    )
    require_exact_fields(value, frozenset(expected))
    require_protocol(value["protocol-version"])
    if value["message-type"] != message_type:
        raise protocol_error(
            "VAL-AGW-074", "worker message type does not match envelope", expected=message_type
        )


def _response_mapping(
    message_type: WorkerMessageType,
    identity: WorkerExecutionIdentity,
    process: WorkerProcessEvidence,
) -> JsonObject:
    return {
        "protocol-version": WORKER_PROTOCOL_VERSION,
        "message-type": message_type,
        **identity.to_mapping(tier_field="accepted-isolation-tier"),
        **process.to_mapping(),
    }


def _require_inner_attempt_identity(
    request: Mapping[str, Any], identity: WorkerExecutionIdentity
) -> None:
    expected = {
        "project-root": identity.project_root,
        "worker-id": identity.worker_id,
        "attempt-epoch": identity.attempt_epoch,
        "provider-isolation-tier": identity.provider_isolation_tier,
    }
    mismatched = sorted(
        key for key, expected_value in expected.items() if request.get(key) != expected_value
    )
    if mismatched:
        raise protocol_error(
            "CON-AGW-074",
            "provider execution request identity does not match its worker envelope",
            fields=mismatched,
        )


def encode_worker_message(message: WorkerMessage) -> str:
    """Encode one private-pipe frame without logging or persisting it."""
    return json.dumps(
        message.to_mapping(), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def decode_worker_message(frame: str) -> WorkerMessage:
    """Decode and strictly validate one private-pipe frame."""
    try:
        value = json.loads(frame)
    except (TypeError, json.JSONDecodeError) as exc:
        raise protocol_error("VAL-AGW-074", "worker protocol frame must be valid JSON") from exc
    if not isinstance(value, dict):
        raise protocol_error("VAL-AGW-074", "worker protocol frame must contain a JSON object")
    message_type = value.get("message-type")
    parsers = {
        "execute": WorkerExecuteEnvelope.from_mapping,
        "handshake": WorkerHandshakeEnvelope.from_mapping,
        "result": WorkerResultEnvelope.from_mapping,
        "error": WorkerErrorEnvelope.from_mapping,
    }
    parser = parsers.get(message_type)
    if parser is None:
        raise protocol_error("VAL-AGW-074", "worker protocol message type is unsupported")
    return parser(value)


__all__ = [
    "WORKER_PROTOCOL_VERSION",
    "WorkerErrorEnvelope",
    "WorkerExecuteEnvelope",
    "WorkerExecutionIdentity",
    "WorkerHandshakeEnvelope",
    "WorkerMessage",
    "WorkerProcessEvidence",
    "WorkerResultEnvelope",
    "decode_worker_message",
    "encode_worker_message",
]
