from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from audiagentic.foundation.invoke.base import InvocationRecipe


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

    install and uninstall are InvocationRecipe instances owned by the provider
    descriptor. lifecycle.py dispatches through them without knowing internals.

    Standard package managers use toolchain factories from
    foundation.invoke.toolchains (npm, uv, brew, gh_extension).

    Custom provisioners (e.g. pi-harness) use CallableRecipe to wrap their
    own install/uninstall logic.

    probe_fn is kept as a callable returning a structured availability dict
    because its semantics differ from install/uninstall (read-only, typed result).
    """
    package_manager: str        # metadata/display only
    package_name: str           # metadata/display only
    executable: str
    install: InvocationRecipe
    uninstall: InvocationRecipe
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
    # Optional: fetch live model list. Receives provider config dict; returns list
    # of model dicts conforming to provider-model-catalog schema (model-id, display-name,
    # status, supports-structured-output, context-window). None = not supported.
    fetch_catalog_fn: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None

    @property
    def install_mode(self) -> str:
        return "external-configured" if self.cli_install is not None else "unmanaged"
