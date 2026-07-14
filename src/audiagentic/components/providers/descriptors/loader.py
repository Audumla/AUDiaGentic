"""Provider descriptor YAML loader.

Builds ``ProviderDescriptor`` instances from YAML files under
``config/providers/``. Uses the DescriptorSpec mechanism from ``spec.py``:
    load YAML → resolve dotpath hooks → build step tree → construct typed descriptor

The PROVIDER_SPEC declares the field map for ProviderDescriptor.
Hindsight-specific fields are NOT part of this spec — they belong to
``config/components/memory/hindsight_matrix.yaml``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.paths.names import get_package_providers_config_dir
from audiagentic.foundation.refs import resolve_ref
from audiagentic.foundation.toolchains.managed_config import (
    REMOTE_CAPABILITY,
    ManagedConfigSpec,
)
from audiagentic.foundation.workflow.invocation.from_spec import build_step_from_spec

from .base import (
    AgentFile,
    CliInstallRecipe,
    HostCapability,
    ProviderDescriptor,
    ProviderPermissions,
)
from .spec import DescriptorSpec, iter_descriptor_files, load_descriptor


def _list_to_tuple(value: Any) -> tuple:
    """Convert list values from YAML to tuples."""
    if isinstance(value, list):
        return tuple(value)
    return value or tuple()


def _build_permissions(data: dict[str, Any]) -> ProviderPermissions:
    """Build ProviderPermissions from YAML dict."""
    return ProviderPermissions(
        can_write_files=data.get("can_write_files", False),
        can_execute_shell=data.get("can_execute_shell", False),
        can_browse_web=data.get("can_browse_web", False),
        can_read_env=data.get("can_read_env", False),
        notes=data.get("notes", ""),
    )


def _build_host_capabilities(data: list[dict[str, Any]]) -> tuple[HostCapability, ...]:
    """Build HostCapability tuple from YAML list."""
    return tuple(
        HostCapability(
            host=item["host"],
            capability_id=item["capability_id"],
            display_name=item["display_name"],
        )
        for item in data
    )


def _build_agent_files(data: list[dict[str, Any]]) -> tuple[AgentFile, ...]:
    """Build AgentFile tuple from YAML list."""
    return tuple(
        AgentFile(
            rel_path=item["rel_path"],
            managed=item.get("managed", True),
            description=item.get("description", ""),
        )
        for item in data
    )


def _build_cli_install(data: dict[str, Any]) -> CliInstallRecipe:
    """Build CliInstallRecipe from YAML dict.

    Supports two forms:
    1. toolchain-based: {toolchain, package, executable} — uses toolchains loader build_step
    2. explicit steps: {package_manager, package_name, executable, install, uninstall, probe_fn}
    """
    if "toolchain" in data:
        # Toolchain-based form
        toolchain = data["toolchain"]
        package = data["package"]
        executable = data["executable"]
        extra = data.get("extra", [])
        uninstall_package = data.get("uninstall_package", package)

        from audiagentic.foundation.toolchains.loader import build_step, has_action

        un_action = "uninstall" if has_action(toolchain, "uninstall") else "remove"

        return CliInstallRecipe(
            package_manager=toolchain,
            package_name=package,
            executable=executable,
            install=build_step(toolchain, "install", package, *extra),
            uninstall=build_step(toolchain, un_action, uninstall_package),
            probe_fn=resolve_ref(data["probe_fn"]) if "probe_fn" in data else None,
        )
    else:
        # Explicit step form
        install_spec = data.get("install")
        uninstall_spec = data.get("uninstall")

        return CliInstallRecipe(
            package_manager=data["package_manager"],
            package_name=data["package_name"],
            executable=data["executable"],
            install=build_step_from_spec(install_spec) if install_spec else None,  # type: ignore[arg-type]
            uninstall=build_step_from_spec(uninstall_spec) if uninstall_spec else None,  # type: ignore[arg-type]
            probe_fn=resolve_ref(data["probe_fn"]) if "probe_fn" in data else None,
        )


def _build_mcp_config(data: dict[str, Any]) -> ManagedConfigSpec:
    """Build the MCP ManagedConfigSpec from YAML dict."""
    return ManagedConfigSpec(
        config_path=data["config_path"],
        reader=resolve_ref(data["reader"]),
        writer=resolve_ref(data["writer"]),
        remover=resolve_ref(data["remover"]),
        format=data.get("format", ""),
        refresh_mode=data["refresh_mode"],
        reload_fn=resolve_ref(data["reload_fn"]) if "reload_fn" in data else None,
        capabilities=frozenset({REMOTE_CAPABILITY}) if data.get("remote", True) else frozenset(),
    )


def _build_language_servers_config(data: dict[str, Any]) -> ManagedConfigSpec:
    """Build the language-servers ManagedConfigSpec from YAML dict."""
    return ManagedConfigSpec(
        config_path=data["config_path"],
        reader=resolve_ref(data["reader"]),
        writer=resolve_ref(data["writer"]),
        remover=resolve_ref(data["remover"]),
        format=data.get("format", ""),
    )


def _build_model_config(data: dict[str, Any]) -> ManagedConfigSpec:
    """Build the model-endpoints ManagedConfigSpec from YAML dict (MO02)."""
    return ManagedConfigSpec(
        config_path=data["config_path"],
        reader=resolve_ref(data["reader"]),
        writer=resolve_ref(data["writer"]),
        remover=resolve_ref(data["remover"]),
        format=data.get("format", ""),
        refresh_mode=data.get("refresh_mode", "none"),
        reload_fn=resolve_ref(data["reload_fn"]) if "reload_fn" in data else None,
    )


# Provider descriptor field specification
PROVIDER_SPEC = DescriptorSpec(constructor=ProviderDescriptor)

PROVIDER_SPEC.add("provider_id", yaml_key="provider_id", kind="data", required=True)
PROVIDER_SPEC.add("display_name", yaml_key="display_name", kind="data", required=True)
PROVIDER_SPEC.add("description", yaml_key="description", kind="data", default="")
PROVIDER_SPEC.add("url", yaml_key="url", kind="data", default="")
PROVIDER_SPEC.add("prompt_aliases", yaml_key="prompt_aliases", kind="data", default=tuple(), converter=_list_to_tuple)
PROVIDER_SPEC.add("cli_probe", yaml_key="cli_probe", kind="data", default=None)
PROVIDER_SPEC.add("cli_install", yaml_key="cli_install", kind="nested", builder=_build_cli_install, default=None)
PROVIDER_SPEC.add("host_capabilities", yaml_key="host_capabilities", kind="nested", builder=_build_host_capabilities, default=tuple())
PROVIDER_SPEC.add("permissions", yaml_key="permissions", kind="nested", builder=_build_permissions, default=ProviderPermissions())
PROVIDER_SPEC.add("agent_files", yaml_key="agent_files", kind="nested", builder=_build_agent_files, default=tuple())
PROVIDER_SPEC.add("access_mode", yaml_key="access_mode", kind="data", default="cli")
PROVIDER_SPEC.add("skill_surface_path", yaml_key="skill_surface_path", kind="data", default=None)
PROVIDER_SPEC.add("instruction_file", yaml_key="instruction_file", kind="data", default=None)
PROVIDER_SPEC.add("fetch_catalog_fn", yaml_key="fetch_catalog_fn", kind="ref", default=None)
PROVIDER_SPEC.add("mcp_config", yaml_key="mcp_config", kind="nested", builder=_build_mcp_config, default=None)
PROVIDER_SPEC.add("language_servers_config", yaml_key="language_servers_config", kind="nested", builder=_build_language_servers_config, default=None)
PROVIDER_SPEC.add("model_config", yaml_key="model_config", kind="nested", builder=_build_model_config, default=None)
PROVIDER_SPEC.add("model_entry_renderer", yaml_key="model_entry_renderer", kind="ref", default=None)
PROVIDER_SPEC.add("supported_connectors", yaml_key="supported_connectors", kind="data", default=tuple(), converter=_list_to_tuple)
PROVIDER_SPEC.add("vendor_key_injection", yaml_key="vendor_key_injection", kind="data", default=dict())
PROVIDER_SPEC.add("on_lsp_enabled", yaml_key="on_lsp_enabled", kind="ref", default=None)
PROVIDER_SPEC.add("receive_lsp_mcp", yaml_key="receive_lsp_mcp", kind="data", default=True)
PROVIDER_SPEC.add("surfaces", yaml_key="surfaces", kind="data", default=None)
PROVIDER_SPEC.add("execution", yaml_key="execution", kind="data", default=None)
PROVIDER_SPEC.add("annotations", yaml_key="annotations", kind="data", default=dict())


def provider_factory(data: dict[str, Any]) -> ProviderDescriptor:
    """Build a ProviderDescriptor from resolved YAML data.

    This function is used by the generic loader to construct the typed
    descriptor from the resolved field values.
    """
    return PROVIDER_SPEC.build(data)


def load_provider_descriptor(path: Path) -> ProviderDescriptor:
    """Load a ProviderDescriptor from a YAML file.

    Args:
        path: Path to the provider YAML file.

    Returns:
        Constructed ProviderDescriptor instance.
    """
    return load_descriptor(path, PROVIDER_SPEC)


def load_providers_from_directory(directory: Path) -> dict[str, ProviderDescriptor]:
    """Load all provider descriptors from a YAML directory.

    Args:
        directory: Path to directory containing provider YAML files.

    Returns:
        Dict mapping provider_id to ProviderDescriptor.
    """
    providers: dict[str, ProviderDescriptor] = {}
    for path in iter_descriptor_files(directory):
        descriptor = load_descriptor(path, PROVIDER_SPEC)
        providers[descriptor.provider_id] = descriptor
    return providers


def get_providers_config_dir() -> Path:
    """Return the path to the provider config directory.

    Returns:
        Path to src/audiagentic/config/providers/
    """
    return get_package_providers_config_dir()
