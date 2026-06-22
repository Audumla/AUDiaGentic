from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

FEATURE_SCOPE_SHARED = "shared"
FEATURE_SCOPE_IMPLEMENTATION = "implementation"
IMPLEMENTATION_CARDINALITY_EXCLUSIVE = "exclusive"
IMPLEMENTATION_CARDINALITY_MULTI = "multi"


class DescriptorType(str, Enum):
    FEATURE = "feature"
    IMPLEMENTATION = "implementation"
    BINDING = "binding"

    @classmethod
    def from_string(cls, value: str) -> "DescriptorType":
        try:
            return cls(value)
        except ValueError:
            raise ValueError(
                f"Unknown descriptor type '{value}'. "
                f"Supported: feature, implementation, binding"
            ) from None


@dataclass(frozen=True)
class OptionSchema:
    option_type: str
    default: Any = None
    values: tuple[Any, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None
    allow_unknown: bool = False


@dataclass(frozen=True, kw_only=True)
class ConfigurableDescriptor:
    """Base for the feature-layer descriptor family (feature/implementation/binding).

    Every member is parented to a component, may carry a typed options schema, and
    retains its raw YAML mapping. Subclasses add identity and domain fields and
    each defines its own registry `key`.
    """
    parent: str
    options_schema: dict[str, OptionSchema] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class LabeledDescriptor(ConfigurableDescriptor):
    """A configurable descriptor that is a user-selectable unit with its own
    presentation and declared dependency set — features and implementations.

    Bindings are excluded on purpose: they are derived, carry no presentation,
    and *reference* dependencies (`uses_dependencies`) rather than declaring them.
    """
    display_name: str = ""
    description: str = ""
    dependencies: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class FeatureDescriptor(LabeledDescriptor):
    kind: str
    feature_id: str
    scope: str = FEATURE_SCOPE_SHARED
    implementation: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.parent, self.kind, self.feature_id)


@dataclass(frozen=True, kw_only=True)
class ImplementationDescriptor(LabeledDescriptor):
    implementation_id: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.parent, self.implementation_id)


@dataclass(frozen=True, kw_only=True)
class BindingDescriptor(ConfigurableDescriptor):
    implementation: str
    feature: str
    feature_kind: str
    uses_dependencies: tuple[str, ...] = ()
    projection_writer_key: str = ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.parent, self.implementation, self.feature_kind, self.feature)


@dataclass(frozen=True)
class FeatureState:
    enabled: bool = False
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedFeatureConfig:
    descriptor: FeatureDescriptor
    state: FeatureState
    component_options: dict[str, Any]
    feature_options: dict[str, Any]
    effective_options: dict[str, Any]


@dataclass(frozen=True)
class ImplementationState:
    enabled: bool = False
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedImplementationConfig:
    descriptor: ImplementationDescriptor
    state: ImplementationState
    component_options: dict[str, Any]
    implementation_options: dict[str, Any]
    effective_options: dict[str, Any]
