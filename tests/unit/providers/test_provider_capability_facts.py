from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, fields

import pytest

from audiagentic.components.providers.descriptors.base import (
    CapabilityEvidence,
    ProviderCapabilityFact,
    ProviderDescriptor,
)
from audiagentic.components.providers.descriptors.capability_facts import (
    capability_facts_payload,
    render_capability_facts_json,
    render_capability_facts_markdown,
    validate_capability_fact_catalog,
    validate_provider_capability_facts,
)
from audiagentic.components.providers.descriptors.loader import (
    PROVIDER_SPEC,
    get_providers_config_dir,
    load_provider_descriptor,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _fact(
    capability_id: str = "catalog-read",
    *,
    subject: str = "external:catalog-read",
    tier: str = "documentation",
    state: str = "verified",
) -> ProviderCapabilityFact:
    return ProviderCapabilityFact(
        capability_id=capability_id,
        subject=subject,
        mechanism="provider CLI",
        constraints=("installed tool required",),
        limitations=("authentication dependent",),
        support_assessment="supported",
        action_needed=None,
        evidence=CapabilityEvidence(
            evidence_tier=tier,
            tool_version="1.2.3",
            fact_anchor="docs/reference/evidence.md#catalog",
            review_state=state,
        ),
    )


def test_capability_fact_types_are_frozen() -> None:
    fact = _fact()

    with pytest.raises(FrozenInstanceError):
        fact.capability_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        fact.evidence.review_state = "quarantined"  # type: ignore[misc]


def test_opencode_capability_facts_load_from_yaml() -> None:
    descriptor = load_provider_descriptor(get_providers_config_dir() / "opencode.yaml")

    assert tuple(fact.capability_id for fact in descriptor.capability_facts) == (
        "cli-install",
        "host-extension",
        "mcp-config",
        "plugin-config",
        "lsp-config",
        "model-catalog-refresh",
        "surface-skill",
        "perm-declaration",
        "model-config-projection",
        # ACP capability family (plan agent-sessions)
        "acp-stdio-transport",
        "acp-live-session",
        "acp-session-resume",
        "acp-shared-live-session",
    )
    catalog_fact = descriptor.capability_facts[5]
    assert catalog_fact.subject == "fetch_catalog_fn"
    assert catalog_fact.evidence.evidence_tier == "execution"
    assert catalog_fact.evidence.review_state == "verified"
    assert catalog_fact.constraints == ("Provider command requires an installed OpenCode CLI.",)
    assert descriptor.capability_facts[8].evidence.review_state == "pending-review"


def test_capability_facts_default_empty() -> None:
    descriptor = PROVIDER_SPEC.build({"provider_id": "fixture", "display_name": "Fixture"})

    assert descriptor.capability_facts == ()


@pytest.mark.parametrize(
    ("evidence", "code"),
    [
        ({"evidence_tier": "guess", "review_state": "pending-review"}, "VAL-PCAP-003"),
        ({"evidence_tier": "documentation", "review_state": "maybe"}, "VAL-PCAP-004"),
        ({"evidence_tier": "execution", "review_state": "verified"}, "VAL-PCAP-005"),
    ],
)
def test_loader_rejects_invalid_evidence(evidence, code) -> None:
    with pytest.raises(AudiaGenticError, match=code):
        PROVIDER_SPEC.build(
            {
                "provider_id": "fixture",
                "display_name": "Fixture",
                "capability_facts": [
                    {
                        "capability_id": "catalog-read",
                        "subject": "external:catalog-read",
                        "evidence": evidence,
                    }
                ],
            }
        )


def test_loader_rejects_unknown_fact_fields_instead_of_losing_them() -> None:
    with pytest.raises(AudiaGenticError, match="VAL-PCAP-009"):
        PROVIDER_SPEC.build(
            {
                "provider_id": "fixture",
                "display_name": "Fixture",
                "capability_facts": [
                    {
                        "capability_id": "catalog-read",
                        "subject": "external:catalog-read",
                        "unexpected": "would otherwise be lost",
                    }
                ],
            }
        )


def test_duplicate_capability_id_rejected_within_provider() -> None:
    descriptor = ProviderDescriptor(
        provider_id="fixture",
        display_name="Fixture",
        capability_facts=(_fact(), _fact()),
    )

    with pytest.raises(AudiaGenticError, match="VAL-PCAP-002"):
        validate_provider_capability_facts(descriptor)


def test_subject_must_resolve() -> None:
    descriptor = ProviderDescriptor(
        provider_id="fixture",
        display_name="Fixture",
        capability_facts=(_fact(subject="model_config"),),
    )

    with pytest.raises(AudiaGenticError, match="VAL-PCAP-007"):
        validate_provider_capability_facts(descriptor)


def test_same_capability_id_allowed_for_different_providers() -> None:
    descriptors = {
        "a": ProviderDescriptor("a", "A", capability_facts=(_fact(),)),
        "b": ProviderDescriptor("b", "B", capability_facts=(_fact(),)),
    }

    validate_capability_fact_catalog(descriptors)


def test_json_serializer_is_deterministic_and_lossless() -> None:
    descriptor = ProviderDescriptor("fixture", "Fixture", capability_facts=(_fact(),))
    descriptors = {"fixture": descriptor}

    first = render_capability_facts_json(descriptors)
    second = render_capability_facts_json(descriptors)
    decoded = json.loads(first)

    assert first == second
    assert decoded == capability_facts_payload(descriptors)
    serialized = decoded["providers"][0]["capability_facts"][0]
    assert serialized["constraints"] == ["installed tool required"]
    assert serialized["limitations"] == ["authentication dependent"]
    assert serialized["evidence"]["fact_anchor"] == "docs/reference/evidence.md#catalog"


def test_markdown_serializer_is_deterministic_and_complete() -> None:
    descriptors = {
        "fixture": ProviderDescriptor("fixture", "Fixture", capability_facts=(_fact(),))
    }

    first = render_capability_facts_markdown(descriptors)

    assert first == render_capability_facts_markdown(descriptors)
    assert "| fixture | catalog-read | external:catalog-read |" in first
    assert "installed tool required" in first
    assert "authentication dependent" in first
    assert "docs/reference/evidence.md#catalog" in first


def test_ma19_ma20_authority_separation() -> None:
    """MA19 capability_facts cannot declare MA20 automation families, modes, or contracts.

    The loader rejects unknown fact fields, so a fact that attempts to carry
    MA20-style fields (family_id, supported_modes, payload_contract, etc.)
    is rejected at load time — MA19 facts are evidence only, never execution authority.
    """
    with pytest.raises(AudiaGenticError, match="VAL-PCAP-009"):
        PROVIDER_SPEC.build(
            {
                "provider_id": "fixture",
                "display_name": "Fixture",
                "capability_facts": [
                    {
                        "capability_id": "fake-ma20",
                        "subject": "external:fake-ma20",
                        "family_id": "managed-mcp",
                        "supported_modes": ["apply", "prune"],
                        "payload_contract": "provider-managed-mcp-payload/v1",
                        "result_contract": "provider-managed-mcp-result/v1",
                        "ownership_scope_required": True,
                    }
                ],
            }
        )


def test_ma19_fact_shape_cannot_hold_ma20_fields() -> None:
    """ProviderCapabilityFact has no fields for MA20 automation declarations.

    The fact shape is locked: capability_id, subject, mechanism, constraints,
    limitations, support_assessment, action_needed, evidence. There is no
    family_id, supported_modes, payload_contract, or result_contract.
    """
    fact_fields = {f.name for f in fields(ProviderCapabilityFact)}
    ma20_fields = {"family_id", "supported_modes", "payload_contract", "result_contract", "ownership_scope_required"}

    assert ma20_fields.isdisjoint(fact_fields), (
        f"ProviderCapabilityFact must not contain MA20 fields: {ma20_fields & fact_fields}"
    )


def test_generated_views_not_imported_by_runtime() -> None:
    """The capability_facts module's serializers produce strings; no generated

    Python modules exist that runtime code could import. Verify the module
    does not write generated views to disk as importable artifacts.
    """
    import audiagentic.components.providers.descriptors.capability_facts as cf

    # The serializers return strings, not file paths or module references
    descriptor = ProviderDescriptor("fixture", "Fixture", capability_facts=(_fact(),))
    descriptors = {"fixture": descriptor}

    json_output = render_capability_facts_json(descriptors)
    md_output = render_capability_facts_markdown(descriptors)

    assert isinstance(json_output, str)
    assert isinstance(md_output, str)
    assert not hasattr(cf, "write_capability_facts_json")
    assert not hasattr(cf, "write_capability_facts_markdown")
