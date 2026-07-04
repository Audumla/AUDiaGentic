"""Generic capability registry for cross-layer contribution.

Foundation and runtime modules can register callable capabilities that are
resolved at consumption time.  This eliminates lazy imports of specific
optional components from foundational layers (Standard 1).

Registered capability keys:
    providers.surface-validator — validates contribution config references
        (providers surfaces observer, effect-only; returns None or logs warnings)
    providers.mcp-projector — sync_component_mcp_to_providers(component_id,
        project_root, enabled=True) → None
    providers.provider-config.resolve_enabled — resolve_provider_enabled(
        project_root, provider_id) → bool
    providers.descriptors.all_ids — all_descriptors() → dict (provider registry)
    harness.runtime-sync — build_runtime_sync(reason=..., component_id=...,
        target=..., has_mcp_servers=...) → dict (runtime/harness)
    harness.config-refresh — refresh_harness_config_if_installed(project_root,
        reason=..., component_id=...) → bool (runtime/harness)

Registration semantics:
    * Idempotent on same function object (re-import safety).
    * Raises VAL-CAP-001 if a key is re-registered with a different callable.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from audiagentic.foundation.contracts.errors import make_error

_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_capability(key: str, fn: Callable[..., Any]) -> None:
    """Register a callable under +key+.

    Idempotent when the same function object is re-registered (re-import safety).
    Raises ``VAL-CAP-001`` when a different callable is registered for an
    existing key — early imports must not silently win.
    """
    existing = _REGISTRY.get(key)
    if existing is not None:
        if existing is fn:
            return
        raise make_error(
            prefix="VAL",
            component="CAP",
            number=1,
            kind="capabilities",
            message=f"capability key {key!r} already registered with a different callable",
            details={"key": key},
        )
    _REGISTRY[key] = fn


def get_capability(key: str) -> Callable[..., Any] | None:
    """Return the registered callable for +key+, or ``None`` if absent."""
    return _REGISTRY.get(key)
