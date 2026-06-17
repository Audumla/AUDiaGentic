"""LSP component bootstrap — lifecycle observer.

Imported by the harness via lifecycle-observer in coding-lsp.yaml.
Subscribes to component lifecycle events.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from audiagentic.components.optional.coding_lsp import language_registry
from audiagentic.components.optional.coding_lsp.coding_lsp_config import (
    CODING_LSP_DIR,
    discover_language_servers,
)
from audiagentic.foundation.components.dependencies import (
    build_dependency_install_commands,
    build_dependency_labels,
    build_dependency_probes,
    detect_missing,
)
from audiagentic.foundation.components.ids import COMPONENT_CODING_LSP
from audiagentic.foundation.event import get_bus
from audiagentic.runtime.lifecycle.observers import (
    COMPONENT_DISABLED,
    COMPONENT_ENABLED,
    COMPONENT_INSTALLED,
    COMPONENT_UNINSTALLED,
)

_REGISTERED = False

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# Dependency facts come from the per-language registry, not the component YAML.
_LSP_PROBES = build_dependency_probes(language_registry.dependency_cfgs())
_LSP_DEP_LABELS = build_dependency_labels(language_registry.dependency_cfgs())
LSP_DEPENDENCY_IDS = list(_LSP_PROBES.keys())


def _format_command(command: list[str]) -> str:
    return " ".join(command)


def _on_lifecycle_event(event_type: str, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
    component_id = payload.get("component_id")
    project_root = payload.get("project_root")
    if component_id != COMPONENT_CODING_LSP:
        return

    if event_type == COMPONENT_INSTALLED and isinstance(project_root, Path):
        _on_installed(project_root)
    elif event_type == COMPONENT_ENABLED and isinstance(project_root, Path):
        _on_enabled(project_root)
    elif event_type in (COMPONENT_DISABLED, COMPONENT_UNINSTALLED):
        _on_disabled(project_root)


def _on_installed(project_root: Path) -> None:
    """Create .coding-lsp/ structure without inferring runtime server config."""
    coding_lsp_dir = project_root / CODING_LSP_DIR
    coding_lsp_dir.mkdir(parents=True, exist_ok=True)
    (coding_lsp_dir / "logs").mkdir(parents=True, exist_ok=True)


def _on_enabled(project_root: Path) -> None:
    """Discover available language servers and sync to provider configs."""
    try:
        available = discover_language_servers(project_root)
    except Exception:
        logger.warning("Failed to discover language servers", exc_info=True)
        available = {}

    try:
        from .language_servers_sync import sync_language_servers_to_providers
        result = sync_language_servers_to_providers(project_root)
        if result.get("synced"):
            logger.info(
                "Synced language servers to providers: %s",
                ", ".join(result["synced"]),
            )
    except Exception:
        logger.warning("Failed to sync language servers to providers", exc_info=True)


def _on_disabled(project_root: Path | None = None) -> None:
    """Shutdown all sessions and prune language server configs."""
    from audiagentic.components.optional.coding_lsp.lsp_api import shutdown_all_sessions
    shutdown_all_sessions()

    if project_root is not None:
        try:
            from .language_servers_sync import prune_language_servers_from_providers
            result = prune_language_servers_from_providers(project_root)
            if result.get("pruned"):
                logger.info(
                    "Pruned language servers from providers: %s",
                    ", ".join(result["pruned"]),
                )
        except Exception:
            logger.warning("Failed to prune language servers from providers", exc_info=True)


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

    lsp.json is the sole source of active languages. Nothing auto-detects or
    auto-populates it; languages are added explicitly via lsp_add_language.
    No configured languages means no dependencies and no install prompt.
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

    install_commands = build_dependency_install_commands(
        language_registry.dependency_cfgs(), missing, workflow_id="coding-lsp"
    )

    offers = []
    for dep_id in missing:
        commands = install_commands.get(dep_id) or []
        cmd = " && ".join(_format_command(command) for command in commands) if commands else "install manually"
        label = _LSP_DEP_LABELS.get(dep_id, dep_id)
        offers.append(f"Install {label}: {cmd}")

    return {
        "missing-dependencies": missing,
        "dependency-install-offer": ". ".join(offers),
    }


register()
