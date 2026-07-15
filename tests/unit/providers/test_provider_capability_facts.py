from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

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
        "model-catalog-refresh",
        "model-config-projection",
    )
    verified = descriptor.capability_facts[0]
    assert verified.subject == "fetch_catalog_fn"
    assert verified.evidence.evidence_tier == "execution"
    assert verified.evidence.review_state == "verified"
    assert verified.constraints == ("Provider command requires an installed OpenCode CLI.",)
    assert descriptor.capability_facts[1].evidence.review_state == "pending-review"


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
