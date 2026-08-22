from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class McpServerDeclaration:
    name: str
    module: str
    managed_id: str | None = None
    args: tuple[str, ...] = ()
    direct_tools: list[str] = field(default_factory=list)
    description: str = ""
    instructions: str = ""
    #: Rich tool metadata. Value is either a plain string (description only) or a
    #: mapping. Known standard keys in a mapping value: ``description`` (str — the
    #: MCP tool annotation), ``parameters`` (dict of param-name -> description str
    #: or nested mapping). Any additional keys are provider/component-owned extension;
    #: the foundation passes them through unchanged.
    tool_descriptions: dict[str, Any] = field(default_factory=dict)
    propagate: str = "audiagentic"  # "audiagentic" | "providers" | "audiagentic,providers"


@dataclass(frozen=True)
class ExternalMcpServerDeclaration:
    """MCP server backed by an external command (not a Python module).

    Entries are included in the harness mcp.json only when all tools listed
    in `requires` are present on PATH.
    """
    name: str
    command: str
    managed_id: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    description: str = ""
    instructions: str = ""
    requires: tuple[str, ...] = ()   # CLI tool names checked via shutil.which
    probe: tuple[str, ...] = ()      # command to run to verify server is usable (returncode 0 = ok)
    propagate: str = "audiagentic"  # "audiagentic" | "providers" | "audiagentic,providers"


@dataclass(frozen=True)
class HarnessInstruction:
    section: str
    content: str
    description: str = ""
    propagate: str = "audiagentic"  # "audiagentic" | "providers" | "audiagentic,providers"


@dataclass(frozen=True)
class ComponentDescriptor:
    # --- identity ---
    component_id: str
    display_name: str
    description: str
    detection_marker: str   # rel_path proving component is installed (relative to component_root)
    aliases: tuple[str, ...] = ()
    type: str = "component"         # discriminator: "component" vs other config types
    scope: str = SCOPE_PROJECT      # SCOPE_PROJECT | SCOPE_HARNESS
    core: bool = False              # if True, component cannot be uninstalled
    yaml_path: Path | None = None   # absolute path to the component's YAML file

    # --- files ---
    files: tuple[ComponentFile, ...] = ()

    # --- dependencies ---
    depends_on: tuple[str, ...] = ()

    # --- mcp ---
    mcp_servers: tuple[McpServerDeclaration, ...] = ()
    external_mcp_servers: tuple[ExternalMcpServerDeclaration, ...] = ()

    # --- lifecycle hooks ---
    post_install: str | None = None  # dotted import path to a function(project_root)
    lifecycle_observer: str | None = None  # dotted module path imported by register_all_components to self-register bus subscribers
    lifecycle_hook: str | None = None  # dotted import path to a function(event_type, payload, metadata)
    status_hook: str | None = None  # dotted import path to a function(project_root) -> dict
    context_hook: str | None = None  # dotted import path to a function(project_root) -> mapping
    context_namespace: str | None = None  # optional stable template namespace

    # --- feature ---
    harness_instructions: tuple[HarnessInstruction, ...] = ()
    implementation_cardinality: str | None = None  # None | "exclusive" | "multi"
