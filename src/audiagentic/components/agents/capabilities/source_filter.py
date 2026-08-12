"""Pre-reservation execution-instance compatibility filtering."""
from __future__ import annotations

from collections.abc import Callable, Iterable


def eligible_instance_ids(instances: Iterable[str], *, compatible: Callable[[str], bool] | None = None) -> tuple[str, ...]:
    predicate = compatible or (lambda _instance: True)
    return tuple(instance for instance in instances if predicate(instance))
