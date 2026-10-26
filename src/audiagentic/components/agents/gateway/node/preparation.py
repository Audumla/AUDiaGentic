"""Pure node preparation/attestation contracts, not materialization or execution.

The instructions owner supplies the expanded-prompt digest; the preparation
owner supplies selected semantic fingerprints and local render/manifest data.
No catalog, server path, provider call, authority decision or receipt is read
here. Public mappings are exact and carry digests/IDs only, except the protected
final command's raw prompt. Never log that command. Retained private manifest
bytes are opaque owner output, not a wire schema or an execution authorization.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

from .contracts import (
    CommandIdentity,
    _freeze,
    _identifier,
    _integer,
    canonical_json,
    conflict,
    invalid,
)


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise invalid(1, "Preparation fingerprint must be lowercase SHA256")
    return value


def _text_digest(value: str) -> str:
    if not isinstance(value, str):
        raise invalid(1, "Preparation prompt must be text")
    try:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    except UnicodeError:
        raise invalid(1, "Preparation prompt must be valid UTF-8 text") from None


class _PublicContract:
    def to_mapping(self) -> dict[str, Any]:
        return {f.name.replace("_", "-"): (
            value.to_mapping() if isinstance(value := getattr(self, f.name), _PublicContract) else value
        ) for f in fields(self)}

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_mapping())).hexdigest()

    @classmethod
    def _exact(cls, value: Mapping[str, Any]) -> dict[str, Any]:
        names = {f.name.replace("_", "-") for f in fields(cls)}
        if not isinstance(value, Mapping) or set(value) != names:
            raise invalid(1, "Preparation contract fields must match exactly")
        return {k.replace("-", "_"): v for k, v in value.items()}


@dataclass(frozen=True)
class PromptSemanticIdentity(_PublicContract):
    composition_fingerprint: str
    prompt_definition_fingerprint: str
    prompt_id: str
    execution_profile_id: str
    expanded_prompt_version: int
    expanded_prompt_sha256: str
    raw_prompt_sha256: str

    def __post_init__(self):
        for value in (self.composition_fingerprint, self.prompt_definition_fingerprint,
                      self.expanded_prompt_sha256, self.raw_prompt_sha256):
            _sha(value)
        _identifier(self.prompt_id)
        _identifier(self.execution_profile_id)
        if type(self.expanded_prompt_version) is not int or self.expanded_prompt_version != 1:
            raise invalid(1, "Preparation expanded-prompt-version must be integer 1")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PromptSemanticIdentity:
        return cls(**cls._exact(value))


@dataclass(frozen=True)
class PreparationBinding(_PublicContract):
    command_id: str
    request_id: str
    node_id: str
    node_epoch: str
    gateway_owner_epoch: str
    connection_generation: int
    workspace_id: str
    grant_revision: int
    binding_generation: int
    preparation_challenge: str
    preparation_request_id: str

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in {"connection_generation", "grant_revision", "binding_generation"}:
                _integer(value)
            else:
                _identifier(value)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PreparationBinding:
        return cls(**cls._exact(value))


@dataclass(frozen=True)
class PreparationAttestation(_PublicContract):
    binding: PreparationBinding
    semantic: PromptSemanticIdentity
    rendered_prompt_sha256: str
    manifest_id: str
    provider_manifest_sha256: str
    context_fingerprint: str
    runtime_digest: str
    worker_id: str
    attempt_epoch: int
    provider_id: str
    model_id: str | None
    model_alias: str | None

    def __post_init__(self):
        if type(self.binding) is not PreparationBinding or type(self.semantic) is not PromptSemanticIdentity:
            raise invalid(1, "Preparation attestation requires typed binding and semantic identity")
        for value in (self.rendered_prompt_sha256, self.provider_manifest_sha256,
                      self.context_fingerprint, self.runtime_digest):
            _sha(value)
        _identifier(self.manifest_id)
        _identifier(self.worker_id)
        _integer(self.attempt_epoch)
        _identifier(self.provider_id)
        if self.model_id is None and self.model_alias is None:
            raise invalid(1, "Preparation requires model-id or model-alias")
        for value in (self.model_id, self.model_alias):
            if value is not None and (not isinstance(value, str) or not value
                                      or value != value.strip() or len(value) > 512
                                      or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise invalid(1, "Preparation model identity must be non-empty bounded text or null")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PreparationAttestation:
        kwargs = cls._exact(value)
        kwargs["binding"] = PreparationBinding.from_mapping(kwargs["binding"])
        kwargs["semantic"] = PromptSemanticIdentity.from_mapping(kwargs["semantic"])
        return cls(**kwargs)


@dataclass(frozen=True)
class RetainedNodePreparation:
    attestation: PreparationAttestation
    _rendered_prompt: str = field(repr=False)
    _provider_manifest: bytes = field(repr=False)

    def __post_init__(self):
        if type(self.attestation) is not PreparationAttestation:
            raise invalid(1, "Retained preparation requires a typed attestation")
        if _text_digest(self._rendered_prompt) != self.attestation.rendered_prompt_sha256:
            raise conflict(1, "Retained rendered prompt does not match preparation attestation")
        if not isinstance(self._provider_manifest, bytes) or not self._provider_manifest:
            raise invalid(1, "Retained preparation requires private immutable manifest bytes")
        if hashlib.sha256(self._provider_manifest).hexdigest() != self.attestation.provider_manifest_sha256:
            raise conflict(1, "Retained provider manifest does not match preparation attestation")


def prepare_node_command(
    *, binding: PreparationBinding, semantic: PromptSemanticIdentity,
    raw_prompt: str, rendered_prompt: str, manifest_id: str,
    context_fingerprint: str, runtime_digest: str, provider_manifest: bytes,
    worker_id: str, attempt_epoch: int, provider_id: str,
    model_id: str | None, model_alias: str | None,
) -> RetainedNodePreparation:
    """Retain owner-produced local data without reading any path/provider.

    The manifest owner supplies its canonical serialized bytes. Their exact-byte
    SHA256 is a content binding, not a replacement manifest identity or context
    fingerprint. No alternate JSON normalization pipeline is introduced here.
    Worker/attempt/provider/model fields must be actual node-local resolved facts,
    not labels inferred from an execution profile. They are attested scalar
    correlation only; provider resolution and terminal worker checks stay owned
    by the execution/central store. Model-id and model-alias may both be present,
    matching ProviderExecutionRequest; at least one is required. No provider
    request is instantiated here because that would require a private root.
    """
    if type(semantic) is not PromptSemanticIdentity or _text_digest(raw_prompt) != semantic.raw_prompt_sha256:
        raise conflict(1, "Raw prompt does not match selected semantic identity")
    if not isinstance(provider_manifest, bytes) or not provider_manifest:
        raise invalid(1, "Retained preparation requires private immutable manifest bytes")
    attestation = PreparationAttestation(
        binding=binding, semantic=semantic, rendered_prompt_sha256=_text_digest(rendered_prompt),
        manifest_id=manifest_id, provider_manifest_sha256=hashlib.sha256(provider_manifest).hexdigest(),
        context_fingerprint=context_fingerprint, runtime_digest=runtime_digest,
        worker_id=worker_id, attempt_epoch=attempt_epoch, provider_id=provider_id,
        model_id=model_id, model_alias=model_alias,
    )
    return RetainedNodePreparation(attestation, rendered_prompt, provider_manifest)


def build_final_command_payload(preparation: RetainedNodePreparation, raw_prompt: str) -> Mapping[str, Any]:
    """Return a deeply frozen protected command; no private render/manifest."""
    attestation = preparation.attestation
    if _text_digest(raw_prompt) != attestation.semantic.raw_prompt_sha256:
        raise conflict(1, "Final raw prompt differs from retained preparation")
    return _freeze({
        "semantic": attestation.semantic.to_mapping(), "attestation": attestation.to_mapping(),
        "raw-prompt": raw_prompt,
        "preparation-challenge": attestation.binding.preparation_challenge,
        "preparation-request-id": attestation.binding.preparation_request_id,
    })


def validate_final_command_payload(
    payload: Mapping[str, Any], identity: CommandIdentity,
    *, accepted_attestation: PreparationAttestation,
) -> PreparationAttestation:
    """Validate centrally against an accepted attestation, without private data.

    The caller supplies the attestation accepted for the preparation exchange,
    not one copied from the final command. Authentication, current-connection
    fencing and grant authorization remain their owning callers' responsibility.
    """
    expected_fields = {"semantic", "attestation", "raw-prompt", "preparation-challenge", "preparation-request-id"}
    if not isinstance(payload, Mapping) or set(payload) != expected_fields:
        raise invalid(1, "Final prepared command fields must match exactly")
    semantic = PromptSemanticIdentity.from_mapping(payload["semantic"])
    attestation = PreparationAttestation.from_mapping(payload["attestation"])
    if type(accepted_attestation) is not PreparationAttestation:
        raise invalid(1, "Final command requires a typed accepted preparation attestation")
    binding = accepted_attestation.binding
    if (type(identity) is not CommandIdentity or attestation != accepted_attestation
            or semantic != attestation.semantic
            or _text_digest(payload["raw-prompt"]) != semantic.raw_prompt_sha256
            or payload["preparation-challenge"] != binding.preparation_challenge
            or payload["preparation-request-id"] != binding.preparation_request_id
            or identity.execution_profile_id != semantic.execution_profile_id
            or identity.payload_sha256 != hashlib.sha256(canonical_json(payload)).hexdigest()
            or any(getattr(identity, name) != getattr(binding, name) for name in (
                "command_id", "request_id", "node_id", "node_epoch", "gateway_owner_epoch",
                "connection_generation", "workspace_id", "grant_revision", "binding_generation"))):
        raise conflict(1, "Final command does not match accepted preparation attestation")
    return attestation


def validate_final_command_preparation(
    preparation: RetainedNodePreparation, payload: Mapping[str, Any], identity: CommandIdentity,
    *, current_binding: PreparationBinding,
) -> PreparationAttestation:
    """Validate retained private inputs/current binding before receipt.prepare.

    current_binding comes from the trusted current connection/preparation owner,
    never copied from this command. This is correlation, not peer authentication.
    The caller still applies central authority and native-effect fences later.
    """
    if type(preparation) is not RetainedNodePreparation:
        raise invalid(1, "Final command requires typed retained preparation")
    attestation = validate_final_command_payload(
        payload, identity, accepted_attestation=preparation.attestation,
    )
    if type(current_binding) is not PreparationBinding or current_binding != attestation.binding:
        raise conflict(1, "Final command does not match current preparation binding")
    # Recheck private content at the consumption boundary as well as construction.
    preparation.__post_init__()
    return attestation
