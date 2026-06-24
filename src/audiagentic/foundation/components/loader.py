"""Load and register ComponentDescriptors from YAML config files."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import load_yaml_file

_component_error: Any = make_error_factory("VAL", "COMP", "components")

from .base import (
    SCOPE_PROJECT,
    ComponentDescriptor,
    ComponentFile,
    ExternalMcpServerDeclaration,
    HarnessInstruction,
    McpServerDeclaration,
)
from .hooks import initialize_lifecycle_hook_dispatch
from .registry import register

logger = logging.getLogger(__name__)

# Resolve relative to the installed package — works in both editable installs and wheels.
_PACKAGE_DIR = Path(__file__).resolve().parents[2]  # audiagentic/
_COMPONENTS_CONFIG_DIR = _PACKAGE_DIR / "config" / "components"
_ALL_COMPONENT_CONFIG_DIRS = [_COMPONENTS_CONFIG_DIR]


def component_yaml_path(component_id: str) -> Path:
    """Return the config YAML path for a component in the unified components dir."""
    for base in _ALL_COMPONENT_CONFIG_DIRS:
        candidate = base / f"{component_id}.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no component config found for '{component_id}'")


def _require_propagate(ms: dict, path: Path) -> str:
    if "propagate" not in ms:
        logger.warning(
            "MCP server %r in %s missing required 'propagate' field — defaulting to 'audiagentic'",
            ms.get("name", "<unknown>"),
            path.name,
        )
        return "audiagentic"
    return ms["propagate"]


def register_from_yaml(path: Path) -> ComponentDescriptor:
    """Parse a single component config YAML and register the descriptor."""
    data = load_yaml_file(path)
    if data.get("type") != "component":
        raise _component_error(
            1,
            f"{path.name}: expected type=component, got {data.get('type')}",
            path=str(path),
            expected="component",
            actual=data.get("type"),
        )
    component_id = data.get("id")
    if not isinstance(component_id, str) or not component_id:
        raise _component_error(2, f"{path.name}: missing or empty id", path=str(path), field="id")
    files = tuple(
        ComponentFile(
            rel_path=f["path"],
            lifecycle=f["lifecycle"],
            recursive=bool(f.get("recursive", False)),
            description=f.get("description", ""),
        )
        for f in (data.get("files") or [])
    )
    mcp_servers = tuple(
        McpServerDeclaration(
            name=ms["name"],
            module=ms["module"],
            managed_id=ms.get("managed-id"),
            args=tuple(ms.get("args") or []),
            direct_tools=ms.get("direct-tools") or [],
            description=ms.get("description", ""),
            instructions=ms.get("instructions", ""),
            tool_descriptions=ms.get("tool-descriptions") or {},
            propagate=_require_propagate(ms, path),
        )
        for ms in (data.get("mcp-servers") or [])
    )

    external_mcp_servers = tuple(
        ExternalMcpServerDeclaration(
            name=ms["name"],
            command=ms["command"],
            managed_id=ms.get("managed-id"),
            args=tuple(ms.get("args") or []),
            env=dict(ms.get("env") or {}),
            description=ms.get("description", ""),
            instructions=ms.get("instructions", ""),
            requires=tuple(ms.get("requires") or []),
            probe=tuple(ms.get("probe") or []),
            propagate=_require_propagate(ms, path),
        )
        for ms in (data.get("external-mcp-servers") or [])
    )

    raw_harness_instructions = data.get("harness-instructions") or []
    if raw_harness_instructions:
        harness_instructions = tuple(
            HarnessInstruction(
                section=hi["section"],
                content=hi["content"],
                description=hi.get("description", ""),
                propagate=hi.get("propagate", "audiagentic"),
            )
            for hi in raw_harness_instructions
        )
    else:
        # Derive harness instructions from MCP server declarations
        from audiagentic.runtime.harness.system_prompt import (
            derive_harness_instructions as _derive_harness_instructions,
        )

        provisional = ComponentDescriptor(
            type=data["type"],
            component_id=component_id,
            display_name=data.get("display-name", component_id),
            description=data.get("description", ""),
            detection_marker=data.get("detection-marker", ""),
            aliases=tuple(data.get("aliases") or []),
            files=(),
            depends_on=tuple(data.get("depends-on") or []),
            yaml_path=path,
            scope=data.get("scope", SCOPE_PROJECT),
            mcp_servers=mcp_servers,
            external_mcp_servers=(),
            harness_instructions=(),
            core=bool(data.get("core", False)),
        )
        harness_instructions = _derive_harness_instructions(provisional)

    # Core flag is determined solely by the YAML descriptor's core field
    is_core = bool(data.get("core", False))

    descriptor = ComponentDescriptor(
        type=data["type"],
        component_id=component_id,
        display_name=data.get("display-name", component_id),
        description=data.get("description", ""),
        detection_marker=data.get("detection-marker", ""),
        aliases=tuple(data.get("aliases") or []),
        files=files,
        depends_on=tuple(data.get("depends-on") or []),
        yaml_path=path,
        scope=data.get("scope", SCOPE_PROJECT),
        mcp_servers=mcp_servers,
        external_mcp_servers=external_mcp_servers,
        harness_instructions=harness_instructions,
        core=is_core,
        post_install=data.get("post-install") or None,
        lifecycle_observer=data.get("lifecycle-observer") or None,
        lifecycle_hook=data.get("lifecycle-hook") or None,
        status_hook=data.get("status-hook") or None,
        implementation_cardinality=data.get("implementation-cardinality") or None,
    )
    register(descriptor)
    return descriptor


def register_all_components(config_dirs: list[Path] | None = None) -> list[ComponentDescriptor]:
    """Load and register every *.yaml file across all component config dirs.

    Defaults to config/components/ (top-level YAMLs only).
    Idempotent — re-registering an already-known component id is a no-op overwrite.

    After loading descriptors, imports any declared lifecycle-observer modules so
    they self-register their event bus subscriptions.
    """
    targets = config_dirs or _ALL_COMPONENT_CONFIG_DIRS
    descriptors = []
    feature_descriptor_types = {"feature", "implementation", "binding"}
    for target in targets:
        for path in sorted(target.resolve().glob("*.yaml")):
            data = load_yaml_file(path)
            if data.get("type") in feature_descriptor_types:
                from audiagentic.foundation.features.loader import (
                    register_from_yaml as register_feature_from_yaml,
                )

                register_feature_from_yaml(path)
                continue
            descriptors.append(register_from_yaml(path))

        for path in sorted(target.resolve().glob("*/*.yaml")):
            data = load_yaml_file(path)
            if data.get("type") in feature_descriptor_types:
                from audiagentic.foundation.features.loader import (
                    register_from_yaml as register_feature_from_yaml,
                )

                register_feature_from_yaml(path)

    _validate_loaded_descriptors(descriptors)

    for descriptor in descriptors:
        if descriptor.lifecycle_observer:
            try:
                __import__(descriptor.lifecycle_observer)
            except Exception:
                logger.warning("Failed to import lifecycle observer for %s", descriptor.component_id, exc_info=True)
    initialize_lifecycle_hook_dispatch()

    from audiagentic.foundation.contracts.error_resolutions import (
        load_all_error_resolutions,
    )

    load_all_error_resolutions(targets)

    return descriptors


def _validate_loaded_descriptors(descriptors: list[ComponentDescriptor]) -> None:
    """Post-load validation for component dependency references.

    Runs after ALL descriptors are loaded so depends-on references can be
    checked against the full set rather than an incrementally built partial set.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for descriptor in descriptors:
        if descriptor.component_id in seen:
            duplicates.add(descriptor.component_id)
        seen.add(descriptor.component_id)
    if duplicates:
        raise _component_error(
            3,
            f"duplicate component ids loaded: {', '.join(sorted(duplicates))}",
            duplicate_ids=sorted(duplicates),
        )

    loaded_ids = {d.component_id for d in descriptors}

    for descriptor in descriptors:
        for dep in descriptor.depends_on:
            if dep not in loaded_ids:
                raise _component_error(
                    4,
                    f"component '{descriptor.component_id}' depends on unknown component '{dep}'",
                    component=descriptor.component_id,
                    dependency=dep,
                )

    # Check for drift between MCP server declarations and harness instructions
    from audiagentic.runtime.harness.system_prompt import (
        check_harness_instruction_drift,
    )

    for descriptor in descriptors:
        for warning in check_harness_instruction_drift(descriptor):
            logger.warning(warning)

    # Validate contribution config references resolve to existing files
    from audiagentic.components.providers.surfaces.base import (
        validate_config_reference,
    )

    for descriptor in descriptors:
        if not descriptor.yaml_path or not descriptor.yaml_path.exists():
            continue
        data = load_yaml_file(descriptor.yaml_path)
        raw_list = data.get("contributions") or data.get("surface-contributions") or []
        for raw in raw_list:
            if not isinstance(raw, dict):
                continue
            config_ref = raw.get("config")
            if isinstance(config_ref, str):
                warning = validate_config_reference(config_ref, descriptor.component_id)
                if warning:
                    logger.warning(warning)
