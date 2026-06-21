from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.io import load_yaml_file, save_yaml_file

from .base import FeatureState, ImplementationState

FEATURE_STATE_PATH = Path(".audiagentic") / "config" / "runtime" / "features.yaml"


def feature_state_path(project_root: Path) -> Path:
    return project_root / FEATURE_STATE_PATH


def load_feature_state(project_root: Path) -> dict[str, Any]:
    path = feature_state_path(project_root)
    if not path.exists():
        return {}
    return load_yaml_file(path)


def save_feature_state(project_root: Path, state: dict[str, Any]) -> None:
    save_yaml_file(feature_state_path(project_root), state, sort_keys=True, atomic=True)


def get_component_state(project_root: Path, parent: str) -> dict[str, Any]:
    return dict(load_feature_state(project_root).get(parent) or {})


def set_component_state(project_root: Path, parent: str, component_state: dict[str, Any]) -> None:
    state = load_feature_state(project_root)
    state[parent] = component_state
    save_feature_state(project_root, state)


def get_feature_state(project_root: Path, parent: str, kind: str, feature_id: str) -> FeatureState:
    component = get_component_state(project_root, parent)
    feature_data = (
        (component.get("features") or {})
        .get(kind, {})
        .get(feature_id, {})
    )
    if not isinstance(feature_data, dict):
        return FeatureState()
    options = feature_data.get("options") or {}
    return FeatureState(
        enabled=bool(feature_data.get("enabled", False)),
        options=dict(options) if isinstance(options, dict) else {},
    )


def get_implementation_state(project_root: Path, parent: str, implementation_id: str) -> ImplementationState:
    component = get_component_state(project_root, parent)
    implementation_data = (component.get("implementations") or {}).get(implementation_id, {})
    if not isinstance(implementation_data, dict):
        return ImplementationState()
    options = implementation_data.get("options") or {}
    return ImplementationState(
        enabled=bool(implementation_data.get("enabled", False)),
        options=dict(options) if isinstance(options, dict) else {},
    )


def set_feature_state(
    project_root: Path,
    parent: str,
    kind: str,
    feature_id: str,
    feature_state: FeatureState,
) -> None:
    component = get_component_state(project_root, parent)
    features = component.setdefault("features", {})
    kind_map = features.setdefault(kind, {})
    kind_map[feature_id] = {
        "enabled": feature_state.enabled,
        "options": dict(feature_state.options),
    }
    set_component_state(project_root, parent, component)


def set_implementation_state(
    project_root: Path,
    parent: str,
    implementation_id: str,
    implementation_state: ImplementationState,
) -> None:
    component = get_component_state(project_root, parent)
    implementations = component.setdefault("implementations", {})
    existing = implementations.get(implementation_id)
    entry: dict[str, Any] = {
        "enabled": implementation_state.enabled,
        "options": dict(implementation_state.options),
    }
    # Preserve implementation-scoped feature state, which nests under the implementation.
    if isinstance(existing, dict) and isinstance(existing.get("features"), dict):
        entry["features"] = existing["features"]
    implementations[implementation_id] = entry
    set_component_state(project_root, parent, component)


def get_implementation_feature_state(
    project_root: Path,
    parent: str,
    implementation_id: str,
    kind: str,
    feature_id: str,
) -> FeatureState:
    component = get_component_state(project_root, parent)
    implementation_data = (component.get("implementations") or {}).get(implementation_id, {})
    if not isinstance(implementation_data, dict):
        return FeatureState()
    feature_data = (
        (implementation_data.get("features") or {})
        .get(kind, {})
        .get(feature_id, {})
    )
    if not isinstance(feature_data, dict):
        return FeatureState()
    options = feature_data.get("options") or {}
    return FeatureState(
        enabled=bool(feature_data.get("enabled", False)),
        options=dict(options) if isinstance(options, dict) else {},
    )


def get_implementation_feature_enabled_explicit(
    project_root: Path,
    parent: str,
    implementation_id: str,
    kind: str,
    feature_id: str,
) -> bool | None:
    """Return the stored enabled flag, or None if no state has ever been written.

    Distinguishes "explicitly disabled" (False) from "never configured" (None) so
    callers can apply a default (e.g. active-when-implementation-enabled) only in
    the unconfigured case.
    """
    component = get_component_state(project_root, parent)
    implementation_data = (component.get("implementations") or {}).get(implementation_id, {})
    if not isinstance(implementation_data, dict):
        return None
    feature_data = (implementation_data.get("features") or {}).get(kind, {}).get(feature_id)
    if not isinstance(feature_data, dict) or "enabled" not in feature_data:
        return None
    return bool(feature_data["enabled"])


def set_implementation_feature_state(
    project_root: Path,
    parent: str,
    implementation_id: str,
    kind: str,
    feature_id: str,
    feature_state: FeatureState,
) -> None:
    component = get_component_state(project_root, parent)
    implementations = component.setdefault("implementations", {})
    implementation_data = implementations.setdefault(implementation_id, {})
    if not isinstance(implementation_data, dict):
        implementation_data = {}
        implementations[implementation_id] = implementation_data
    features = implementation_data.setdefault("features", {})
    kind_map = features.setdefault(kind, {})
    kind_map[feature_id] = {
        "enabled": feature_state.enabled,
        "options": dict(feature_state.options),
    }
    set_component_state(project_root, parent, component)
