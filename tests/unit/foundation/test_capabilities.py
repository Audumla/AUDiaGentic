"""Tests for foundation/capabilities.py — generic capability registry (AR02)."""
from __future__ import annotations

import pytest

from audiagentic.foundation.capabilities import get_capability, register_capability
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def clean_registry():
    """Ensure clean registry state for tests that need it.

    Note: not autouse — clearing the global registry can break other tests
    that depend on lifecycle observer import-time registration (module cache).
    After teardown, restores only entries that existed before the test, preserving
    any capabilities registered by other modules during this fixture's scope.
    """
    from audiagentic.foundation.capabilities import _REGISTRY

    saved = dict(_REGISTRY)
    _REGISTRY.clear()
    yield
    # On teardown: restore saved entries, but DON'T delete keys added by others.
    for k, v in saved.items():
        _REGISTRY[k] = v


def test_register_and_get(clean_registry):
    def fn():
        return 42

    register_capability("test.fn", fn)
    resolved = get_capability("test.fn")
    assert resolved is fn
    assert resolved() == 42


def test_get_missing_returns_none():
    assert get_capability("nonexistent.key_" + id(None).__str__()) is None


def test_register_same_fn_idempotent(clean_registry):
    """Re-registering the same callable is a no-op (re-import safety)."""
    def fn():
        return 1

    register_capability("test.idem", fn)
    register_capability("test.idem", fn)  # should not raise
    assert get_capability("test.idem") is fn


def test_register_different_fn_raises_val_cap_001(clean_registry):
    """Re-registering with a different callable raises VAL-CAP-001."""
    def fn_a():
        return "a"

    def fn_b():
        return "b"

    register_capability("test.duplicate", fn_a)

    with pytest.raises(AudiaGenticError, match="VAL-CAP-001"):
        register_capability("test.duplicate", fn_b)


def test_providers_absent_noop(clean_registry):
    """When providers absent (capability not registered), consumer gets None."""
    validate_ref = get_capability("providers.surface-validator")
    assert validate_ref is None


def test_bootstrap_order_validation_then_contributions():
    """Verify that contribution validation uses capability registry and no-ops when absent."""
    from audiagentic.foundation.components.loader import (
        _validate_descriptors_contributions,
    )

    # Contributions validation never raises — it either calls the validator or no-ops.
    _validate_descriptors_contributions([])  # empty list is safe regardless of registry state

    # With providers installed, the real validator should be registered after bootstrap.
    validate_ref = get_capability("providers.surface-validator")
    if validate_ref is None:
        pytest.skip("providers observer not yet imported (test ordering dependency)")

    # Verify it's callable with expected signature.
    warning = validate_ref("some/path.yaml", "test-comp")
    # The real validator returns None or a warning string — either is valid.
    assert isinstance(warning, (str, type(None)))


def test_capability_registry_keys_documented():
    """Module docstring lists registered capability keys."""
    import audiagentic.foundation.capabilities as cap_mod

    doc = cap_mod.__doc__ or ""
    expected_keys = [
        "providers.surface-validator",
        "providers.mcp-projector",
        "providers.provider-config.resolve_enabled",
        "providers.descriptors.all_ids",
    ]
    for key in expected_keys:
        assert key in doc, f"Capability key {key!r} not documented in module docstring"
