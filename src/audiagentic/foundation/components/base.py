from __future__ import annotations

from dataclasses import dataclass

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
class ComponentDescriptor:
    component_id: str
    display_name: str
    description: str
    detection_marker: str   # rel_path proving component is installed (relative to component_root)
    files: tuple[ComponentFile, ...] = ()
    depends_on: tuple[str, ...] = ()
    config_path: str | None = None  # path relative to config/ for detailed component config
    scope: str = SCOPE_PROJECT      # SCOPE_PROJECT | SCOPE_HARNESS
