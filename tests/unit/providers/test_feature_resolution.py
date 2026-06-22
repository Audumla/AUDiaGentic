from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.services.feature_resolution import (
    resolve_active_provider_features,
)
from audiagentic.components.providers.services.provider_config import set_provider_enabled
from audiagentic.foundation.components.ids import COMPONENT_PROVIDERS
from audiagentic.foundation.features.base import FeatureState
from audiagentic.foundation.features.state import set_implementation_feature_state


def _kinds_for(resolved, provider_id: str) -> set[str]:
    return {r.kind for r in resolved if r.provider_id == provider_id}


def test_no_enabled_providers_resolves_nothing(tmp_path: Path) -> None:
    assert resolve_active_provider_features(tmp_path) == []


def test_enabled_provider_resolves_all_its_features(tmp_path: Path) -> None:
    set_provider_enabled(tmp_path, "claude", enabled=True)

    resolved = resolve_active_provider_features(tmp_path)
    kinds = _kinds_for(resolved, "claude")

    assert "mcp" in kinds
    assert "skills" in kinds
    assert "surface" in kinds
    # Every resolved feature carries its owning descriptor for the projection layer.
    assert all(r.descriptor.provider_id == r.provider_id for r in resolved)


def test_disabled_provider_contributes_nothing(tmp_path: Path) -> None:
    set_provider_enabled(tmp_path, "claude", enabled=True)
    set_provider_enabled(tmp_path, "claude", enabled=False)

    assert _kinds_for(resolve_active_provider_features(tmp_path), "claude") == set()


def test_explicitly_disabled_feature_excluded_siblings_remain(tmp_path: Path) -> None:
    set_provider_enabled(tmp_path, "claude", enabled=True)
    set_implementation_feature_state(
        tmp_path, COMPONENT_PROVIDERS, "claude", "mcp", "mcp", FeatureState(enabled=False)
    )

    kinds = _kinds_for(resolve_active_provider_features(tmp_path), "claude")
    assert "mcp" not in kinds
    assert "skills" in kinds  # sibling capability still active when provider enabled


def test_feature_active_by_default_when_provider_enabled(tmp_path: Path) -> None:
    # No per-feature state written: capabilities project because the provider is on.
    set_provider_enabled(tmp_path, "claude", enabled=True)
    resolved = resolve_active_provider_features(tmp_path)
    assert any(r.kind == "mcp" for r in resolved if r.provider_id == "claude")
