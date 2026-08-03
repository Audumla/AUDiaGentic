"""Typed composition identifiers and the service contribution record.

Domain-neutral by construction: nothing here knows what a service *is*. The
composition root supplies contributions; this module only describes their shape.

`ServiceId` and `ImplementationId` are distinct `NewType`s over `str` so that a
binding map keyed by the wrong one is a type error rather than a build-time
surprise — the two are structurally identical and trivially confusable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, NewType

from audiagentic.foundation.contracts.errors import make_error_factory

ServiceId = NewType("ServiceId", str)
ImplementationId = NewType("ImplementationId", str)

composition_error = make_error_factory("VAL", "COMPOSE", "composition")
composition_state_error = make_error_factory("CON", "COMPOSE", "composition")


@dataclass(frozen=True)
class ServiceContribution:
    """One implementation a service may be bound to.

    `requires` maps the factory's keyword parameter name to the service ID that
    supplies it. Keying by parameter name (rather than a flat list of service
    IDs) is what lets the builder call the factory with keywords, so a service
    can depend on two different services of the same shape.
    """

    service_id: ServiceId
    implementation_id: ImplementationId
    factory: Callable[..., Any]
    requires: Mapping[str, ServiceId] = field(default_factory=dict)
    # Explicit rather than discovered: the builder does not go looking for a
    # `close()`/`__exit__` on the instance. A service that needs releasing says
    # so here, and receives its own instance.
    finalizer: Callable[[Any], None] | None = None

    def __post_init__(self) -> None:
        if not self.service_id or not self.service_id.strip():
            raise composition_error(7, "Service contribution requires a non-empty service-id.")
        if not self.implementation_id or not self.implementation_id.strip():
            raise composition_error(
                7,
                "Service contribution requires a non-empty implementation-id.",
                service_id=self.service_id,
            )
        if not callable(self.factory):
            raise composition_error(
                7,
                "Service contribution factory must be callable.",
                service_id=self.service_id,
                implementation_id=self.implementation_id,
            )
        object.__setattr__(self, "requires", dict(self.requires or {}))
