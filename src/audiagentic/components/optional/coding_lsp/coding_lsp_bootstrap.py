"""LSP component bootstrap — lifecycle observer.

Imported by the harness via lifecycle-observer in coding-lsp.yaml.
Subscribes to component lifecycle events.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from audiagentic.components.optional.coding_lsp.coding_lsp_config import (
    _DEFAULT_SERVERS,
    CODING_LSP_DIR,
    detect_project_languages,
    discover_language_servers,
    write_lsp_config,
)
from audiagentic.foundation.components.ids import COMPONENT_CODING_LSP
from audiagentic.foundation.dependencies import detect_missing, load_component_probes
from audiagentic.foundation.event import get_bus
from audiagentic.runtime.lifecycle.observers import (
    COMPONENT_DISABLED,
    COMPONENT_ENABLED,
    COMPONENT_INSTALLED,
    COMPONENT_UNINSTALLED,
)

_REGISTERED = False

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

_LSP_PROBES = load_component_probes("coding-lsp")
LSP_DEPENDENCY_IDS = list(_LSP_PROBES.keys())


def _on_lifecycle_event(event_type: str, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
    component_id = payload.get("component_id")
    project_root = payload.get("project_root")
    if component_id != COMPONENT_CODING_LSP or not isinstance(project_root, Path):
        return

    if event_type == COMPONENT_INSTALLED:
        _on_installed(project_root)
    elif event_type == COMPONENT_ENABLED:
        _on_enabled(project_root)
    elif event_type in (COMPONENT_DISABLED, COMPONENT_UNINSTALLED):
        _on_disabled()


def _on_installed(project_root: Path) -> None:
    """Create .coding-lsp/ structure and auto-configure detected project languages."""
    coding_lsp_dir = project_root / CODING_LSP_DIR
    coding_lsp_dir.mkdir(parents=True, exist_ok=True)
    (coding_lsp_dir / "logs").mkdir(parents=True, exist_ok=True)

    lsp_json = coding_lsp_dir / "lsp.json"
    if not lsp_json.exists():
        detected = detect_project_languages(project_root)
        initial_config = {
            lang: {
                "command": _DEFAULT_SERVERS[lang].command,
                "fileExtensions": _DEFAULT_SERVERS[lang].file_extensions,
                "workspaceConfigFiles": _DEFAULT_SERVERS[lang].workspace_config_files,
            }
            for lang in detected
            if lang in _DEFAULT_SERVERS
        }
        write_lsp_config(lsp_json, initial_config)


def _on_enabled(project_root: Path) -> None:
    """Discover available language servers and cache results."""
    try:
        available = discover_language_servers(project_root)
    except Exception:
        logger.warning("Failed to discover language servers", exc_info=True)
        available = {}


def _on_disabled() -> None:
    """Shutdown all sessions."""
    from audiagentic.components.optional.coding_lsp.lsp_api import shutdown_all_sessions
    shutdown_all_sessions()


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


def _active_dependency_ids(project_root: Path | None) -> list[str]:
    """Return dependency IDs for languages explicitly configured in lsp.json.

    lsp.json is the source of truth for active languages — auto-detection runs
    once at install to populate it, not on every status check.
    """
    from audiagentic.components.optional.coding_lsp.lsp_api import configured_dependency_ids
    return configured_dependency_ids(project_root)


def status_payload(project_root: Path | None = None) -> dict[str, Any]:
    """Return status payload for the coding-lsp component.

    Includes missing-dependencies and dependency-install-offer keys
    so the component installer can prompt the user to install them.
    Only reports dependencies for languages configured or detected in the project.
    """
    active_dep_ids = _active_dependency_ids(project_root)
    if not active_dep_ids:
        return {}
    missing = detect_missing(_LSP_PROBES, active_dep_ids)
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

