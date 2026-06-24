from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.io import load_yaml_file, save_yaml_file

from .base import FeatureState, ImplementationState

# Runtime state directory. State is sharded per component (parent) so a mutation
# to component A never rewrites component B's data (write-scope isolation).
RUNTIME_DIR = Path(".audiagentic") / "config" / "runtime"
SHARD_DIR = RUNTIME_DIR / "features"
# Legacy monolithic state file (pre-sharding). Kept only for back-compat reads
# and one-shot migration; mutations never write it.
LEGACY_FEATURE_STATE_PATH = RUNTIME_DIR / "features.yaml"
# Deprecated alias retained for back-compat with external callers/tests.
FEATURE_STATE_PATH = LEGACY_FEATURE_STATE_PATH


def runtime_dir(project_root: Path) -> Path:
    return project_root / RUNTIME_DIR


def shard_dir(project_root: Path) -> Path:
    return project_root / SHARD_DIR


def shard_path(project_root: Path, parent: str) -> Path:
    """Deterministic per-component shard path. No index file is used."""
    return shard_dir(project_root) / f"{parent}.yaml"


def legacy_feature_state_path(project_root: Path) -> Path:
    return project_root / LEGACY_FEATURE_STATE_PATH


# Deprecated: legacy path accessor retained for back-compat.
def feature_state_path(project_root: Path) -> Path:
    return legacy_feature_state_path(project_root)


def _load_legacy_state(project_root: Path) -> dict[str, Any]:
    path = legacy_feature_state_path(project_root)
    if not path.exists():
        return {}
    return load_yaml_file(path)


def load_feature_state(project_root: Path) -> dict[str, Any]:
    """Return the whole-document state assembled from all per-component shards.

    Back-compat helper. If shards exist, they are the source of truth; otherwise
    the legacy monolithic file (if present) is returned.
    """
    directory = shard_dir(project_root)
    if directory.exists():
        state: dict[str, Any] = {}
        for shard in sorted(directory.glob("*.yaml")):
            parent = shard.stem
            state[parent] = load_yaml_file(shard)
        if state:
            return state
    return _load_legacy_state(project_root)


def save_feature_state(project_root: Path, state: dict[str, Any]) -> None:
    """Write the whole-document state out as per-component shards.

    Back-compat helper (migration / bulk writes). Per-component mutations should
    use set_component_state, which writes only the affected shard.
    """
    for parent, component_state in state.items():
        save_yaml_file(
            shard_path(project_root, parent),
            component_state if isinstance(component_state, dict) else {},
            sort_keys=True,
            atomic=True,
        )


def get_component_state(project_root: Path, parent: str) -> dict[str, Any]:
    path = shard_path(project_root, parent)
    if path.exists():
        component_state = load_yaml_file(path)
    else:
        # Lazy read-migration: pull this parent's slice out of the legacy file.
        legacy = _load_legacy_state(project_root)
        component_state = legacy.get(parent) or {}
        if not isinstance(component_state, dict):
            return {}
        if component_state:
            migrate_component_state_to_flat(component_state)
            set_component_state(project_root, parent, component_state)
            return dict(component_state)
        return {}
    if not isinstance(component_state, dict):
        return {}
    if _needs_migration(component_state):
        migrate_component_state_to_flat(component_state)
        set_component_state(project_root, parent, component_state)
    return dict(component_state)


def set_component_state(project_root: Path, parent: str, component_state: dict[str, Any]) -> None:
    # Isolation: only the affected parent's shard is rewritten.
    save_yaml_file(
        shard_path(project_root, parent),
        component_state,
        sort_keys=True,
        atomic=True,
    )


def migrate_to_shards(project_root: Path) -> list[str]:
    """One-shot split of the legacy monolithic features.yaml into per-component shards.

    Each top-level key becomes ``features/{parent}.yaml`` (with nested->flat
    feature-key migration applied). The legacy file is renamed to
    ``features.yaml.migrated`` (never deleted) for rollback. Returns the list of
    parents migrated. No-op (returns []) if the legacy file is absent.
    """
    legacy_path = legacy_feature_state_path(project_root)
    if not legacy_path.exists():
        return []
    legacy = load_yaml_file(legacy_path)
    migrated: list[str] = []
    for parent, component_state in legacy.items():
        if not isinstance(component_state, dict):
            component_state = {}
        else:
            migrate_component_state_to_flat(component_state)
        set_component_state(project_root, parent, component_state)
        migrated.append(parent)
    legacy_path.rename(legacy_path.with_suffix(legacy_path.suffix + ".migrated"))
    return migrated


# ---------------------------------------------------------------------------
# Composite key helpers
# ---------------------------------------------------------------------------

def _needs_migration(component_state: dict[str, Any]) -> bool:
    """Check if component state needs migration from nested to flat format."""
    features = component_state.get("features")
    if isinstance(features, dict) and _is_nested_features_map(features):
        return True
    implementations = component_state.get("implementations")
    if isinstance(implementations, dict):
        for impl_data in implementations.values():
            if isinstance(impl_data, dict):
                impl_features = impl_data.get("features")
                if isinstance(impl_features, dict) and _is_nested_features_map(impl_features):
                    return True
    return False


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
# Migration: nested features -> flat composite keys
# ---------------------------------------------------------------------------

def _is_nested_features_map(features: dict[str, Any]) -> bool:
    """Check if features dict uses old nested format (kind -> id -> state)."""
    for value in features.values():
        if isinstance(value, dict):
            for inner_value in value.values():
                if isinstance(inner_value, dict) and ("enabled" in inner_value or "options" in inner_value):
                    return True
    return False


def _migrate_features_to_flat(features: dict[str, Any]) -> dict[str, Any]:
    """Migrate nested features map to flat composite key format.

    Before: { "language": { "python": { "enabled": true } } }
    After:  { "language:python": { "enabled": true } }
    """
    if not _is_nested_features_map(features):
        return features

    flat: dict[str, Any] = {}
    for kind, kind_map in features.items():
        if not isinstance(kind_map, dict):
            flat[kind] = kind_map
            continue
        for feature_id, feature_data in kind_map.items():
            composite = feature_composite_key(kind, feature_id)
            flat[composite] = feature_data
    return flat


def _migrate_component_features(component_state: dict[str, Any]) -> dict[str, Any]:
    """Migrate features in a component state dict to flat format."""
    if "features" not in component_state:
        return component_state
    features = component_state["features"]
    if isinstance(features, dict) and _is_nested_features_map(features):
        component_state["features"] = _migrate_features_to_flat(features)
    return component_state


def _migrate_implementation_features(component_state: dict[str, Any]) -> dict[str, Any]:
    """Migrate implementation-scoped features to flat format."""
    implementations = component_state.get("implementations")
    if not isinstance(implementations, dict):
        return component_state
    for impl_id, impl_data in implementations.items():
        if not isinstance(impl_data, dict):
            continue
        features = impl_data.get("features")
        if isinstance(features, dict) and _is_nested_features_map(features):
            impl_data["features"] = _migrate_features_to_flat(features)
    return component_state


def migrate_component_state_to_flat(component_state: dict[str, Any]) -> dict[str, Any]:
    """Migrate a component's state dict from nested to flat feature keys.

    Runs in-place and returns the mutated dict.
    """
    _migrate_component_features(component_state)
    _migrate_implementation_features(component_state)
    return component_state


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
