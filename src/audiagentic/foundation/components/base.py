from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MODE_REQUIRED_MANAGED = "required-managed"
MODE_CREATE_IF_MISSING = "create-if-missing"
MODE_GENERATED_MANAGED = "generated-managed"
MODE_RUNTIME_ONLY = "runtime-only"

# Component scopes
SCOPE_PROJECT = "project"   # installed into project_root/.audiagentic/
SCOPE_HARNESS = "harness"   # installed into audiagentic_home() — shared across all projects

__all__ = [
    "ComponentFile",
    "ComponentDescriptor",
    "McpServerDeclaration",
    "ExternalMcpServerDeclaration",
    "MODE_REQUIRED_MANAGED",
    "MODE_CREATE_IF_MISSING",
    "MODE_GENERATED_MANAGED",
    "MODE_RUNTIME_ONLY",
    "SCOPE_PROJECT",
    "SCOPE_HARNESS",
]


@dataclass(frozen=True)
class ComponentFile:
    rel_path: str
    lifecycle: str          # one of the MODE_* constants
    recursive: bool = False
    description: str = ""


from dataclasses import field


@dataclass(frozen=True)
class McpServerDeclaration:
    name: str
    module: str
    args: tuple[str, ...] = ()
    direct_tools: list[str] | bool = field(default_factory=list)
    description: str = ""
    instructions: str = ""
    tool_descriptions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalMcpServerDeclaration:
    """MCP server backed by an external command (not a Python module).

    Entries are included in the harness mcp.json only when all tools listed
    in `requires` are present on PATH.
    """
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    description: str = ""
    instructions: str = ""
    requires: tuple[str, ...] = ()   # CLI tool names checked via shutil.which
    probe: tuple[str, ...] = ()      # command to run to verify server is usable (returncode 0 = ok)


@dataclass(frozen=True)
class HarnessInstruction:
    section: str
    content: str
    description: str = ""


@dataclass(frozen=True)
class ComponentDescriptor:
    component_id: str
    display_name: str
    description: str
    detection_marker: str   # rel_path proving component is installed (relative to component_root)
    files: tuple[ComponentFile, ...] = ()
    depends_on: tuple[str, ...] = ()
    yaml_path: Path | None = None   # absolute path to the component's YAML file
    scope: str = SCOPE_PROJECT      # SCOPE_PROJECT | SCOPE_HARNESS
    mcp_servers: tuple[McpServerDeclaration, ...] = ()
    external_mcp_servers: tuple[ExternalMcpServerDeclaration, ...] = ()
    harness_instructions: tuple[HarnessInstruction, ...] = ()
    core: bool = False              # if True, component cannot be uninstalled
    type: str = "component"         # discriminator: "component" vs other config types
    post_install: str | None = None  # dotted import path to a function(project_root)
    lifecycle_observer: str | None = None  # dotted module path imported by register_all_components to self-register bus subscribers
