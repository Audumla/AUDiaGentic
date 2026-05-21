"""Load and register ComponentDescriptors from YAML config files."""
from __future__ import annotations

from pathlib import Path

from .base import (
    SCOPE_PROJECT,
    ComponentDescriptor,
    ComponentFile,
    ExternalMcpServerDeclaration,
    HarnessInstruction,
    McpServerDeclaration,
)
from .registry import register

# Resolve relative to the installed package — works in both editable installs and wheels.
_PACKAGE_DIR = Path(__file__).resolve().parents[2]  # audiagentic/
_COMPONENTS_CONFIG_DIR = _PACKAGE_DIR / "config" / "components"
_ALL_COMPONENT_CONFIG_DIRS = [
    _COMPONENTS_CONFIG_DIR / "core",
    _COMPONENTS_CONFIG_DIR / "optional",
]


def register_from_yaml(path: Path) -> ComponentDescriptor:
    """Parse a single component config YAML and register the descriptor."""
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data.get("type") != "component":
        raise ValueError(f"{path.name}: expected type=component, got {data.get('type')}")
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
            args=tuple(ms.get("args") or []),
            direct_tools=ms.get("direct-tools") or [],
            description=ms.get("description", ""),
            instructions=ms.get("instructions", ""),
            tool_descriptions=ms.get("tool-descriptions") or {},
        )
        for ms in (data.get("mcp-servers") or [])
    )

    external_mcp_servers = tuple(
        ExternalMcpServerDeclaration(
            name=ms["name"],
            command=ms["command"],
            args=tuple(ms.get("args") or []),
            env=dict(ms.get("env") or {}),
            description=ms.get("description", ""),
            instructions=ms.get("instructions", ""),
            requires=tuple(ms.get("requires") or []),
            probe=tuple(ms.get("probe") or []),
        )
        for ms in (data.get("external-mcp-servers") or [])
    )

    harness_instructions = tuple(
        HarnessInstruction(
            section=hi["section"],
            content=hi["content"],
            description=hi.get("description", ""),
        )
        for hi in (data.get("harness-instructions") or [])
    )

    # Components under a "core" subdirectory are automatically core
    is_core = bool(data.get("core", False)) or path.parent.name == "core"

    descriptor = ComponentDescriptor(
        type=data["type"],
        component_id=data["component-id"],
        display_name=data.get("display-name", data["component-id"]),
        description=data.get("description", ""),
        detection_marker=data.get("detection-marker", ""),
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
    )
    register(descriptor)
    return descriptor


def register_all_components(config_dirs: list[Path] | None = None) -> list[ComponentDescriptor]:
    """Load and register every *.yaml file across all component config dirs.

    Defaults to config/components/{core,optional}/ (top-level YAMLs only).
    Idempotent — re-registering an already-known component-id is a no-op overwrite.

    After loading descriptors, imports any declared lifecycle-observer modules so
    they self-register their event bus subscriptions.
    """
    targets = config_dirs or _ALL_COMPONENT_CONFIG_DIRS
    descriptors = []
    for target in targets:
        for path in sorted(target.resolve().glob("*.yaml")):
            descriptors.append(register_from_yaml(path))
    for descriptor in descriptors:
        if descriptor.lifecycle_observer:
            try:
                __import__(descriptor.lifecycle_observer)
            except Exception:  # noqa: BLE001
                pass
    return descriptors
