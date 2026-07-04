"""Shared fixtures for foundation unit tests."""
from __future__ import annotations

import pytest

from audiagentic.foundation.features import registry


@pytest.fixture
def isolated_features_registry():
    """Run a test against an empty features registry, restoring prior state after.

    Tests that exercise feature/implementation loading need a clean registry,
    but a bare ``registry.clear()`` in teardown leaks an EMPTY registry to every
    later test (e.g. memory tests resolving the 'hindsight' implementation).
    Snapshot the module dicts, clear for the test, and restore on teardown.
    """
    snapshots = {
        name: dict(getattr(registry, name))
        for name in ("_features", "_impl_features", "_implementations", "_bindings", "_binding_writers")
    }
    registry.clear()
    yield
    registry.clear()
    for name, saved in snapshots.items():
        getattr(registry, name).update(saved)
