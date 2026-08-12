"""Gateway job execution context — submission envelope and resolved manifest.

SH02 contract (docs/design/gateway-execution-context.md v0.4). The envelope is
the existing submit surface made explicit and versioned; the manifest freezes
the resolution that already happens implicitly on submit. One immutable
manifest per request; all attempts share it (RV565). Later items add fields
via a schema version bump — nothing speculative here (RV566/RV567).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    # Type-check-only: keeps this in sync with providers.contracts.provider_execution
    # .ProviderIsolationTier without importing it at runtime. worker_host.py
    # imports this module (via worker_protocol.py) at its own top level, before
    # main()'s redirect_stdout(sys.stderr) guard — importing anything under
    # audiagentic.components.providers there triggers the providers package's
    # eager adapter-loading __init__.py unprotected, corrupting the worker's
    # stdout-framed IPC protocol (CC51 finding). The runtime value set below is
    # a deliberate, documented duplicate for that reason.
    IsolationTier = Any
else:
    IsolationTier = Literal["full-isolation", "partial-isolation", "no-isolation"]

from audiagentic.foundation.contracts.errors import AudiaGenticError

ENVELOPE_SCHEMA_VERSION = 2
MANIFEST_SCHEMA_VERSION = 2
SUPPORTED_ENVELOPE_VERSIONS: tuple[int, ...] = (1, 2)

_ISOLATION_TIERS = {"full-isolation", "partial-isolation", "no-isolation"}
_MODES = {"async", "blocking"}
_MAX_IDEMPOTENCY_KEY_LENGTH = 512

# Request metadata becomes durable record data and lifecycle-event metadata.
# Keep control fields at the explicit envelope boundary and never let callers
# smuggle a second raw prompt or idempotency key through aliases.  The
# remaining metadata remains deliberately small and provenance-oriented (for
# example correlation_id, subject, and job-id); credential scanning below
# still rejects secret-like values.
_RESERVED_METADATA_KEY_FORMS = frozenset(
    {
        "prompt",
        "promptbody",
        "prompttext",
        "rawprompt",
        "idempotency",
        "idempotencykey",
        "rawidempotencykey",
    }
)

# Values that must never travel in envelope metadata; prompt content is
# exempt (prompts may legitimately discuss keys) and is never persisted raw.
_CREDENTIAL_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _err(code: str, message: str, details: dict[str, Any] | None = None) -> AudiaGenticError:
    return AudiaGenticError(code=code, kind="agents", message=message, details=details or {})


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint_form(display_path: str, *, windows: bool) -> str:
    """Fingerprint form of an already-resolved absolute path.

    Windows: casefolded, forward slashes. POSIX: NFC-normalized, case kept.
    """
    if windows:
        return display_path.replace("\\", "/").casefold()
    return unicodedata.normalize("NFC", display_path)


@dataclass(frozen=True)
class CanonicalRoot:
    display: str
    fingerprint: str


def canonicalize_project_root(raw: str | Path, *, windows: bool | None = None) -> CanonicalRoot:
    """Resolve a submitted project root to display + fingerprint forms.

    Rejects empty/relative roots (VAL-AGW-062) and UNC paths (VAL-AGW-064).
    """
    if windows is None:
        windows = os.name == "nt"
    text = str(raw).strip()
    if not text:
        raise _err("VAL-AGW-062", "project_root is required")
    if text.startswith(("\\\\", "//")):
        raise _err("VAL-AGW-064", "UNC/network project roots are unsupported", {"project_root": text})
    # Test and remote clients can present Windows spelling while the control
    # plane is running elsewhere. Normalize separators before resolution so a
    # trailing backslash is not treated as a literal POSIX filename and given
    # a different execution-context fingerprint.
    path = Path(text.replace("\\", "/") if windows else text)
    if not path.is_absolute():
        raise _err("VAL-AGW-062", "project_root must be absolute", {"project_root": text})
    resolved = path.resolve()
    display = str(resolved)
    return CanonicalRoot(display=display, fingerprint=fingerprint_form(display, windows=windows))


@dataclass(frozen=True)
class SessionSpec:
    session_id: str | None = None
    keep_alive: bool | None = None
    idle_timeout_seconds: float | None = None
    max_lifetime_seconds: float | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SessionSpec:
        if not isinstance(value, Mapping):
            raise _err("VAL-AGW-082", "gateway submission session must be a mapping")
        return cls(
            session_id=value.get("session_id"),
            keep_alive=value.get("keep_alive"),
            idle_timeout_seconds=value.get("idle_timeout_seconds"),
            max_lifetime_seconds=value.get("max_lifetime_seconds"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "keep_alive": self.keep_alive,
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "max_lifetime_seconds": self.max_lifetime_seconds,
        }


@dataclass(frozen=True)
class SubmissionEnvelope:
    """What a client asks for — the existing submit surface plus versioning."""

    project_root: str
    schema_version: int = ENVELOPE_SCHEMA_VERSION
    idempotency_key: str | None = None
    correlation_id: str | None = None
    source: str | None = None
    execution_profile_id: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    component_profile: str | None = None
    mode: str = "async"
    timeout_seconds: float | None = None
    session: SessionSpec = field(default_factory=SessionSpec)
    prompt_body: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    work_id: str | None = None
    context_id: str | None = None
    message_id: str | None = None
    agent_config_fingerprint: str | None = None
    role_manifest_fingerprint: str | None = None
    eligible_instance_ids: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SubmissionEnvelope:
        if not isinstance(value, Mapping):
            raise _err("VAL-AGW-082", "gateway submission must be a mapping")
        metadata = value.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise _err("VAL-AGW-082", "gateway submission metadata must be a mapping")
        session = value.get("session", {})
        return cls(
            project_root=value.get("project_root", ""),
            schema_version=value.get("schema_version", ENVELOPE_SCHEMA_VERSION),
            idempotency_key=value.get("idempotency_key"),
            correlation_id=value.get("correlation_id"),
            source=value.get("source"),
            execution_profile_id=value.get("execution_profile_id"),
            provider_id=value.get("provider_id"),
            model_id=value.get("model_id"),
            component_profile=value.get("component_profile"),
            mode=value.get("mode", "async"),
            timeout_seconds=value.get("timeout_seconds"),
            session=SessionSpec.from_mapping(session),
            prompt_body=value.get("prompt_body"),
            metadata=dict(metadata),
            work_id=value.get("work_id"),
            context_id=value.get("context_id"),
            message_id=value.get("message_id"),
            agent_config_fingerprint=value.get("agent_config_fingerprint"),
            role_manifest_fingerprint=value.get("role_manifest_fingerprint"),
            eligible_instance_ids=tuple(value.get("eligible_instance_ids") or ()),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "source": self.source,
            "project_root": self.project_root,
            "execution_profile_id": self.execution_profile_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "component_profile": self.component_profile,
            "mode": self.mode,
            "timeout_seconds": self.timeout_seconds,
            "session": self.session.to_mapping(),
            "prompt_body": self.prompt_body,
            "metadata": dict(self.metadata),
            "work_id": self.work_id,
            "context_id": self.context_id,
            "message_id": self.message_id,
            "agent_config_fingerprint": self.agent_config_fingerprint,
            "role_manifest_fingerprint": self.role_manifest_fingerprint,
            "eligible_instance_ids": list(self.eligible_instance_ids),
        }

    def validate(self, *, windows: bool | None = None) -> CanonicalRoot:
        """Validate and return the canonical project root.

        Raises VAL-AGW-069 (version), VAL-AGW-062/-064 (root),
        VAL-AGW-063 (selection), VAL-AGW-065 (credential material in
        metadata), VAL-AGW-066 (mode), and VAL-AGW-082 (wire shape).
        """
        _require_string("project_root", self.project_root)
        _require_integer("schema_version", self.schema_version)
        _require_optional_string("idempotency_key", self.idempotency_key, max_length=_MAX_IDEMPOTENCY_KEY_LENGTH)
        for name in (
            "correlation_id",
            "source",
            "execution_profile_id",
            "provider_id",
            "model_id",
            "component_profile",
        ):
            _require_optional_string(name, getattr(self, name), allow_empty=name == "component_profile")
        _require_string("mode", self.mode)
        _require_optional_number("timeout_seconds", self.timeout_seconds, positive=True)
        _validate_session_spec(self.session)
        if self.prompt_body is not None:
            _require_string("prompt_body", self.prompt_body)
        _validate_metadata(self.metadata)
        if self.schema_version not in SUPPORTED_ENVELOPE_VERSIONS:
            raise _err(
                "VAL-AGW-069",
                "unsupported envelope schema version",
                {
                    "requested": self.schema_version,
                    "supported_min": min(SUPPORTED_ENVELOPE_VERSIONS),
                    "supported_max": max(SUPPORTED_ENVELOPE_VERSIONS),
                },
            )
        if (self.provider_id is None) != (self.model_id is None):
            raise _err(
                "VAL-AGW-063",
                "provider_id and model_id must be given together",
                {"provider_id": self.provider_id, "model_id": self.model_id},
            )
        if self.mode not in _MODES:
            raise _err("VAL-AGW-066", "mode must be 'async' or 'blocking'", {"mode": self.mode})
        for key, value in self.metadata.items():
            if _contains_credential_value(value):
                raise _err(
                    "VAL-AGW-065",
                    "credential-like material is not allowed in envelope metadata",
                    {"metadata_key": key},
                )
        return canonicalize_project_root(self.project_root, windows=windows)


def sanitize_submission_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return metadata safe for durable request records and lifecycle events.

    This is intentionally a small scrubber, not a second metadata contract:
    envelope-owned prompt/idempotency data is removed at every nesting level,
    while correlation and subject provenance are retained unchanged.
    """
    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise _err("VAL-AGW-082", "gateway submission metadata must be a mapping")

    def scrub(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: scrub(item)
                for key, item in value.items()
                if _metadata_key_form(key) not in _RESERVED_METADATA_KEY_FORMS
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, tuple):
            return [scrub(item) for item in value]
        return value

    return scrub(metadata)


