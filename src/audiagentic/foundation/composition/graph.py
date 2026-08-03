"""The built graph: immutable, root-addressable, finalized in reverse order.

There is deliberately no `get(service_id)`. A built graph is not a container to
ask questions of at runtime — it hands the composition root the instances it
declared as roots and nothing else. Services receive their dependencies through
their constructors and never see this object.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from audiagentic.foundation.composition.contracts import ServiceId

logger = logging.getLogger(__name__)


class BuiltGraph:
    """Constructed services, addressable only by configured root ID."""

    def __init__(
        self,
        *,
        roots: Mapping[ServiceId, Any],
        construction_order: Sequence[ServiceId],
        finalizers: Sequence[tuple[ServiceId, Callable[[], None]]],
    ) -> None:
        self._roots = dict(roots)
        self._construction_order = tuple(construction_order)
        self._finalizers = tuple(finalizers)
        self._shut_down = False

    @property
    def construction_order(self) -> tuple[ServiceId, ...]:
        """Order services were constructed in. Finalization is its reverse."""
        return self._construction_order

    def root(self, service_id: ServiceId) -> Any:
        """Return a configured root instance.

        Only the composition root calls this, and only for an ID it listed in
        `composition.roots`. It is not a general lookup: a service that was
        built as a dependency is not reachable through it.
        """
        if service_id not in self._roots:
            raise KeyError(
                f"{service_id!r} is not a configured composition root; "
                f"configured roots are {sorted(self._roots)}"
            )
        return self._roots[service_id]

    def shutdown(self) -> None:
        """Finalize in reverse construction order.

        A failing finalizer is logged and the remaining ones still run — a
        partial shutdown that abandons the rest would leak whatever the
        earlier-constructed services hold. Idempotent.
        """
        if self._shut_down:
            return
        self._shut_down = True
        for service_id, finalizer in reversed(self._finalizers):
            try:
                finalizer()
            except Exception:
                logger.exception(
                    "Composition finalizer failed", extra={"service_id": str(service_id)}
                )
