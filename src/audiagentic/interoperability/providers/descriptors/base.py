from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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

    For standard package managers (npm, brew, gh-extension, uv-tool) the
    lifecycle module synthesises commands from package_manager + package_name.

    For custom provisioners (e.g. pi-harness) set the optional callable hooks
    instead — lifecycle.py dispatches through them without knowing the details:
      install_fn(project_root: Path | None) -> subprocess.CompletedProcess
      uninstall_fn(project_root: Path | None) -> subprocess.CompletedProcess
      probe_fn(descriptor: ProviderDescriptor) -> dict[str, Any] | None
    """
    package_manager: str
    package_name: str
    executable: str
    uninstall_name: str | None = None
    install_command: tuple[str, ...] = ()
    uninstall_command: tuple[str, ...] = ()
    install_fn: Callable[[Path | None], subprocess.CompletedProcess[str]] | None = None
    uninstall_fn: Callable[[Path | None], subprocess.CompletedProcess[str]] | None = None
    probe_fn: Callable[[Any], dict[str, Any] | None] | None = None


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    cli_probe: list[str] | None = None
    cli_install: CliInstallRecipe | None = None
    vscode_extensions: tuple[VsCodeExtension, ...] = field(default_factory=tuple)
    permissions: ProviderPermissions = field(default_factory=ProviderPermissions)
    agent_files: tuple[AgentFile, ...] = field(default_factory=tuple)
