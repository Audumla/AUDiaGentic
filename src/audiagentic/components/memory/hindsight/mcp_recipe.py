"""Hindsight MCP config recipe for provider harness targets.

This recipe writes the Hindsight MCP server entry into a provider's harness
config file. It is owned by the Hindsight memory implementation and uses generic
provider target data; memory core only exports backend config.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.toolchains.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.config_patcher import ConfigPatcher
from audiagentic.foundation.toolchains.probes import ConfigKeyCheck
from audiagentic.foundation.toolchains.provision_steps import (
    ConfigSetStep,
    ProvisionStep,
)
from audiagentic.foundation.toolchains.recipe_contract import (
    ProvisioningRecipe,
    RecipeResult,
    RecipeState,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HindsightTarget:
    """Provider harness destination for the MCP entry.

    ``config_path`` is the harness config file; ``container`` is the key path to
    the MCP-servers table within it (e.g. ``("mcpServers",)`` for most JSON
    configs, ``("servers",)`` for VS Code, ``("mcp_servers",)`` for some TOML).

    Provider-specific format callbacks (writer_fn, reader_fn, remover_fn from
    McpConfigSpec) override default ConfigPatcher for non-JSON formats.
    """

    config_path: str | Path
    container: tuple[str, ...] = ("mcpServers",)
    writer_fn: Any = None  # fmt: skip
    reader_fn: Any = None  # fmt: skip
    remover_fn: Any = None  # fmt: skip


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
        if backend.bank_id:
            entry.setdefault("env", {})["HINDSIGHT_BANK_ID"] = backend.bank_id
        return entry
    # sse / http transports point at the MCP endpoint (base URL + /mcp); the
    # bare base URL is the API root and does not speak MCP.
    entry = {"type": backend.transport, "url": backend.mcp_url}
    headers = backend.headers()  # includes Authorization and X-Bank-Id when set
    if headers:
        entry["headers"] = headers
    return entry


def build_hindsight_mcp_entry(backend: HindsightBackendConfig) -> McpServerEntry:
    """Build McpServerEntry directly from HindsightBackendConfig."""
    if backend.transport == "stdio":
        env = {}
        if backend.api_key:
            env["HINDSIGHT_API_KEY"] = backend.api_key
        if backend.bank_id:
            env["HINDSIGHT_BANK_ID"] = backend.bank_id
        return McpServerEntry(
            name=backend.server_name,
            command="hindsight-mcp",
            args=("--base-url", backend.base_url),
            env=env,
        )
    headers = backend.headers()
    return McpServerEntry(
        name=backend.server_name,
        url=backend.mcp_url,
        headers=headers if headers else {},
        transport=backend.transport,
    )


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

    def provision_steps(self) -> list[ProvisionStep]:
        """Return ProvisionSteps for JSON-based MCP config.

        ConfigSetStep uses ConfigPatcher for standard JSON writes; custom
        writer_fn/reader_fn callbacks are used during configure/probe for
        verification against the provider's native format.
        """
        return [
            ConfigSetStep(
                id=f"mcp-config-{self.backend.server_name}",
                path=str(self.target.config_path),
                key_path=self._key_path,
                value=self._desired_entry(),
                registry=self.registry,
                recipe_id=self.recipe_id,
            )
        ]

    def _desired_entry(self) -> dict[str, Any]:
        return self._entry_builder(self.backend)

    def _present_check(self) -> ConfigKeyCheck:
        return ConfigKeyCheck(
            self.target.config_path, self._key_path, expected_value=self._desired_entry()
        )

    def probe(self, context: dict[str, Any]) -> RecipeResult:
        if self.target.reader_fn is not None:
            try:
                entries = self.target.reader_fn(Path(self.target.config_path))
                desired = build_hindsight_mcp_entry(self.backend)
                present = entries.get(self.backend.server_name) == desired
            except Exception:
                logger.warning("probe reader failed for %s", self.target.config_path, exc_info=True)
                present = False
            return RecipeResult.ok(
                RecipeState.VERIFIED if present else RecipeState.ABSENT,
                status="entry present" if present else "entry absent",
            )
        present = self._present_check().check().passed
        return RecipeResult.ok(
            RecipeState.VERIFIED if present else RecipeState.ABSENT,
            status="entry present" if present else "entry absent",
        )

    def install(self, context: dict[str, Any]) -> RecipeResult:
        return RecipeResult.ok(RecipeState.INSTALLING, status="external backend")

    def configure(self, context: dict[str, Any]) -> RecipeResult:
        entry = self._desired_entry()
        if self.target.writer_fn is not None:
            existing = {}
            if self.target.reader_fn:
                try:
                    existing = self.target.reader_fn(Path(self.target.config_path))
                except Exception:
                    logger.warning("reader failed for %s", self.target.config_path, exc_info=True)
            existing[self.backend.server_name] = build_hindsight_mcp_entry(self.backend)
            self.target.writer_fn(Path(self.target.config_path), existing)
            return RecipeResult.ok(
                RecipeState.CONFIGURING,
                artifacts=[self._artifact_id()],
                status="entry written",
            )
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
        if self.target.reader_fn is not None:
            probed = self.probe(context)
            if probed.success and probed.state is RecipeState.VERIFIED:
                return RecipeResult.ok(
                    RecipeState.VERIFIED, artifacts=[self._artifact_id()]
                )
            return RecipeResult.fail(f"verify failed: {probed.status}")
        result = self._present_check().check()
        if result.passed:
            return RecipeResult.ok(
                RecipeState.VERIFIED, artifacts=[self._artifact_id()]
            )
        return RecipeResult.fail(f"verify failed: {result.detail}")

    def uninstall(self, context: dict[str, Any]) -> RecipeResult:
        return RecipeResult.ok(RecipeState.ABSENT, status="external backend")

    def prune(self, context: dict[str, Any]) -> RecipeResult:
        if self.target.remover_fn is not None:
            removed = self.target.remover_fn(Path(self.target.config_path), self.backend.server_name)
            if self.registry is not None:
                report = self.registry.prune(self.recipe_id)
                if not report.ok:
                    return RecipeResult.fail("; ".join(report.errors))
            return RecipeResult.ok(
                RecipeState.ABSENT,
                status="entry removed" if removed else "entry already absent",
            )
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
    "build_hindsight_mcp_entry",
]
