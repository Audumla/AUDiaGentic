"""Typed public contract for the MCP launch-surface family.

A "launch surface" is what MCP servers are visible to a provider's process for
ONE launch — as distinct from ``managed_mcp``, which durably reconciles a
provider's own config file. This family answers: "make this launch see only
these AUDiaGentic-curated servers," for whichever mechanism the provider
actually has (patched CLI flags, a per-process env var, a generated file —
provider-owned and invisible to callers).

Foundation-safe: imports only stdlib. Lives in ``providers/contracts`` because
the capability lives on the provider side — adapters declare/implement HOW to
build a launch surface; callers (the interactive harness launcher, the
gateway's isolated-agent-job dispatch) supply WHAT servers belong in it and
consume the result through ``providers_api``, never an adapter directly.

Callers own entry selection through ``foundation.mcp.projection``; a platform
component may not depend on runtime orchestration to compute it (architecture
§1 dependency boundaries).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

McpLaunchIsolationTier = Literal["exact", "additive", "unsupported"]


@dataclass(frozen=True)
class McpLaunchServerEntry:
    """One AUDiaGentic-curated MCP server to include in the launch surface."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.command:
            raise ValueError("name and command are required")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> McpLaunchServerEntry:
        return cls(
            name=str(value["name"]),
            command=str(value["command"]),
            args=tuple(str(item) for item in value.get("args", ())),
            env=tuple(sorted((str(k), str(v)) for k, v in dict(value.get("env", {})).items())),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {"name": self.name, "command": self.command, "args": list(self.args), "env": dict(self.env)}


@dataclass(frozen=True)
class McpLaunchSurfaceRequest:
    """What should be visible — the provider decides only how to deliver it."""

    project_root: str
    runtime_root: str | None = None
    entries: tuple[McpLaunchServerEntry, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        names = [entry.name for entry in self.entries]
        if len(names) != len(set(names)):
            raise ValueError("launch surface entry names must be unique")


@dataclass(frozen=True)
class McpLaunchSurfaceResult:
    """What a provider's launch-surface builder actually produced.

    ``applied_isolation`` reports the outcome of this materialization attempt.
    The provider's inherent support is declared separately by
    ``ProviderDescriptor.mcp_launch_isolation_tier``.
    """

    ok: bool
    supported: bool
    applied_isolation: McpLaunchIsolationTier = "unsupported"
    mechanism: str = ""
    extra_args: tuple[str, ...] = ()
    extra_env: tuple[tuple[str, str], ...] = ()

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "supported": self.supported,
            "applied_isolation": self.applied_isolation,
            "mechanism": self.mechanism,
            "extra_args": list(self.extra_args),
            "extra_env": dict(self.extra_env),
        }


__all__ = [
    "McpLaunchIsolationTier",
    "McpLaunchServerEntry",
    "McpLaunchSurfaceRequest",
    "McpLaunchSurfaceResult",
]
