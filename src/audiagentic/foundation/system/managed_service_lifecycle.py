"""Public facade for managed-service start, attach, drain, and shutdown."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ManagedServiceRecord
from audiagentic.foundation.system.managed_service_lifecycle_contracts import (
    ManagedServiceDeclaration,
    ManagedServiceHooks,
    ServiceHandshake,
    StartOrAttachResult,
    StopResult,
)
from audiagentic.foundation.system.managed_service_shutdown import ManagedServiceShutdown
from audiagentic.foundation.system.managed_service_start import ManagedServiceStarter


class ManagedServiceLifecycle:
    """Small composition facade over cohesive start and shutdown coordinators."""

    def __init__(self, store: ManagedServiceStore, hooks: ManagedServiceHooks) -> None:
        self._starter = ManagedServiceStarter(store, hooks)
        self._shutdown = ManagedServiceShutdown(store, hooks)

    def start_or_attach(
        self,
        declaration: ManagedServiceDeclaration,
        *,
        client_instance_id: str,
        lease_ttl_seconds: float,
        correlation_id: str | None = None,
        lease_facts: Mapping[str, Any] | None = None,
    ) -> StartOrAttachResult:
        return self._starter.start_or_attach(
            declaration,
            client_instance_id=client_instance_id,
            lease_ttl_seconds=lease_ttl_seconds,
            correlation_id=correlation_id,
            lease_facts=lease_facts,
        )

    def request_drain(
        self, *, expected_revision: int, expected_epoch: str
    ) -> ManagedServiceRecord:
        return self._shutdown.request_drain(
            expected_revision=expected_revision, expected_epoch=expected_epoch
        )

    def stop_if_quiescent(
        self,
        *,
        expected_epoch: str,
        graceful_timeout: float = 5.0,
        force_timeout: float = 2.0,
    ) -> StopResult:
        return self._shutdown.stop_if_quiescent(
            expected_epoch=expected_epoch,
            graceful_timeout=graceful_timeout,
            force_timeout=force_timeout,
        )


__all__ = [
    "ManagedServiceDeclaration",
    "ManagedServiceHooks",
    "ManagedServiceLifecycle",
    "ServiceHandshake",
    "StartOrAttachResult",
    "StopResult",
]
