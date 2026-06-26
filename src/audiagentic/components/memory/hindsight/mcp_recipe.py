"""Hindsight MCP config recipe for provider harness targets.

This recipe writes the Hindsight MCP server entry into a provider's harness
config file. It is owned by the Hindsight memory implementation and uses generic
provider target data; memory core only exports backend config.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight_export import HindsightBackendConfig
from audiagentic.foundation.toolchains.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.config_patcher import ConfigPatcher
from audiagentic.foundation.toolchains.probes import ConfigKeyCheck
from audiagentic.foundation.toolchains.recipe_contract import (
    ProvisioningRecipe,
    RecipeResult,
    RecipeState,
)


@dataclass(frozen=True)
class HindsightTarget:
    """Provider harness destination for the MCP entry.

    ``config_path`` is the harness config file; ``container`` is the key path to
    the MCP-servers table within it (e.g. ``("mcpServers",)`` for most JSON
    configs, ``("servers",)`` for VS Code, ``("mcp_servers",)`` for some TOML).
    """

    config_path: str | Path
    container: tuple[str, ...] = ("mcpServers",)


def build_hindsight_entry(backend: HindsightBackendConfig) -> dict[str, Any]:
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
        backend: HindsightBackendConfig,
        target: HindsightTarget,
        *,
        registry: ArtifactRegistry | None = None,
        recipe_id: str | None = None,
        entry_builder: Callable[[HindsightBackendConfig], dict[str, Any]] = build_hindsight_entry,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.target = target
        self.registry = registry
        self.recipe_id = recipe_id or f"hindsight:{Path(target.config_path).as_posix()}"
        self._entry_builder = entry_builder

    @property
    def _key_path(self) -> tuple[str, ...]:
        return (*self.target.container, self.backend.server_name)

    def _desired_entry(self) -> dict[str, Any]:
        return self._entry_builder(self.backend)

    def _present_check(self) -> ConfigKeyCheck:
        return ConfigKeyCheck(
            self.target.config_path, self._key_path, expected_value=self._desired_entry()
        )

    def probe(self, context: dict[str, Any]) -> RecipeResult:
        present = self._present_check().check().passed
        return RecipeResult.ok(
            RecipeState.VERIFIED if present else RecipeState.ABSENT,
            status="entry present" if present else "entry absent",
        )

    def install(self, context: dict[str, Any]) -> RecipeResult:
        return RecipeResult.ok(RecipeState.INSTALLING, status="external backend")

    def configure(self, context: dict[str, Any]) -> RecipeResult:
        entry = self._desired_entry()
        patcher = ConfigPatcher(self.target.config_path)
        change = patcher.set_key((*self.target.container, self.backend.server_name), entry)
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
        change = ConfigPatcher(self.target.config_path).remove_key(
            (*self.target.container, self.backend.server_name)
        )
        return RecipeResult.ok(
            RecipeState.ABSENT,
            status="entry removed" if change.existed else "entry already absent",
        )

    def _artifact_id(self) -> str:
        return f"{Path(self.target.config_path).as_posix()}::{'.'.join(self._key_path)}"


__all__ = [
    "HindsightMcpRecipe",
    "HindsightTarget",
    "build_hindsight_entry",
]