def _metadata_key_form(key: Any) -> str:
    return "".join(character for character in key.casefold() if character.isalnum()) if isinstance(key, str) else ""


def _wire_error(field: str, message: str) -> AudiaGenticError:
    return _err("VAL-AGW-082", message, {"field": field})


def _require_string(field: str, value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise _wire_error(field, f"gateway submission {field} must be a non-empty string")


def _require_optional_string(
    field: str, value: Any, *, allow_empty: bool = False, max_length: int | None = None
) -> None:
    if value is None:
        return
    if not isinstance(value, str) or (not allow_empty and not value):
        raise _wire_error(field, f"gateway submission {field} must be a non-empty string when supplied")
    if max_length is not None and len(value) > max_length:
        raise _wire_error(field, f"gateway submission {field} exceeds its maximum length")


def _require_integer(field: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _wire_error(field, f"gateway submission {field} must be an integer")


def _require_optional_number(field: str, value: Any, *, positive: bool = False, nonnegative: bool = False) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _wire_error(field, f"gateway submission {field} must be a finite number when supplied")
    if positive and value <= 0:
        raise _wire_error(field, f"gateway submission {field} must be positive")
    if nonnegative and value < 0:
        raise _wire_error(field, f"gateway submission {field} must be non-negative")


def _validate_session_spec(session: SessionSpec) -> None:
    if not isinstance(session, SessionSpec):
        raise _wire_error("session", "gateway submission session is invalid")
    _require_optional_string("session.session_id", session.session_id)
    if session.keep_alive is not None and not isinstance(session.keep_alive, bool):
        raise _wire_error("session.keep_alive", "gateway submission session.keep_alive must be a boolean")
    _require_optional_number("session.idle_timeout_seconds", session.idle_timeout_seconds, nonnegative=True)
    _require_optional_number("session.max_lifetime_seconds", session.max_lifetime_seconds, nonnegative=True)


def _validate_metadata(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise _wire_error("metadata", "gateway submission metadata must be a mapping")

    def valid(item: Any) -> bool:
        if item is None or isinstance(item, (str, bool, int)):
            return True
        if isinstance(item, float):
            return math.isfinite(item)
        if isinstance(item, Mapping):
            return all(isinstance(key, str) and valid(child) for key, child in item.items())
        if isinstance(item, (list, tuple)):
            return all(valid(child) for child in item)
        return False

    if not valid(value):
        raise _wire_error("metadata", "gateway submission metadata must contain JSON-compatible values")


def _contains_credential(text: str) -> bool:
    return any(pattern.search(text) for pattern in _CREDENTIAL_PATTERNS)


def _contains_credential_value(value: Any) -> bool:
    """Inspect JSON-shaped metadata without scanning the separate prompt field."""
    if isinstance(value, str):
        return _contains_credential(value)
    if isinstance(value, Mapping):
        return any(_contains_credential_value(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_credential_value(item) for item in value)
    return False


@dataclass(frozen=True)
class ManifestIdentity:
    """Identity-bearing resolved context — the fingerprint input, nothing else."""

    project_root: str  # fingerprint-form canonical path; also the execution cwd
    execution_profile_id: str
    provider_id: str
    # AS105/AS101: free-instance dispatch binds a concrete model only at
    # dispatch time, never at admission -- so this is unknown for a
    # multi-instance profile when the manifest is built. Not required for
    # identity: agent_runtime_digest already covers the resolved profile's
    # full instances set, so a None model_id here does not weaken the
    # fingerprint's ability to detect a profile-content change.
    model_id: str | None
    provider_isolation_tier: str
    component_profile: str  # "" = base components
    agent_runtime_digest: str

    def __post_init__(self) -> None:
        if self.provider_isolation_tier not in _ISOLATION_TIERS:
            raise _err(
                "VAL-AGW-067",
                "provider_isolation_tier must be an enumerated isolation tier",
                {"provider_isolation_tier": self.provider_isolation_tier},
            )
        for name in ("project_root", "execution_profile_id", "provider_id", "agent_runtime_digest"):
            if not getattr(self, name):
                raise _err("VAL-AGW-068", f"manifest identity field {name} is required", {"field": name})

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ManifestIdentity:
        return cls(
            project_root=value["project_root"],
            execution_profile_id=value["execution_profile_id"],
            provider_id=value["provider_id"],
            model_id=value["model_id"],
            provider_isolation_tier=value["provider_isolation_tier"],
            component_profile=value.get("component_profile", ""),
            agent_runtime_digest=value["agent_runtime_digest"],
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "project_root": self.project_root,
            "execution_profile_id": self.execution_profile_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "provider_isolation_tier": self.provider_isolation_tier,
            "component_profile": self.component_profile,
            "agent_runtime_digest": self.agent_runtime_digest,
        }


def compute_context_fingerprint(identity: ManifestIdentity) -> str:
    return sha256_hex(canonical_json(identity.to_mapping()))


def compute_agent_runtime_digest(
    resolved_profile: Mapping[str, Any],
    provider_config_state: Mapping[str, Any],
    component_overlay: Mapping[str, Any],
) -> str:
    """Digest of the resolved agent runtime (approved recipe, design doc §3.1).

    Inputs are resolved objects, never raw file bytes: cosmetic file noise
    cannot move the digest, any real configuration change does.
    """
    return sha256_hex(
        canonical_json(
            {
                "execution_profile": dict(resolved_profile),
                "provider_config": dict(provider_config_state),
                "component_overlay": dict(component_overlay),
            }
        )
    )


def compute_prompt_digest(prompt_body: str | None) -> str:
    return sha256_hex(prompt_body or "")


def derive_idempotency_key(
    explicit_key: str | None,
    *,
    context_fingerprint: str,
    prompt_digest: str,
    session_id: str | None,
) -> str:
    """Client key wins; else a fresh unique key per admission.

    Deriving a key from context+prompt+session (the original design doc §5.2
    behavior) silently replayed the first request when an agent legitimately
    repeated an identical prompt ("continue", "try again", identical tool
    instructions). Deduplication is opt-in: only an explicit caller key (or a
    durable spool event ID used as one) expresses retry intent.
    """
    if explicit_key:
        return explicit_key
    del context_fingerprint, prompt_digest, session_id
    import uuid

    return f"auto-{uuid.uuid4().hex}"


@dataclass(frozen=True)
class ExecutionManifest:
    """Immutable resolution of one request. All attempts share it (RV565)."""

    schema_version: int
    manifest_id: str
    request_id: str
    resolved_at: str
    identity: ManifestIdentity
    context_fingerprint: str
    session: SessionSpec
    mode: str
    timeout_seconds: float | None
    prompt_digest: str
    work_id: str | None = None
    context_id: str | None = None
    message_id: str | None = None
    agent_config_fingerprint: str | None = None
    role_manifest_fingerprint: str | None = None
    eligible_instance_ids: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ExecutionManifest:
        return cls(
            schema_version=int(value["schema_version"]),
            manifest_id=value["manifest_id"],
            request_id=value["request_id"],
            resolved_at=value["resolved_at"],
            identity=ManifestIdentity.from_mapping(value["identity"]),
            context_fingerprint=value["context_fingerprint"],
            session=SessionSpec.from_mapping(value.get("session") or {}),
            mode=value.get("mode", "async"),
            timeout_seconds=value.get("timeout_seconds"),
            prompt_digest=value["prompt_digest"],
            work_id=value.get("work_id"),
            context_id=value.get("context_id"),
            message_id=value.get("message_id"),
            agent_config_fingerprint=value.get("agent_config_fingerprint"),
            role_manifest_fingerprint=value.get("role_manifest_fingerprint"),
            eligible_instance_ids=tuple(value.get("eligible_instance_ids") or ()),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "request_id": self.request_id,
            "resolved_at": self.resolved_at,
            "identity": self.identity.to_mapping(),
            "context_fingerprint": self.context_fingerprint,
            "session": self.session.to_mapping(),
            "mode": self.mode,
            "timeout_seconds": self.timeout_seconds,
            "prompt_digest": self.prompt_digest,
            "work_id": self.work_id,
            "context_id": self.context_id,
            "message_id": self.message_id,
            "agent_config_fingerprint": self.agent_config_fingerprint,
            "role_manifest_fingerprint": self.role_manifest_fingerprint,
            "eligible_instance_ids": list(self.eligible_instance_ids),
        }


def build_manifest(
    envelope: SubmissionEnvelope,
    *,
    manifest_id: str,
    request_id: str,
    resolved_at: str,
    canonical_root: CanonicalRoot,
    execution_profile_id: str,
    provider_id: str,
    model_id: str | None,
    provider_isolation_tier: str,
    agent_runtime_digest: str,
) -> ExecutionManifest:
    """Freeze one admission's resolution into an immutable manifest.

    The caller (gateway admission, SH03+) supplies the resolution outcome;
    this function owns identity assembly, fingerprint, and prompt digest.
    """
    identity = ManifestIdentity(
        project_root=canonical_root.fingerprint,
        execution_profile_id=execution_profile_id,
        provider_id=provider_id,
        model_id=model_id,
        provider_isolation_tier=provider_isolation_tier,
        component_profile=envelope.component_profile or "",
        agent_runtime_digest=agent_runtime_digest,
    )
    return ExecutionManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        manifest_id=manifest_id,
        request_id=request_id,
        resolved_at=resolved_at,
        identity=identity,
        context_fingerprint=compute_context_fingerprint(identity),
        session=envelope.session,
        mode=envelope.mode,
        timeout_seconds=envelope.timeout_seconds,
        prompt_digest=compute_prompt_digest(envelope.prompt_body),
    )


__all__ = [
    "ENVELOPE_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "SUPPORTED_ENVELOPE_VERSIONS",
    "CanonicalRoot",
    "ExecutionManifest",
    "IsolationTier",
    "ManifestIdentity",
    "SessionSpec",
    "SubmissionEnvelope",
    "build_manifest",
    "canonical_json",
    "canonicalize_project_root",
    "compute_agent_runtime_digest",
    "compute_context_fingerprint",
    "compute_prompt_digest",
    "derive_idempotency_key",
    "fingerprint_form",
    "sanitize_submission_metadata",
    "sha256_hex",
]
