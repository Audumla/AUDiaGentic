from __future__ import annotations

from pathlib import Path

from .base import (
    FeatureDescriptor,
    ImplementationDescriptor,
    ResolvedFeatureConfig,
    ResolvedImplementationConfig,
)
from .options import resolve_options_with_provenance
from .state import get_component_state, get_feature_state, get_implementation_state


def resolve_feature(project_root: Path, descriptor: FeatureDescriptor) -> ResolvedFeatureConfig:
    component_state = get_component_state(project_root, descriptor.parent)
    component_options = dict(component_state.get("options") or {})
    applicable_component_options = {
        key: value
        for key, value in component_options.items()
        if key in descriptor.options_schema
    }
    feature_state = get_feature_state(
        project_root,
        descriptor.parent,
        descriptor.kind,
        descriptor.feature_id,
    )
    effective_options, option_provenance = resolve_options_with_provenance(
        descriptor.options_schema,
        applicable_component_options,
        feature_state.options,
        layer_names=["component-state", "feature-state"],
    )
    return ResolvedFeatureConfig(
        descriptor=descriptor,
        state=feature_state,
        component_options=component_options,
        feature_options=dict(feature_state.options),
        effective_options=effective_options,
        option_provenance=option_provenance,
    )


def resolve_implementation(
    project_root: Path,
    descriptor: ImplementationDescriptor,
) -> ResolvedImplementationConfig:
    component_state = get_component_state(project_root, descriptor.parent)
    component_options = dict(component_state.get("options") or {})
    applicable_component_options = {
        key: value
        for key, value in component_options.items()
        if key in descriptor.options_schema
    }
    implementation_state = get_implementation_state(
        project_root,
        descriptor.parent,
        descriptor.implementation_id,
    )
    effective_options, option_provenance = resolve_options_with_provenance(
        descriptor.options_schema,
        applicable_component_options,
        implementation_state.options,
        layer_names=["component-state", "implementation-state"],
    )
    return ResolvedImplementationConfig(
        descriptor=descriptor,
        state=implementation_state,
        component_options=component_options,
        implementation_options=dict(implementation_state.options),
        effective_options=effective_options,
        option_provenance=option_provenance,
    )
