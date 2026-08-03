"""Minimal config-driven composition: contributions in, immutable graph out.

Deliberately absent, per AS59's non-negotiable rules: decorators, reflection
auto-wiring, a runtime `get()`, mutable registration, child containers and
task/session scopes. Services stay plain Python and receive dependencies
through their constructors.
"""

from audiagentic.foundation.composition.builder import build_graph
from audiagentic.foundation.composition.config import (
    CONFIG_NAMESPACE,
    CompositionConfig,
    load_composition_config,
    parse_composition_config,
)
from audiagentic.foundation.composition.contracts import (
    ImplementationId,
    ServiceContribution,
    ServiceId,
)
from audiagentic.foundation.composition.graph import BuiltGraph

__all__ = [
    "CONFIG_NAMESPACE",
    "BuiltGraph",
    "CompositionConfig",
    "ImplementationId",
    "ServiceContribution",
    "ServiceId",
    "build_graph",
    "load_composition_config",
    "parse_composition_config",
]
