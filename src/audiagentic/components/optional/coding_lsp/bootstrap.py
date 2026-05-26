"""LSP component bootstrap — lifecycle observer.

Imported by the harness via lifecycle-observer in coding-lsp.yaml.
Subscribes to component lifecycle events.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from audiagentic.foundation.event import get_bus
from audiagentic.components.optional.coding_lsp.config import (
    detect_project_languages,
    discover_language_servers,
    read_lsp_config,
    write_lsp_config,
)
from audiagentic.foundation.dependencies import detect_missing
from audiagentic.components.optional.coding_lsp.lsp_dependencies import get_lsp_dependencies
from audiagentic.runtime.lifecycle.observers import (
    COMPONENT_ENABLED,
    COMPONENT_INSTALLED,
    COMPONENT_DISABLED,
    COMPONENT_UNINSTALLED,
)

_REGISTERED = False

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# Dependency IDs used by this component's status hook
LSP_DEPENDENCY_IDS = list(get_lsp_dependencies().keys())


def _on_lifecycle_event(event_type: str, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
    component_id = payload.get("component_id")
    project_root = payload.get("project_root")
    if component_id != "coding-lsp" or not isinstance(project_root, Path):
        return

    if event_type == COMPONENT_INSTALLED:
        _on_installed(project_root)
    elif event_type == COMPONENT_ENABLED:
        _on_enabled(project_root)
    elif event_type in (COMPONENT_DISABLED, COMPONENT_UNINSTALLED):
        _on_disabled()


def _on_installed(project_root: Path) -> None:
    """Create .coding-lsp/ structure and copy lsp.json template if missing."""
    coding_lsp_dir = project_root / ".coding-lsp"
    coding_lsp_dir.mkdir(parents=True, exist_ok=True)
    (coding_lsp_dir / "logs").mkdir(parents=True, exist_ok=True)

    lsp_json = coding_lsp_dir / "lsp.json"
    if not lsp_json.exists():
        template = _TEMPLATE_DIR / "lsp.json.example"
        if template.exists():
            write_lsp_config(lsp_json, {"python": {
                "command": ["pyright-langserver", "--stdio"],
                "fileExtensions": [".py", ".pyi"],
                "workspaceConfigFiles": ["pyrightconfig.json"],
            }})


def _on_enabled(project_root: Path) -> None:
    """Discover available language servers and cache results."""
    try:
        available = discover_language_servers(project_root)
    except Exception:
        available = {}


def _on_disabled() -> None:
    """Shutdown all sessions."""
    from audiagentic.components.optional.coding_lsp.mcp_server import _session_manager
    _session_manager.shutdown_all()


def register() -> None:
    """Subscribe to component lifecycle events."""
    global _REGISTERED
    if _REGISTERED:
        return
    bus = get_bus()
    bus.subscribe(COMPONENT_INSTALLED, _on_lifecycle_event)
    bus.subscribe(COMPONENT_ENABLED, _on_lifecycle_event)
    bus.subscribe(COMPONENT_DISABLED, _on_lifecycle_event)
    bus.subscribe(COMPONENT_UNINSTALLED, _on_lifecycle_event)
    _REGISTERED = True


def status_payload(project_root: Path | None = None) -> dict[str, Any]:
    """Return status payload for the coding-lsp component.

    Includes missing-dependencies and dependency-install-offer keys
    so the component installer can prompt the user to install them.
    """
    deps = get_lsp_dependencies()
    missing = detect_missing(deps, LSP_DEPENDENCY_IDS)
    if not missing:
        return {}

    install_commands: dict[str, str] = {
        "pyright": "uv tool install pyright",
        "typescript-language-server": "npm install -g typescript-language-server",
        "rust-analyzer": "cargo install rust-analyzer",
        "clangd": "install clangd via your system package manager",
    }

    offers = []
    for dep_id in missing:
        cmd = install_commands.get(dep_id, "install manually")
        label = deps[dep_id].display_name
        offers.append(f"Install {label}: {cmd}")

    return {
        "missing-dependencies": missing,
        "dependency-install-offer": ". ".join(offers),
    }


register()
