from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.components.coding_lsp.language_servers import LanguageServerEntry
from audiagentic.foundation.mcp import McpServerEntry
from audiagentic.foundation.workflow.invocation.steps import CallableStep, SequenceStep, ShellStep


@dataclass(frozen=True)
class McpConfigSpec:
    """Declares how a provider reads/writes its MCP server config.

    reader/writer/remover are supplied by each adapter — they own their format.
    format is informational only (display, tests, logging).
    """
    config_path: str | Callable[[Path | None], Path]
    reader: Callable[[Path], dict[str, McpServerEntry]]
    writer: Callable[[Path, dict[str, McpServerEntry]], None]
    remover: Callable[[Path, str], bool]
    refresh_mode: str  # "file-watch" | "restart-required"
    format: str = ""   # informational label
    reload_fn: Callable[[Path], dict[str, Any]] | None = None


@dataclass(frozen=True)
class LanguageServersConfigSpec:
    """Declares how a provider reads/writes its language server config.

    reader/writer/remover are supplied by each adapter — they own their format.
    writer upserts managed languages (preserving unmanaged entries); remover
    deletes one managed language (also preserving unmanaged). format is
    informational only (display, tests, logging).
    """
    config_path: str | Callable[[Path | None], Path]
    reader: Callable[[Path], dict[str, LanguageServerEntry]]
    writer: Callable[[Path, dict[str, LanguageServerEntry]], None]
    remover: Callable[[Path, str], bool]
    format: str = ""   # informational label


@dataclass(frozen=True)
class HostCapability:
    host: str
    capability_id: str
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

    Use cli_recipe() for standard toolchain installs (npm, uv, brew, vscode).
    Custom provisioners (e.g. pi-harness, raw shell scripts) pass steps directly.

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


def cli_recipe(
    toolchain: str,
    package: str,
    *extra: str,
    executable: str,
    uninstall_package: str | None = None,
    **kwargs: Any,
) -> CliInstallRecipe:
    """Build a CliInstallRecipe from a toolchain name and package, without importing toolchains."""
    from audiagentic.foundation.toolchains.loader import build_step, has_action
    un_pkg = uninstall_package or package
    un_action = "uninstall" if has_action(toolchain, "uninstall") else "remove"
    return CliInstallRecipe(
        package_manager=toolchain,
        package_name=package,
        executable=executable,
        install=build_step(toolchain, "install", package, *extra),
        uninstall=build_step(toolchain, un_action, un_pkg),
        **kwargs,
    )


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    description: str = ""
    url: str = ""
    prompt_aliases: tuple[str, ...] = field(default_factory=tuple)
    cli_probe: list[str] | None = None
    cli_install: CliInstallRecipe | None = None
    host_capabilities: tuple[HostCapability, ...] = field(default_factory=tuple)
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
    # Language server config spec — None means this provider doesn't accept LSP config sync.
    language_servers_config: LanguageServersConfigSpec | None = None
    # Optional hook fired when the coding-lsp component is enabled. Lets a provider
    # provision its own LSP support (e.g. pi installs the pi-lens extension, which
    # auto-discovers language servers from PATH). When set, the provider is treated
    # as self-providing LSP and is excluded from the generic ag-lsp MCP projection.
    # Receives project_root; returns a result dict.
    on_lsp_enabled: Callable[[Path | None], dict[str, Any]] | None = None
    # Controls whether this provider receives the ag-lsp MCP server from the
    # coding-lsp component. When True (default), the provider gets the MCP server
    # regardless of whether it has its own LSP implementation. Set to False to
    # opt-out of receiving the ag-lsp MCP.
    receive_lsp_mcp: bool = True
    # Declarative execution pipeline (AR12). When present and no hand-written
    # adapter.py exists, adapters/base_runner.py builds the runner from this
    # block (mode: cli | stub | ok-stub | unsupported; see base_runner docstring
    # for the full schema). Custom adapter modules always win.
    execution: dict[str, Any] | None = None
    # Declarative surface rendering (AR03). When present, a standard renderer is
    # registered for this provider from the descriptor alone — no surface.py.
    # Keys: renderer ("flat-skill" renders per-skill files + the instruction
    # file; "none" renders no skill surfaces), contribution-file (single-file
    # contribution target, e.g. "GEMINI.md" or "AGENTS.md"),
    # launch-example-template (default "@{tag}-{provider_id}").
    # Adapters with custom rendering keep a surface.py, which wins over this.
    surfaces: dict[str, Any] | None = None

    def host_extensions(self, host_id: str) -> tuple[HostCapability, ...]:
        """Capabilities declared for one editor host."""
        return tuple(
            capability
            for capability in self.host_capabilities
            if capability.host == host_id
        )

    @property
    def install_mode(self) -> str:
        return "external-configured" if self.cli_install is not None else "unmanaged"
