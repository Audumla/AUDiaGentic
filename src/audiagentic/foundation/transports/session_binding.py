"""Neutral provider session binding value objects.

Provider session refs are opaque protected data. Core gateway code may store
and compare them, but must not parse, display, log, or use them as paths.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BindingRelation(StrEnum):
    OPENED = "opened"
    ATTACHED = "attached"
    RESUMED_FROM = "resumed-from"
    REPLACED = "replaced"


class SessionOwnership(StrEnum):
    OWNED = "owned"
    EXTERNAL = "external"
    ADOPTED = "adopted"


@dataclass(frozen=True)
class ProviderSessionRef:
    """Opaque protected ref. Never appears in repr/str/logs — access .value
    only at the storage or provider-surface boundary."""

    value: str = field(repr=False)

    def __repr__(self) -> str:
        return "ProviderSessionRef(<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True)
class SessionBindingIntent:
    ag_session_id: str
    generation: int
    relation: BindingRelation
    ownership: SessionOwnership
    prior_binding_id: str | None = None
