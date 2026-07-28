"""Enabled-aware projection contract.

Locks in the unified Stage 3 behaviour every provider projection (MCP, surfaces,
skills, language-servers) depends on: capability activity is driven solely by
`resolve_active_provider_features`, gated on provider enablement, with optional
per-capability override. This is the regression guard that lets the projection
writers trust the resolver as their single active-set source.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.services.config.feature_resolution import (
    enabled_provider_ids,
    resolve_active_provider_features,
)
from audiagentic.components.providers.services.config.provider_config import set_provider_enabled
from audiagentic.foundation.features.base import FeatureState
from audiagentic.foundation.features.state import set_implementation_feature_state

# codex exposes all four capability kinds.
_PROVIDER = "codex"
_ALL_KINDS = {"mcp", "surface", "skills", "lsp-support"}


def _active_kinds(project_root: Path, provider_id: str) -> set[str]:
    return {
        resolved.kind
        for resolved in resolve_active_provider_features(project_root)
        if resolved.provider_id == provider_id
    }


def test_enabled_provider_projects_all_capabilities(tmp_path: Path) -> None:
    set_provider_enabled(tmp_path, _PROVIDER, enabled=True)
    assert _active_kinds(tmp_path, _PROVIDER) == _ALL_KINDS
    assert _PROVIDER in enabled_provider_ids(tmp_path)


def test_disabled_provider_projects_nothing(tmp_path: Path) -> None:
    set_provider_enabled(tmp_path, _PROVIDER, enabled=True)
    set_provider_enabled(tmp_path, _PROVIDER, enabled=False)
    assert _active_kinds(tmp_path, _PROVIDER) == set()
    assert _PROVIDER not in enabled_provider_ids(tmp_path)


def test_per_capability_disable_drops_only_that_capability(tmp_path: Path) -> None:
    set_provider_enabled(tmp_path, _PROVIDER, enabled=True)
    # Explicitly disable just the MCP capability of an otherwise-enabled provider.
    set_implementation_feature_state(
        tmp_path, "providers", _PROVIDER, "mcp", "mcp", FeatureState(enabled=False)
    )

    kinds = _active_kinds(tmp_path, _PROVIDER)
    assert "mcp" not in kinds
    assert kinds == _ALL_KINDS - {"mcp"}
    # The provider itself is still enabled — only one capability was suppressed.
    assert _PROVIDER in enabled_provider_ids(tmp_path)


def test_enabled_provider_ids_independent_of_capability_overrides(tmp_path: Path) -> None:
    # Even with every capability explicitly disabled, the provider stays "enabled"
    # at the implementation level (enabled_provider_ids gates LSP provisioning hooks).
    set_provider_enabled(tmp_path, _PROVIDER, enabled=True)
    for kind in _ALL_KINDS:
        feature_id = "mcp" if kind == "mcp" else kind  # surface uses path ids; keep simple kinds
        if kind in {"mcp", "skills", "lsp-support"}:
            set_implementation_feature_state(
                tmp_path, "providers", _PROVIDER, kind, feature_id, FeatureState(enabled=False)
            )
    assert _PROVIDER in enabled_provider_ids(tmp_path)
