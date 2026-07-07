"""Shared fixtures for foundation unit tests."""
from __future__ import annotations

import pytest

from audiagentic.foundation.features import registry as features_registry


@pytest.fixture(autouse=True)
def _reset_foundation_state():
    """Reset all foundation-level registries and logging between each test.

    Foundation tests exercise the loader, registries, and cache guard directly,
    so they need full reset to avoid cross-test pollution (e.g. profile-component
    descriptors from one test leaking into a base-only test).  The root conftest
    handles cache invalidation; this fixture handles registry clearing.
    """
    from audiagentic.foundation.components import registry as components_registry
    from audiagentic.foundation.logging.config import reset_logging_for_test
    from audiagentic.foundation.registry_utils import reset_all_registries

    reset_all_registries()
    components_registry.reset()
    features_registry.clear()
    reset_logging_for_test()


@pytest.fixture
def isolated_features_registry():
    """Run a test against an empty features registry, restoring prior state after.

    Tests that exercise feature/implementation loading need a clean registry,
    but a bare ``registry.clear()`` in teardown leaks an EMPTY registry to every
    later test (e.g. memory tests resolving the 'hindsight' implementation).
    Snapshot the module dicts, clear for the test, and restore on teardown.
    """
    snapshots = {
        name: dict(getattr(features_registry, name))
        for name in ("_features", "_impl_features", "_implementations", "_bindings", "_binding_writers")
    }
    features_registry.clear()
    yield
    features_registry.clear()
    for name, saved in snapshots.items():
        getattr(features_registry, name).update(saved)
