"""Final commands must bind exact selected semantics and retained preparation."""
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.node.contracts import CommandIdentity, canonical_json
from audiagentic.components.agents.gateway.node.preparation import (
    PreparationAttestation,
    PreparationBinding,
    PromptSemanticIdentity,
    RetainedNodePreparation,
    build_final_command_payload,
    prepare_node_command,
    validate_final_command_payload,
    validate_final_command_preparation,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def prepared():
    raw = "raw prompt\r\n  preserve whitespace and λ"
    semantic = PromptSemanticIdentity("a" * 64, "b" * 64, "selected-prompt", "profile", 1,
                                      sha("expanded prompt"), sha(raw))
    binding = PreparationBinding("command", "request", "node", "node-epoch", "owner-epoch",
                                 1, "workspace", 2, 3, "challenge", "prepare-message")
    local = prepare_node_command(
        binding=binding, semantic=semantic, raw_prompt=raw,
        rendered_prompt="PRIVATE rendered prompt /local/provider/path",
        manifest_id="manifest", context_fingerprint="c" * 64, runtime_digest="d" * 64,
        provider_manifest=b"PRIVATE provider manifest /local/provider/path",
        worker_id="worker", attempt_epoch=1, provider_id="provider", model_id="vendor/model", model_alias=None,
    )
    payload = build_final_command_payload(local, raw)
    identity = identity_for(binding, payload)
    return local, payload, identity, binding


def identity_for(binding, payload):
    return CommandIdentity(
        binding.command_id, binding.request_id, binding.node_id, binding.node_epoch,
        binding.gateway_owner_epoch, binding.connection_generation, binding.workspace_id,
        binding.grant_revision, binding.binding_generation,
        hashlib.sha256(canonical_json(payload)).hexdigest(), payload["semantic"]["execution-profile-id"],
    )


def mutable(payload):
    return json.loads(canonical_json(payload))


def test_roundtrip_exact_schemas_and_canonical_digest(prepared):
    local, payload, identity, binding = prepared
    attestation = local.attestation
    assert PreparationAttestation.from_mapping(attestation.to_mapping()) == attestation
    assert PromptSemanticIdentity.from_mapping(attestation.semantic.to_mapping()) == attestation.semantic
    assert PreparationBinding.from_mapping(binding.to_mapping()) == binding
    assert attestation.digest == hashlib.sha256(canonical_json(attestation.to_mapping())).hexdigest()
    assert attestation.semantic.digest == hashlib.sha256(canonical_json(attestation.semantic.to_mapping())).hexdigest()
    assert set(payload["semantic"]) == {
        "composition-fingerprint", "prompt-definition-fingerprint", "prompt-id", "execution-profile-id",
        "expanded-prompt-version", "expanded-prompt-sha256", "raw-prompt-sha256",
    }
    assert validate_final_command_preparation(local, payload, identity, current_binding=binding) == attestation
    reversed_payload = dict(reversed(list(payload.items())))
    assert canonical_json(reversed_payload) == canonical_json(payload)


def test_private_data_excluded_and_final_payload_frozen(prepared):
    local, payload, _, _ = prepared
    assert "PRIVATE" not in repr(local)
    assert b"PRIVATE" not in canonical_json(payload)
    assert b"/local/provider/path" not in canonical_json(payload)
    assert not hasattr(local, "to_mapping")
    with pytest.raises(FrozenInstanceError):
        local._rendered_prompt = "changed"
    with pytest.raises(TypeError):
        payload["semantic"]["prompt-id"] = "changed"
    with pytest.raises(TypeError):
        payload["attestation"]["binding"]["node-id"] = "changed"


@pytest.mark.parametrize("field", ["composition-fingerprint", "prompt-definition-fingerprint",
                                  "expanded-prompt-sha256", "raw-prompt-sha256"])
def test_semantic_substitution_rejected_even_with_matching_final_digest(prepared, field):
    local, payload, _, binding = prepared
    changed = mutable(payload)
    changed["semantic"][field] = "e" * 64
    changed["attestation"]["semantic"][field] = "e" * 64
    with pytest.raises(AudiaGenticError):
        validate_final_command_preparation(local, changed, identity_for(binding, changed), current_binding=binding)


@pytest.mark.parametrize("field,value", [
    ("rendered-prompt-sha256", "e" * 64), ("manifest-id", "other-manifest"),
    ("provider-manifest-sha256", "e" * 64),
    ("context-fingerprint", "e" * 64), ("runtime-digest", "e" * 64),
    ("worker-id", "other-worker"), ("attempt-epoch", 2), ("provider-id", "other-provider"),
    ("model-id", "other-model"), ("model-alias", "other-alias"),
])
def test_attestation_substitution_rejected(prepared, field, value):
    local, payload, _, binding = prepared
    changed = mutable(payload)
    changed["attestation"][field] = value
    with pytest.raises(AudiaGenticError):
        validate_final_command_preparation(local, changed, identity_for(binding, changed), current_binding=binding)


@pytest.mark.parametrize("field,value", [
    ("request_id", "other"), ("command_id", "other"), ("node_id", "other"),
    ("node_epoch", "other"), ("gateway_owner_epoch", "other"), ("workspace_id", "other"),
    ("connection_generation", 2), ("binding_generation", 4), ("grant_revision", 3),
    ("preparation_challenge", "other"), ("preparation_request_id", "other"),
])
def test_wrong_current_scope_or_reconnect_rejected(prepared, field, value):
    local, payload, identity, binding = prepared
    current = replace(binding, **{field: value})
    with pytest.raises(AudiaGenticError):
        validate_final_command_preparation(local, payload, identity, current_binding=current)


@pytest.mark.parametrize("field,value", [
    ("request_id", "other"), ("command_id", "other"), ("node_id", "other"),
    ("node_epoch", "other"), ("gateway_owner_epoch", "other"), ("workspace_id", "other"),
    ("connection_generation", 2), ("binding_generation", 4), ("grant_revision", 3),
    ("payload_sha256", "e" * 64), ("execution_profile_id", "other"),
])
def test_final_identity_substitution_rejected(prepared, field, value):
    local, payload, identity, binding = prepared
    with pytest.raises(AudiaGenticError):
        validate_final_command_preparation(local, payload, replace(identity, **{field: value}), current_binding=binding)


@pytest.mark.parametrize("field,value", [("preparation-challenge", "other"),
                                        ("preparation-request-id", "other"), ("raw-prompt", "other raw")])
def test_final_message_correlation_rejected(prepared, field, value):
    local, payload, _, binding = prepared
    changed = mutable(payload)
    changed[field] = value
    with pytest.raises(AudiaGenticError):
        validate_final_command_preparation(local, changed, identity_for(binding, changed), current_binding=binding)


@pytest.mark.parametrize("target", ["final", "semantic", "attestation", "binding"])
@pytest.mark.parametrize("operation", ["extra", "missing"])
def test_exact_schema_no_private_metadata(prepared, target, operation):
    local, payload, identity, binding = prepared
    changed = mutable(payload)
    mapping = changed if target == "final" else (
        changed["attestation"]["binding"] if target == "binding" else changed[target])
    if operation == "extra":
        mapping["project-root"] = "/private/server/path"
    else:
        del mapping[next(iter(mapping))]
    with pytest.raises(AudiaGenticError):
        validate_final_command_preparation(local, changed, identity, current_binding=binding)


@pytest.mark.parametrize("value", [True, False, "1", 0, 2])
def test_expanded_prompt_version_is_exact_integer(prepared, value):
    with pytest.raises(AudiaGenticError):
        replace(prepared[0].attestation.semantic, expanded_prompt_version=value)


@pytest.mark.parametrize("value", [True, "1", 0])
def test_generation_types_are_strict(prepared, value):
    with pytest.raises(AudiaGenticError):
        replace(prepared[3], connection_generation=value)


def test_retained_render_must_match_attestation(prepared):
    with pytest.raises(AudiaGenticError):
        RetainedNodePreparation(prepared[0].attestation, "substituted", b"manifest")
    with pytest.raises(AudiaGenticError):
        build_final_command_payload(prepared[0], "wrong raw prompt")


def test_preparation_is_pure_and_does_not_read_paths(prepared, monkeypatch):
    local, payload, _, binding = prepared

    def forbidden(*args, **kwargs):
        pytest.fail("preparation tried to read a filesystem path")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    result = prepare_node_command(
        binding=binding, semantic=local.attestation.semantic, raw_prompt=payload["raw-prompt"],
        rendered_prompt=local._rendered_prompt, manifest_id=local.attestation.manifest_id,
        context_fingerprint=local.attestation.context_fingerprint,
        runtime_digest=local.attestation.runtime_digest, provider_manifest=local._provider_manifest,
        worker_id=local.attestation.worker_id, attempt_epoch=local.attestation.attempt_epoch,
        provider_id=local.attestation.provider_id, model_id=local.attestation.model_id,
        model_alias=local.attestation.model_alias,
    )
    assert result == local


@pytest.mark.parametrize("value", ["A" * 64, "a" * 63, "/private/path", True, None])
def test_semantic_fingerprints_are_exact_sha256(prepared, value):
    with pytest.raises(AudiaGenticError):
        replace(prepared[0].attestation.semantic, prompt_definition_fingerprint=value)


@pytest.mark.parametrize("value", [None, [], "not-an-object"])
def test_nested_malformed_contracts_rejected(prepared, value):
    local, payload, identity, binding = prepared
    changed = mutable(payload)
    changed["attestation"]["semantic"] = value
    with pytest.raises(AudiaGenticError):
        validate_final_command_preparation(local, changed, identity, current_binding=binding)


def test_preparation_rejects_wrong_raw_before_retention(prepared):
    local, _, _, binding = prepared
    with pytest.raises(AudiaGenticError):
        prepare_node_command(
            binding=binding, semantic=local.attestation.semantic, raw_prompt="substituted raw",
            rendered_prompt="rendered", manifest_id="manifest", context_fingerprint="c" * 64,
            runtime_digest="d" * 64, provider_manifest=b"private",
            worker_id="worker", attempt_epoch=1, provider_id="provider", model_id="model", model_alias=None,
        )


def test_raw_prompt_utf8_error_does_not_expose_prompt(prepared):
    with pytest.raises(AudiaGenticError) as caught:
        build_final_command_payload(prepared[0], "SECRET\ud800")
    assert "SECRET" not in str(caught.value)


def test_private_manifest_substitution_rejected_with_same_attested_id_and_context(prepared):
    local, payload, _, _ = prepared
    assert local.attestation.provider_manifest_sha256 == hashlib.sha256(local._provider_manifest).hexdigest()
    assert payload["attestation"]["provider-manifest-sha256"] == local.attestation.provider_manifest_sha256
    with pytest.raises(AudiaGenticError, match="provider manifest"):
        replace(local, _provider_manifest=b"substituted PRIVATE manifest")


@pytest.mark.parametrize("value", [None, "a" * 63, "A" * 64, True])
def test_provider_manifest_digest_is_strict(prepared, value):
    with pytest.raises(AudiaGenticError):
        replace(prepared[0].attestation, provider_manifest_sha256=value)


def test_old_attestation_without_manifest_digest_rejected(prepared):
    mapping = prepared[0].attestation.to_mapping()
    del mapping["provider-manifest-sha256"]
    with pytest.raises(AudiaGenticError):
        PreparationAttestation.from_mapping(mapping)


def test_central_validator_needs_only_accepted_public_attestation(prepared):
    local, payload, identity, _ = prepared
    accepted = PreparationAttestation.from_mapping(local.attestation.to_mapping())
    assert validate_final_command_payload(payload, identity, accepted_attestation=accepted) == accepted


def test_central_validator_rejects_wrong_accepted_attestation(prepared):
    local, payload, identity, _ = prepared
    accepted = replace(local.attestation, manifest_id="other-manifest")
    with pytest.raises(AudiaGenticError):
        validate_final_command_payload(payload, identity, accepted_attestation=accepted)


@pytest.mark.parametrize("field,value", [
    ("command_id", "other"), ("request_id", "other"), ("node_id", "other"),
    ("node_epoch", "other"), ("gateway_owner_epoch", "other"),
    ("connection_generation", 2), ("workspace_id", "other"),
    ("grant_revision", 3), ("binding_generation", 4),
    ("execution_profile_id", "other"), ("payload_sha256", "e" * 64),
])
def test_central_validator_rejects_identity_binding_and_digest(prepared, field, value):
    local, payload, identity, _ = prepared
    with pytest.raises(AudiaGenticError):
        validate_final_command_payload(payload, replace(identity, **{field: value}),
                                       accepted_attestation=local.attestation)


@pytest.mark.parametrize("field", ["raw-prompt", "preparation-challenge", "preparation-request-id"])
def test_central_validator_rejects_rehashed_final_substitution(prepared, field):
    local, payload, _, binding = prepared
    changed = mutable(payload)
    changed[field] = "substitution"
    with pytest.raises(AudiaGenticError):
        validate_final_command_payload(changed, identity_for(binding, changed),
                                       accepted_attestation=local.attestation)


@pytest.mark.parametrize("model_id,model_alias", [
    ("vendor/model:version", None), (None, "selected-alias"), ("model", "selected-alias"),
])
def test_model_id_or_alias_and_both_are_supported(prepared, model_id, model_alias):
    attestation = replace(prepared[0].attestation, model_id=model_id, model_alias=model_alias)
    mapping = attestation.to_mapping()
    assert mapping["model-id"] == model_id and mapping["model-alias"] == model_alias
    assert PreparationAttestation.from_mapping(mapping) == attestation


@pytest.mark.parametrize("model_id,model_alias", [
    (None, None), ("", None), (None, ""), ("model", ""), ("", "alias"),
    (True, None), (None, 1), (" model", None), ("model\nSECRET", None), ("a" * 513, None),
])
def test_missing_or_fake_empty_model_identity_rejected(prepared, model_id, model_alias):
    with pytest.raises(AudiaGenticError):
        replace(prepared[0].attestation, model_id=model_id, model_alias=model_alias)


@pytest.mark.parametrize("value", [True, False, 0, -1, "1", 1.5])
def test_attempt_epoch_is_positive_strict_integer(prepared, value):
    with pytest.raises(AudiaGenticError):
        replace(prepared[0].attestation, attempt_epoch=value)


@pytest.mark.parametrize("field", ["worker-id", "attempt-epoch", "provider-id", "model-id", "model-alias"])
def test_actual_worker_correlation_fields_are_required(prepared, field):
    mapping = prepared[0].attestation.to_mapping()
    del mapping[field]
    with pytest.raises(AudiaGenticError):
        PreparationAttestation.from_mapping(mapping)
