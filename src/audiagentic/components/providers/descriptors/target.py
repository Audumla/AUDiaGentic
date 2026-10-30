"""A provider instance: one descriptor plus a named option overlay.

``providers.<id>.instances.<name>`` in settings overlays a provider's options,
so one descriptor can serve several targets (for example two accounts or
projects of the same service). Operational state that must stay separate per
target (sessions, queue, evidence) is keyed on :attr:`ProviderTarget.key`;
descriptor, adapter and policy lookups use :attr:`ProviderTarget.provider_id`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from audiagentic.foundation.contracts.errors import make_error_factory

INSTANCE_SEPARATOR = "@"
INSTANCE_NAME_PATTERN = r"[a-z0-9][a-z0-9_-]{0,31}"
_NAME = re.compile(INSTANCE_NAME_PATTERN + r"\Z")

provider_config_error = make_error_factory("VAL", "PCFG", "providers")


@dataclass(frozen=True)
class ProviderTarget:
    provider_id: str
    instance: str | None = None

    @classmethod
    def parse(cls, key: str) -> ProviderTarget:
        provider_id, separator, instance = key.partition(INSTANCE_SEPARATOR)
        if not separator:
            return cls(provider_id)
        if not _NAME.match(instance):
            raise provider_config_error(5, "Invalid provider instance name", provider=provider_id, instance=instance)
        return cls(provider_id, instance)

    @property
    def key(self) -> str:
        return self.provider_id if self.instance is None else f"{self.provider_id}{INSTANCE_SEPARATOR}{self.instance}"


def base_provider_id(key: str) -> str:
    """The descriptor id behind a provider key (``gpt-auto@t1`` -> ``gpt-auto``)."""
    return key.partition(INSTANCE_SEPARATOR)[0]
