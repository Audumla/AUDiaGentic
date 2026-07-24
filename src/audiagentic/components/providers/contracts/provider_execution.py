"""Typed public contract for one-shot provider execution."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from audiagentic.foundation.contracts.errors import AudiaGenticError

ProviderIsolationTier = Literal[
    "full-isolation",
    "partial-isolation",
    "no-isolation",
]

_ISOLATION_TIERS = frozenset(
    {"full-isolation", "partial-isolation", "no-isolation"}
)


@dataclass(frozen=True)
class ProviderExecutionRequest:
    """One provider turn resolved to one isolated worker attempt.

    ``packet_data`` is runtime-only provider-neutral input.  It may contain the
    raw prompt and therefore must never be persisted by the provider API.
    Identity-bearing packet fields are replaced from the typed fields before
    provider dispatch.
    """

    project_root: Path
    provider_id: str
    model_id: str | None
    model_alias: str | None
    packet_data: Mapping[str, Any] = field(default_factory=dict)
    worker_id: str = ""
    attempt_epoch: int = 0
    provider_isolation_tier: ProviderIsolationTier = "no-isolation"

    def __post_init__(self) -> None:
        root = Path(self.project_root)
        if not root.is_absolute():
            raise AudiaGenticError(
                code="VAL-PEXE-001",
                kind="providers",
                message="provider execution project root must be absolute",
                details={"project-root": str(root)},
            )
        if not self.provider_id or not self.worker_id or self.attempt_epoch < 1:
            raise AudiaGenticError(
                code="VAL-PEXE-002",
                kind="providers",
                message="provider execution attempt identity is incomplete",
                details={
                    "provider-id": self.provider_id,
                    "worker-id": self.worker_id,
                    "attempt-epoch": self.attempt_epoch,
                },
            )
        if not self.model_id and not self.model_alias:
            raise AudiaGenticError(
                code="VAL-MODEL-002",
                kind="providers",
                message="model-id or model-alias is required",
                details={"provider-id": self.provider_id},
            )
        if self.provider_isolation_tier not in _ISOLATION_TIERS:
            raise AudiaGenticError(
                code="VAL-PEXE-003",
                kind="providers",
                message="provider execution isolation tier is invalid",
                details={"provider-isolation-tier": self.provider_isolation_tier},
            )
        if not isinstance(self.packet_data, Mapping):
            raise AudiaGenticError(
                code="VAL-PEXE-004",
                kind="providers",
                message="provider execution packet data must be a mapping",
                details={"type": type(self.packet_data).__name__},
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ProviderExecutionRequest:
        packet_data = value.get("packet-data", {})
        return cls(
            project_root=Path(str(value.get("project-root", ""))),
            provider_id=str(value.get("provider-id", "")),
            model_id=(str(value["model-id"]) if value.get("model-id") else None),
            model_alias=(
                str(value["model-alias"]) if value.get("model-alias") else None
            ),
            packet_data=(
                dict(packet_data) if isinstance(packet_data, Mapping) else packet_data
            ),
            worker_id=str(value.get("worker-id", "")),
            attempt_epoch=int(value.get("attempt-epoch", 0)),
            provider_isolation_tier=str(
                value.get("provider-isolation-tier", "")
            ),  # type: ignore[arg-type]
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "project-root": str(self.project_root),
            "provider-id": self.provider_id,
            "model-id": self.model_id,
            "model-alias": self.model_alias,
            "packet-data": dict(self.packet_data),
            "worker-id": self.worker_id,
            "attempt-epoch": self.attempt_epoch,
            "provider-isolation-tier": self.provider_isolation_tier,
        }


@dataclass(frozen=True)
class ProviderExecutionResult:
    """Normalized result from one provider worker attempt."""

    provider_id: str
    model_id: str
    worker_id: str
    attempt_epoch: int
    result_data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not self.provider_id
            or not self.model_id
            or not self.worker_id
            or self.attempt_epoch < 1
        ):
            raise AudiaGenticError(
                code="VAL-PEXE-002",
                kind="providers",
                message="provider execution result identity is incomplete",
                details={
                    "provider-id": self.provider_id,
                    "model-id": self.model_id,
                    "worker-id": self.worker_id,
                    "attempt-epoch": self.attempt_epoch,
                },
            )
        if not isinstance(self.result_data, Mapping):
            raise AudiaGenticError(
                code="VAL-PEXE-005",
                kind="providers",
                message="provider execution result data must be a mapping",
                details={"type": type(self.result_data).__name__},
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ProviderExecutionResult:
        result_data = value.get("result-data", {})
        if not isinstance(result_data, Mapping):
            raise AudiaGenticError(
                code="VAL-PEXE-005",
                kind="providers",
                message="provider execution result data must be a mapping",
                details={"type": type(result_data).__name__},
            )
        return cls(
            provider_id=str(value.get("provider-id", "")),
            model_id=str(value.get("model-id", "")),
            worker_id=str(value.get("worker-id", "")),
            attempt_epoch=int(value.get("attempt-epoch", 0)),
            result_data=dict(result_data),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "provider-id": self.provider_id,
            "model-id": self.model_id,
            "worker-id": self.worker_id,
            "attempt-epoch": self.attempt_epoch,
            "result-data": dict(self.result_data),
        }


@dataclass(frozen=True)
class ProviderAcpLaunchResult:
    """Provider-owned ACP launch declaration for agents session transport.

    ``launch`` is a :class:`~audiagentic.foundation.transports.ProviderLaunch`
    (aliased ``AcpLaunch`` in the ACP subsystem). Typed ``Any`` here to avoid a
    contract->foundation import at this layer; the transport validates the
    concrete type.
    """

    provider_id: str
    model_id: str
    launch: Any = field(repr=False)


__all__ = [
    "ProviderExecutionRequest",
    "ProviderExecutionResult",
    "ProviderAcpLaunchResult",
    "ProviderIsolationTier",
]
