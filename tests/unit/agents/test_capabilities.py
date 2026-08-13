from __future__ import annotations

import pytest

from audiagentic.components.agents.capabilities.contracts import (
    CapabilityRequirementId,
    LaunchContribution,
)
from audiagentic.components.agents.capabilities.resolver import resolve_role_manifest
from audiagentic.components.agents.capabilities.vocabulary import CapabilityVocabulary
from audiagentic.components.agents.models.role import Role
from audiagentic.components.providers.providers_api import read_provider_capability_evidence


def test_role_manifest_fingerprint_is_independent_of_role_order() -> None:
    vocabulary = CapabilityVocabulary({CapabilityRequirementId("files"): LaunchContribution(arguments=("--files",))})
    roles = (Role("b", required_capabilities=(CapabilityRequirementId("files"),)), Role("a"))
    evidence = {"facts": ({"capability_id": "files", "support_assessment": "supported", "source": "test"},)}
    first = resolve_role_manifest(roles, vocabulary, evidence)
    second = resolve_role_manifest(tuple(reversed(roles)), vocabulary, evidence)
    assert first.fingerprint == second.fingerprint


def test_unknown_and_evidence_only_capabilities_fail() -> None:
    role = Role("r", required_capabilities=(CapabilityRequirementId("unknown"),))
    with pytest.raises(ValueError, match="unknown"):
        resolve_role_manifest((role,), CapabilityVocabulary({}), object())
    vocabulary = CapabilityVocabulary({}, frozenset({CapabilityRequirementId("observed")}))
    with pytest.raises(ValueError, match="evidence-only"):
        resolve_role_manifest((Role("r", required_capabilities=(CapabilityRequirementId("observed"),)),), vocabulary, object())


def test_provider_evidence_is_read_through_public_boundary() -> None:
    snapshot = read_provider_capability_evidence("local-openai")
    assert snapshot.provider_id == "local-openai"
    assert isinstance(snapshot.facts, tuple)
