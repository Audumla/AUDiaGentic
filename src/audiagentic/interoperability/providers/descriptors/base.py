from __future__ import annotations

from dataclasses import dataclass, field


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
    """How AUDiaGentic can provision a provider CLI."""
    package_manager: str
    package_name: str
    executable: str
    uninstall_name: str | None = None
    install_command: tuple[str, ...] = ()
    uninstall_command: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    cli_probe: list[str] | None = None
    cli_install: CliInstallRecipe | None = None
    vscode_extensions: tuple[VsCodeExtension, ...] = field(default_factory=tuple)
    permissions: ProviderPermissions = field(default_factory=ProviderPermissions)
    agent_files: tuple[AgentFile, ...] = field(default_factory=tuple)
