from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .base import FeatureState, ImplementationState
from .observations import (
    clear_observation,
    get_observation,
    observed_keys,
    record_observation,
)

# Component options and feature switches are the ``features`` section of the settings, written into
# the user-project scope (one person's untracked choices for one project); a tracked project file
# may carry shared defaults. An implementation's ``enabled`` flag is lifecycle state, not configuration:
# it is what enable, disable and reconciliation applied on this host, kept in the observation store and
# merged back into the component view below. ``providers.<id>.enabled`` in settings is the separate,
# user-owned override that wins over it.
SECTION = "features"
WRITE_SCOPE = "user-project"
ENABLED_PREFIX = "enabled:"


def get_component_state(project_root: Path, parent: str) -> dict[str, Any]:
    state: dict[str, Any] = {}
    if project_root.is_dir():
        from audiagentic.foundation.config.settings import resolve_settings_cached

        section = resolve_settings_cached(project_root).get(SECTION)
        entry = section.get(parent) if isinstance(section, dict) else None
        state = deepcopy(entry) if isinstance(entry, dict) else {}
    for key in observed_keys(project_root, parent, ENABLED_PREFIX):
        implementation = key[len(ENABLED_PREFIX):]
        entry = state.setdefault("implementations", {}).setdefault(implementation, {})
        if isinstance(entry, dict):
            entry["enabled"] = bool(get_observation(project_root, parent, key))
    return state


def set_component_state(project_root: Path, parent: str, component_state: dict[str, Any]) -> None:
    """Replace one component's state; each implementation's ``enabled`` goes to the observation store."""
    from audiagentic.foundation.config.writer import replace_at

    settings_part = deepcopy(component_state)
    enabled: dict[str, bool] = {}
    for implementation, entry in (settings_part.get("implementations") or {}).items():
        if isinstance(entry, dict) and "enabled" in entry:
            enabled[implementation] = bool(entry.pop("enabled"))
    settings_part["implementations"] = {k: v for k, v in (settings_part.get("implementations") or {}).items() if v}
    if not settings_part["implementations"]:
        del settings_part["implementations"]
    replace_at(WRITE_SCOPE, (SECTION, parent), settings_part, project_root=project_root)
    for key in observed_keys(project_root, parent, ENABLED_PREFIX):
        if key[len(ENABLED_PREFIX):] not in enabled:
            clear_observation(project_root, parent, key)
    for implementation, value in enabled.items():
        key = ENABLED_PREFIX + implementation
        if get_observation(project_root, parent, key) is not value:
            record_observation(project_root, parent, key, value, source="feature-state")


# ---------------------------------------------------------------------------
# Composite key helpers
# ---------------------------------------------------------------------------


def feature_composite_key(kind: str, feature_id: str) -> str:
    """Build a flat composite key for a feature."""
    return f"{kind}:{feature_id}"


def parse_feature_composite_key(key: str) -> tuple[str, str] | None:
    """Parse a composite key into (kind, feature_id), or None if invalid."""
    if ":" not in key:
        return None
    kind, feature_id = key.split(":", 1)
    if not kind or not feature_id:
        return None
    return kind, feature_id


# ---------------------------------------------------------------------------
# Feature state access (flat composite key format)
# ---------------------------------------------------------------------------


def get_feature_state(project_root: Path, parent: str, kind: str, feature_id: str) -> FeatureState:
    component = get_component_state(project_root, parent)
    features = component.get("features") or {}
    composite = feature_composite_key(kind, feature_id)
    feature_data = features.get(composite, {})
    if not isinstance(feature_data, dict):
        return FeatureState()
    options = feature_data.get("options") or {}
    return FeatureState(
        enabled=bool(feature_data.get("enabled", False)),
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
    composite = feature_composite_key(kind, feature_id)
    features[composite] = {
        "enabled": feature_state.enabled,
        "options": dict(feature_state.options),
    }
    set_component_state(project_root, parent, component)


# ---------------------------------------------------------------------------
# Implementation state access
# ---------------------------------------------------------------------------


def get_implementation_state(
    project_root: Path, parent: str, implementation_id: str
) -> ImplementationState:
    component = get_component_state(project_root, parent)
    implementation_data = (component.get("implementations") or {}).get(implementation_id, {})
    if not isinstance(implementation_data, dict):
        return ImplementationState()
    options = implementation_data.get("options") or {}
    return ImplementationState(
        enabled=bool(implementation_data.get("enabled", False)),
        options=dict(options) if isinstance(options, dict) else {},
    )


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
    if isinstance(existing, dict) and isinstance(existing.get("features"), dict):
        entry["features"] = existing["features"]
    implementations[implementation_id] = entry
    set_component_state(project_root, parent, component)


def remove_implementation_state(project_root: Path, parent: str, implementation_id: str) -> bool:
    """Remove one implementation's project state, returning whether it existed."""
    component = get_component_state(project_root, parent)
    implementations = component.get("implementations")
    if not isinstance(implementations, dict) or implementation_id not in implementations:
        return False
    del implementations[implementation_id]
    if implementations:
        component["implementations"] = implementations
    else:
        component.pop("implementations", None)
    set_component_state(project_root, parent, component)
    return True


# ---------------------------------------------------------------------------
# Implementation-scoped feature state (flat composite key format)
# ---------------------------------------------------------------------------


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
    features = implementation_data.get("features") or {}
    composite = feature_composite_key(kind, feature_id)
    feature_data = features.get(composite, {})
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
    features = implementation_data.get("features") or {}
    composite = feature_composite_key(kind, feature_id)
    feature_data = features.get(composite)
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
    composite = feature_composite_key(kind, feature_id)
    features[composite] = {
        "enabled": feature_state.enabled,
        "options": dict(feature_state.options),
    }
    set_component_state(project_root, parent, component)
