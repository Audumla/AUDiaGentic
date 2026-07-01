"""Cross-system coupling regression: provider register -> feature registry.

When a provider descriptor is registered, the provider registry's
_register_feature_implementation() must populate the feature registry with
each provider's ImplementationDescriptor + derived impl-features.

This test ensures the coupling remains intact after YAML migration.
"""
from __future__ import annotations

from audiagentic.foundation.features import registry as feature_registry


def setup_function() -> None:
    feature_registry.clear()


def teardown_function() -> None:
    feature_registry.clear()


def test_provider_registration_populates_feature_registry() -> None:
    """Registering providers populates feature registry with ImplementationDescriptor entries."""
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    providers = all_descriptors()
    assert len(providers) >= 15

    implementations = feature_registry.all_implementations()

    for provider_id in providers:
        key = ("providers", provider_id)
        assert key in implementations, (
            f"Provider {provider_id} has no ImplementationDescriptor in feature registry"
        )


def test_provider_alias_map_matches_registry() -> None:
    """provider_alias_map returns entries for all registered providers."""
    from audiagentic.components.providers.descriptors.registry import (
        all_descriptors,
        provider_alias_map,
    )

    providers = all_descriptors()
    aliases = provider_alias_map()

    for provider_id in providers:
        assert provider_id in aliases, f"{provider_id} missing from alias map"
        assert aliases[provider_id] == provider_id


def test_canonical_provider_ids_matches_registry() -> None:
    """canonical_provider_ids returns the same set as all_descriptors."""
    from audiagentic.components.providers.descriptors.registry import (
        all_descriptors,
        canonical_provider_ids,
    )

    providers = all_descriptors()
    ids = canonical_provider_ids()

    assert set(ids) == set(providers)
    assert len(ids) == len(providers)
