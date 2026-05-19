"""Load and register ComponentDescriptors from YAML config files."""
from __future__ import annotations

from pathlib import Path

from .base import SCOPE_PROJECT, ComponentDescriptor, ComponentFile, HarnessInstruction, McpServerDeclaration
from .registry import register

# Resolve relative to the installed package — works in both editable installs and wheels.
_PACKAGE_DIR = Path(__file__).resolve().parents[2]  # audiagentic/
_COMPONENTS_CONFIG_DIR = _PACKAGE_DIR / "config" / "foundation" / "components"
_ALL_COMPONENT_CONFIG_DIRS = [_COMPONENTS_CONFIG_DIR]


def register_from_yaml(path: Path) -> ComponentDescriptor:
    """Parse a single component config YAML and register the descriptor."""
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
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
        )
        for ms in (data.get("mcp-servers") or [])
    )

    harness_instructions = tuple(
        HarnessInstruction(
            section=hi["section"],
            content=hi["content"],
            description=hi.get("description", ""),
        )
        for hi in (data.get("harness-instructions") or [])
    )

    descriptor = ComponentDescriptor(
        component_id=data["component-id"],
        display_name=data.get("display-name", data["component-id"]),
        description=data.get("description", ""),
        detection_marker=data["detection-marker"],
        files=files,
        depends_on=tuple(data.get("depends-on") or []),
        config_path=data.get("config") or None,
        scope=data.get("scope", SCOPE_PROJECT),
        mcp_servers=mcp_servers,
        harness_instructions=harness_instructions,
    )
    register(descriptor)
    return descriptor


def register_all_components(config_dirs: list[Path] | None = None) -> list[ComponentDescriptor]:
    """Load and register every *.yaml file across all component config dirs.

    Defaults to foundation/components and interoperability/providers/surfaces.
    Idempotent — re-registering an already-known component-id is a no-op overwrite.
    """
    targets = config_dirs or _ALL_COMPONENT_CONFIG_DIRS
    descriptors = []
    for target in targets:
        for path in sorted(target.resolve().rglob("*.yaml")):
            descriptors.append(register_from_yaml(path))
    return descriptors
