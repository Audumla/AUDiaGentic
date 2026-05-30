from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.workflow.invocation.steps import CallableStep, SequenceStep, ShellStep


@dataclass(frozen=True)
class McpConfigSpec:
    """Declares how a provider reads/writes its MCP server config.

    reader/writer/remover are supplied by each adapter — they own their format.
    format is informational only (display, tests, logging).
    """
    config_path: str | Callable[[], Path]
    reader: Callable[[Path], dict[str, McpServerEntry]]
    writer: Callable[[Path, dict[str, McpServerEntry]], None]
    remover: Callable[[Path, str], bool]
    refresh_mode: str  # "file-watch" | "restart-required"
    format: str = ""   # informational label
    reload_fn: Callable[[Path], dict[str, Any]] | None = None


@dataclass(frozen=True)
class VsCodeExtension:
    extension_id: str
    display_name: str


@dataclass(frozen=True)
class AgentFile:
    """A project file owned or written by a provider surface."""
    rel_path: str           # relative to project root
    managed: bool = True    # AUDiaGentic generates/updates this file
    description: str = ""


@dataclass(frozen=True)
class ProviderPermissions:
    """Inherent capability model of a provider (what it *can* do, not policy)."""
    can_write_files: bool = False
    can_execute_shell: bool = False
    can_browse_web: bool = False
    can_read_env: bool = False
    notes: str = ""


@dataclass(frozen=True)
class CliInstallRecipe:
    """How AUDiaGentic can provision a provider CLI.

    Standard package managers use toolchain factories from
    foundation.toolchains (npm, uv, brew, gh_extension).

    Custom provisioners (e.g. pi-harness) use CallableStep.

    probe_fn is kept as a callable returning a structured availability dict
    because its semantics differ from install/uninstall (read-only, typed result).
    """
    package_manager: str        # metadata/display only
    package_name: str           # metadata/display only
    executable: str
    install: ShellStep | SequenceStep | CallableStep
    uninstall: ShellStep | SequenceStep | CallableStep
    uninstall_name: str | None = None
    probe_fn: Callable[[Any], dict[str, Any] | None] | None = None


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    description: str = ""
    url: str = ""
    cli_probe: list[str] | None = None
    cli_install: CliInstallRecipe | None = None
    vscode_extensions: tuple[VsCodeExtension, ...] = field(default_factory=tuple)
    permissions: ProviderPermissions = field(default_factory=ProviderPermissions)
    agent_files: tuple[AgentFile, ...] = field(default_factory=tuple)
    # access-mode written to providers.yaml when this provider is first enabled.
    # "cli"  — invoked as a subprocess CLI tool
    # "env"  — accessed via environment / API key (no local binary)
    # "none" — passthrough bridge, no direct provider access
    access_mode: str = "cli"
    # Path template for skill surface files, e.g. ".claude/skills/{tag}/SKILL.md".
    # None means this provider has no skill file concept (contributions go to AGENTS.md etc.).
    skill_surface_path: str | None = None
    # Relative path of the provider's managed instruction file in the project root,
    # e.g. "CLAUDE.md". None means no instruction file is rendered for this provider.
    instruction_file: str | None = None
    # Optional: fetch live model list. Receives provider config dict; returns list
    # of model dicts conforming to provider-model-catalog schema (model-id, display-name,
    # status, supports-structured-output, context-window). None = not supported.
    fetch_catalog_fn: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None
    # MCP server config spec — None means this provider has no manageable MCP config.
    mcp_config: McpConfigSpec | None = None

    @property
    def install_mode(self) -> str:
        return "external-configured" if self.cli_install is not None else "unmanaged"
