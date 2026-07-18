"""Typed callback and result contracts for managed-service coordination."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from audiagentic.foundation.system.managed_process import (
    DetachedLaunch,
    ProcessIdentity,
    launch_detached,
    observe_process,
    signal_owned_process,
)
from audiagentic.foundation.system.managed_service_contracts import (
    ClientLease,
    EndpointInfo,
    ManagedServiceRecord,
    ProcessEvidence,
    ServiceKey,
    validation_error,
)

StartDisposition = Literal["started", "attached", "recovered"]
StopOutcome = Literal[
    "stopped", "active-leases", "not-quiescent", "quiescence-unavailable",
    "ownership-unverified", "stop-timeout", "stop-failed",
]


@dataclass(frozen=True)
class ManagedServiceDeclaration:
    key: ServiceKey
    process: DetachedLaunch
    endpoint: EndpointInfo
    protocol_version: str
    readiness_timeout: float = 15.0
    readiness_poll_interval: float = 0.05

    def __post_init__(self) -> None:
        if not self.protocol_version:
            raise validation_error(12, "protocol version is required")
        if self.readiness_timeout <= 0 or self.readiness_poll_interval <= 0:
            raise validation_error(21, "readiness timing must be positive")


@dataclass(frozen=True)
class ServiceHandshake:
    ready: bool
    owner_epoch: str
    protocol_version: str
    endpoint: EndpointInfo
    health_facts: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ManagedServiceHooks:
    handshake: Callable[[ManagedServiceRecord], ServiceHandshake]
    quiescent: Callable[[ManagedServiceRecord], bool]
    request_stop: Callable[[ManagedServiceRecord], None]
    observe: Callable[[ProcessEvidence], ProcessIdentity | None] = observe_process
    launch: Callable[..., ProcessEvidence] = launch_detached
    signal: Callable[..., None] = signal_owned_process


@dataclass(frozen=True)
class StartOrAttachResult:
    record: ManagedServiceRecord
    lease: ClientLease
    disposition: StartDisposition


@dataclass(frozen=True)
class StopResult:
    record: ManagedServiceRecord
    outcome: StopOutcome
    forced: bool = False


__all__ = [
    "ManagedServiceDeclaration",
    "ManagedServiceHooks",
    "ServiceHandshake",
    "StartDisposition",
    "StartOrAttachResult",
    "StopOutcome",
    "StopResult",
]
