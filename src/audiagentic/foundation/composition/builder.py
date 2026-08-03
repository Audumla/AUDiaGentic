"""Build a `BuiltGraph` from contributions plus configured bindings.

Resolution happens once, here, at build time. Nothing in this module is
reachable after the graph is built, and no service is handed the builder.

Only the part of the graph reachable from configured roots is constructed. An
unreachable binding is dead configuration, not a live dependency — this is what
stops the binding map from silently accumulating edges nobody uses.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from audiagentic.foundation.composition.config import CompositionConfig
from audiagentic.foundation.composition.contracts import (
    ImplementationId,
    ServiceContribution,
    ServiceId,
    composition_error,
    composition_state_error,
)
from audiagentic.foundation.composition.graph import BuiltGraph


def _index_contributions(
    contributions: Iterable[ServiceContribution],
) -> dict[ServiceId, dict[ImplementationId, ServiceContribution]]:
    index: dict[ServiceId, dict[ImplementationId, ServiceContribution]] = {}
    for contribution in contributions:
        by_implementation = index.setdefault(contribution.service_id, {})
        existing = by_implementation.get(contribution.implementation_id)
        if existing is not None:
            raise composition_error(
                5,
                f"Duplicate composition contribution: implementation "
                f"{contribution.implementation_id!r} is contributed twice for service "
                f"{contribution.service_id!r}.",
                service_id=str(contribution.service_id),
                implementation_id=str(contribution.implementation_id),
            )
        by_implementation[contribution.implementation_id] = contribution
    return index


def _validate_bindings(
    config: CompositionConfig,
    index: Mapping[ServiceId, Mapping[ImplementationId, ServiceContribution]],
) -> None:
    """Reject bindings naming things no code contributes.

    Checked across the whole binding map rather than only the reachable subset,
    so a typo in an unused binding is still reported instead of lying dormant
    until the day that service becomes reachable.
    """
    for service_id, implementation_id in config.bindings.items():
        by_implementation = index.get(service_id)
        if by_implementation is None:
            raise composition_error(
                3,
                f"Composition binding names unknown service {service_id!r}. "
                f"Known services: {sorted(str(s) for s in index)}.",
                service_id=str(service_id),
                known_services=sorted(str(s) for s in index),
            )
        if implementation_id not in by_implementation:
            raise composition_error(
                4,
                f"Composition binding for service {service_id!r} names unknown implementation "
                f"{implementation_id!r}. Known implementations: "
                f"{sorted(str(i) for i in by_implementation)}.",
                service_id=str(service_id),
                implementation_id=str(implementation_id),
                known_implementations=sorted(str(i) for i in by_implementation),
            )


def _select(
    service_id: ServiceId,
    config: CompositionConfig,
    index: Mapping[ServiceId, Mapping[ImplementationId, ServiceContribution]],
    requested_by: ServiceId | None,
) -> ServiceContribution:
    """Resolve one service to its bound contribution.

    There is no implicit default when a service has exactly one implementation.
    Configuration stays authoritative: if the graph needs a service, the config
    says which implementation, or the build fails.
    """
    implementation_id = config.bindings.get(service_id)
    if implementation_id is None:
        origin = (
            f" (required by {requested_by!r})" if requested_by is not None else " (a configured root)"
        )
        raise composition_error(
            6,
            f"No composition binding for service {service_id!r}{origin}. "
            f"Add it under composition.bindings.",
            service_id=str(service_id),
            required_by=str(requested_by) if requested_by is not None else None,
        )
    # _validate_bindings already proved both IDs resolve.
    return index[service_id][implementation_id]


def build_graph(
    contributions: Iterable[ServiceContribution],
    config: CompositionConfig,
    *,
    overrides: Mapping[ServiceId, Any] | None = None,
) -> BuiltGraph:
    """Construct the graph reachable from `config.roots`.

    `overrides` substitutes an already-constructed instance for a service at
    build time. It exists so tests can swap a dependency without reaching into
    module state; the substituted service's own dependencies are not built.
    """
    index = _index_contributions(contributions)
    _validate_bindings(config, index)

    substitutes = dict(overrides or {})
    instances: dict[ServiceId, Any] = {}
    construction_order: list[ServiceId] = []
    finalizers: list[tuple[ServiceId, Callable[[], None]]] = []
    # Path (not just a set) so a cycle can be reported in the order it forms.
    in_progress: list[ServiceId] = []

    def construct(service_id: ServiceId, requested_by: ServiceId | None) -> Any:
        if service_id in instances:
            return instances[service_id]
        if service_id in substitutes:
            instance = substitutes[service_id]
            instances[service_id] = instance
            construction_order.append(service_id)
            return instance
        if service_id in in_progress:
            cycle = [*in_progress[in_progress.index(service_id) :], service_id]
            raise composition_state_error(
                1,
                "Composition dependency cycle: " + " -> ".join(str(s) for s in cycle),
                cycle=[str(s) for s in cycle],
            )

        contribution = _select(service_id, config, index, requested_by)
        in_progress.append(service_id)
        try:
            kwargs = {
                parameter: construct(dependency, service_id)
                for parameter, dependency in contribution.requires.items()
            }
            instance = contribution.factory(**kwargs)
        finally:
            in_progress.pop()

        instances[service_id] = instance
        construction_order.append(service_id)
        if contribution.finalizer is not None:
            finalizer = contribution.finalizer
            finalizers.append((service_id, lambda inst=instance, fn=finalizer: fn(inst)))
        return instance

    roots = {root_id: construct(root_id, None) for root_id in config.roots}
    return BuiltGraph(
        roots=roots,
        construction_order=tuple(construction_order),
        finalizers=tuple(finalizers),
    )
