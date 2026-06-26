"""Hindsight memory backend expressed as a provisioning recipe (TO08).

Implements the *mcp-config* integration strategy: register the Hindsight MCP
server into a harness's config file so the agent can reach long-term memory.

Ownership boundary (HI03): the memory component owns only the provider-agnostic
backend config (:class:`HindsightBackend` — base URL, transport, auth). *Where*
the entry is written is a provider-owned concern, injected as a
:class:`HindsightTarget`. The recipe therefore names no providers and hardcodes
no paths; provider-specific variations are expressed by the target and an
optional ``entry_builder`` override, satisfying the generic contract (RV08).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.foundation.toolchains.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.config_patcher import ConfigPatcher
from audiagentic.foundation.toolchains.probes import ConfigKeyCheck
from audiagentic.foundation.toolchains.recipe_contract import (
    ProvisioningRecipe,
    RecipeResult,
    RecipeState,
)


@dataclass(frozen=True)
class HindsightBackend:
    """Provider-agnostic Hindsight backend identity exported by the memory component."""

    base_url: str
    transport: str = "sse"  # "sse" | "stdio"
    api_key: str | None = None
    timeout_seconds: int = 30
    server_name: str = "hindsight"


@dataclass(frozen=True)
class HindsightTarget:
    """Provider-owned destination for the MCP entry.

    ``config_path`` is the harness config file; ``container`` is the key path to
    the MCP-servers table within it (e.g. ``("mcpServers",)`` for most JSON
    configs, ``("servers",)`` for VS Code, ``("mcp_servers",)`` for some TOML).
    """

    config_path: str | Path
    container: tuple[str, ...] = ("mcpServers",)


def build_hindsight_entry(backend: HindsightBackend) -> dict[str, Any]:
    """Default MCP entry for a Hindsight backend, keyed by transport.

    Override via ``HindsightMcpRecipe(entry_builder=...)`` for harnesses whose
    MCP entry schema differs.
    """
    if backend.transport == "stdio":
        args = ["--base-url", backend.base_url]
        entry: dict[str, Any] = {"command": "hindsight-mcp", "args": args}
        if backend.api_key:
            entry["env"] = {"HINDSIGHT_API_KEY": backend.api_key}
        return entry
    # sse / http transports point straight at the backend URL.
    entry = {"type": backend.transport, "url": backend.base_url}
    if backend.api_key:
        entry["headers"] = {"Authorization": f"Bearer {backend.api_key}"}
    return entry


class HindsightMcpRecipe(ProvisioningRecipe):
    """Install/verify/remove the Hindsight MCP entry in one harness config file."""

    def __init__(
        self,
        backend: HindsightBackend,
        target: HindsightTarget,
        *,
        registry: ArtifactRegistry | None = None,
        recipe_id: str | None = None,
        entry_builder: Callable[[HindsightBackend], dict[str, Any]] = build_hindsight_entry,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.target = target
        self.registry = registry
        self.recipe_id = recipe_id or f"memory:hindsight:{Path(target.config_path).as_posix()}"
        self._entry_builder = entry_builder

    @property
    def _key_path(self) -> tuple[str, ...]:
        return (*self.target.container, self.backend.server_name)

    def _desired_entry(self) -> dict[str, Any]:
        return self._entry_builder(self.backend)

    def _present_check(self) -> ConfigKeyCheck:
        # Match the full entry, not just key existence: a present-but-stale entry
        # (e.g. an old base URL) must read as absent so provision reconfigures it.
        return ConfigKeyCheck(
            self.target.config_path, self._key_path, expected_value=self._desired_entry()
        )

    # --- lifecycle -----------------------------------------------------------

    def probe(self, context: dict[str, Any]) -> RecipeResult:
        present = self._present_check().check().passed
        return RecipeResult.ok(
            RecipeState.VERIFIED if present else RecipeState.ABSENT,
            status="entry present" if present else "entry absent",
        )

    def install(self, context: dict[str, Any]) -> RecipeResult:
        # mcp-config is pure configuration: the backend runs externally, so there
        # is nothing to acquire here. Configure does the work.
        return RecipeResult.ok(RecipeState.INSTALLING, status="external backend")

    def configure(self, context: dict[str, Any]) -> RecipeResult:
        entry = self._desired_entry()
        change = ConfigPatcher(self.target.config_path).add_mcp_entry(
            self.backend.server_name, entry, container=self.target.container
        )
        if self.registry is not None:
            self.registry.register(self.recipe_id, changes=[change])
        return RecipeResult.ok(
            RecipeState.CONFIGURING,
            artifacts=[change.artifact_id],
            status="entry written",
        )

    def verify(self, context: dict[str, Any]) -> RecipeResult:
        result = self._present_check().check()
        if result.passed:
            return RecipeResult.ok(
                RecipeState.VERIFIED, artifacts=[self._artifact_id()]
            )
        return RecipeResult.fail(f"verify failed: {result.detail}")

    def uninstall(self, context: dict[str, Any]) -> RecipeResult:
        return RecipeResult.ok(RecipeState.ABSENT, status="external backend")

    def prune(self, context: dict[str, Any]) -> RecipeResult:
        if self.registry is not None:
            report = self.registry.prune(self.recipe_id)
            if not report.ok:
                return RecipeResult.fail("; ".join(report.errors))
            return RecipeResult.ok(
                RecipeState.ABSENT, status=f"removed {len(report.removed_keys)} entries"
            )
        # No registry: remove the entry directly.
        change = ConfigPatcher(self.target.config_path).remove_mcp_entry(
            self.backend.server_name, container=self.target.container
        )
        return RecipeResult.ok(
            RecipeState.ABSENT,
            status="entry removed" if change.existed else "entry already absent",
        )

    def _artifact_id(self) -> str:
        return f"{Path(self.target.config_path).as_posix()}::{'.'.join(self._key_path)}"


__all__ = [
    "HindsightBackend",
    "HindsightMcpRecipe",
    "HindsightTarget",
    "build_hindsight_entry",
]
