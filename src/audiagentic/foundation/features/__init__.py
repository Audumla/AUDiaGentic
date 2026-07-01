"""Component feature descriptors, state, and resolution helpers."""

from .base import (
    FEATURE_SCOPE_IMPLEMENTATION,
    FEATURE_SCOPE_SHARED,
    BindingDescriptor,
    ConfigurableDescriptor,
    FeatureDescriptor,
    FeatureState,
    ImplementationDescriptor,
    ImplementationState,
    LabeledDescriptor,
    OptionSchema,
    ResolvedFeatureConfig,
    ResolvedImplementationConfig,
)
from .config_status import (
    ConfigStatus,
    ImplementationConfigStatus,
    MissingOption,
    evaluate_config,
    implementation_config_status,
)

__all__ = [
    "FEATURE_SCOPE_IMPLEMENTATION",
    "FEATURE_SCOPE_SHARED",
    "BindingDescriptor",
    "ConfigStatus",
    "ConfigurableDescriptor",
    "FeatureDescriptor",
    "FeatureState",
    "ImplementationConfigStatus",
    "ImplementationDescriptor",
    "ImplementationState",
    "LabeledDescriptor",
    "MissingOption",
    "OptionSchema",
    "ResolvedFeatureConfig",
    "ResolvedImplementationConfig",
    "evaluate_config",
    "implementation_config_status",
]
