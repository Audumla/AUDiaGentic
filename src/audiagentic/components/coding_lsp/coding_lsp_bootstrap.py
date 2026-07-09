"""LSP component bootstrap — lifecycle observer.

Imported by the harness via lifecycle-observer in coding-lsp.yaml.
Subscribes to component lifecycle events.
"""
from __future__ import annotations

import logging
from pathlib import Path

from audiagentic.components.coding_lsp.coding_lsp_config import (
    CODING_LSP_DIR,
)
from audiagentic.foundation.components import is_enabled
from audiagentic.foundation.components.dependencies import (
    build_dependency_install_commands,
    build_dependency_labels,
    build_dependency_probes,
    detect_missing,
)
from audiagentic.foundation.components.hooks import ComponentStatusPayload
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event import subscribe_component_lifecycle

logger = logging.getLogger(__name__)

# Register binding writers at module-import time so they're visible to
# feature validation (which runs after lifecycle observers are imported).
from . import language_servers_sync  # noqa: E402,F401

_COMPONENT_ID = "coding-lsp"

_REGISTERED = False

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _format_command(command: list[str]) -> str:
    return " ".join(command)


def _format_dependency_install_offer(
    missing: list[str],
    install_commands: dict[str, list[list[str]]],
    dep_labels: dict[str, str],
) -> str:
    offers = []
    for dep_id in missing:
        commands = install_commands.get(dep_id) or []
        fallback = (
            "; manual fallback if automation fails: "
            + " && ".join(_format_command(command) for command in commands)
            if commands
            else ""
        )
        label = dep_labels.get(dep_id, dep_id)
        offers.append(
            f"{label} auto-installs on first file-based LSP use; "
            f"for eager install call lsp_install_dependencies(['{dep_id}']){fallback}"
        )
    return ". ".join(offers)


def _on_installed(project_root: Path) -> None:
    """Create .coding-lsp/ structure without inferring runtime server config."""
    coding_lsp_dir = project_root / CODING_LSP_DIR
    coding_lsp_dir.mkdir(parents=True, exist_ok=True)
    (coding_lsp_dir / "logs").mkdir(parents=True, exist_ok=True)


def _on_enabled(project_root: Path) -> None:
    """Sync configured language servers and generic MCP projection to providers.

    Projection only — fast and side-effect-light. Provider provisioning that needs
    a network install (e.g. pi-lens) is deliberately NOT done here: it runs from
    the explicit `lsp_install_dependencies` flow so enabling the component never
    blocks on a slow install.
    """
    try:
        from .language_servers_sync import (
            sync_generic_lsp_mcp_to_providers,
            sync_language_servers_to_providers,
        )
        native_result = sync_language_servers_to_providers(project_root)
        generic_result = sync_generic_lsp_mcp_to_providers(project_root)
        if native_result.get("synced"):
            logger.info(
                "Synced language servers to providers: %s",
                ", ".join(native_result["synced"]),
            )
        if generic_result.get("synced"):
            logger.info(
                "Synced generic ag-lsp MCP to providers: %s",
                ", ".join(generic_result["synced"]),
            )
    except AudiaGenticError:
        logger.warning("Failed to sync coding-lsp provider config", exc_info=True)


def _on_disabled(project_root: Path | None = None) -> None:
    """Shutdown all sessions and prune language server configs."""
    from audiagentic.components.coding_lsp.lsp_api import shutdown_all_sessions
    shutdown_all_sessions()

    if project_root is not None:
        try:
            from .language_servers_sync import (
                prune_generic_lsp_mcp_from_providers,
                prune_language_servers_from_providers,
            )
            native_result = prune_language_servers_from_providers(project_root)
            generic_result = prune_generic_lsp_mcp_from_providers(project_root)
            if native_result.get("pruned"):
                logger.info(
                    "Pruned language servers from providers: %s",
                    ", ".join(native_result["pruned"]),
                )
            if generic_result.get("pruned"):
                logger.info(
                    "Pruned generic ag-lsp MCP from providers: %s",
                    ", ".join(generic_result["pruned"]),
                )
        except AudiaGenticError:
            logger.warning("Failed to prune coding-lsp provider config", exc_info=True)


def register() -> None:
    """Subscribe to component lifecycle events."""
    global _REGISTERED
    if _REGISTERED:
        return
    subscribe_component_lifecycle(
        _COMPONENT_ID,
        on_installed=lambda root, payload, metadata: _on_installed(root),
        on_enabled=lambda root, payload, metadata: _on_enabled(root),
        on_disabled=lambda root, payload, metadata: _on_disabled(root),
        on_uninstalled=lambda root, payload, metadata: _on_disabled(root),
    )
    _REGISTERED = True


def _active_dependency_ids(project_root: Path | None) -> list[str]:
    """Return dependency IDs for active implementation and configured languages.

    Feature state is the source of active languages. Nothing auto-detects or
    auto-populates it; languages are added explicitly via lsp_add_language.
    Implementation dependencies are included when a non-default implementation
    is selected. lsp.json is only a generated runtime cache/projection.
    """
    from audiagentic.components.coding_lsp.lsp_config_api import active_dependency_ids
    return active_dependency_ids(project_root)


def status_payload(project_root: Path | None = None) -> ComponentStatusPayload:
    """Return status payload for the coding-lsp component.

    Includes missing-dependencies and dependency-install-offer keys
    so the component installer can prompt the user to install them.
    Only reports dependencies for languages configured or detected in the project.
    """
    active_dep_ids = _active_dependency_ids(project_root)
    enabled = bool(project_root and is_enabled(_COMPONENT_ID, project_root))
    active_impl = None
    if project_root is not None:
        from audiagentic.components.coding_lsp.runtime_resolver import active_lsp_implementation
        active_impl = active_lsp_implementation(project_root)
    if not active_dep_ids:
        return ComponentStatusPayload(
            enabled=enabled,
            configured=True,
            active_implementation=active_impl,
            missing_required=[],
            details={},
        )
    from audiagentic.components.coding_lsp.lsp_config_api import active_dependency_cfgs

    dep_cfgs = active_dependency_cfgs(project_root)
    probes = build_dependency_probes(dep_cfgs)
    missing = detect_missing(probes, active_dep_ids)
    if not missing:
        return ComponentStatusPayload(
            enabled=enabled,
            configured=True,
            active_implementation=active_impl,
            missing_required=[],
            details={},
        )

    install_commands = build_dependency_install_commands(
        dep_cfgs, missing, workflow_id="coding-lsp"
    )
    dep_labels = build_dependency_labels(dep_cfgs)

    return ComponentStatusPayload(
        enabled=enabled,
        configured=False,
        active_implementation=active_impl,
        missing_required=[],
        details={
            "missing_dependencies": missing,
            "dependency_auto_install": True,
            "dependency_install_offer": _format_dependency_install_offer(
                missing,
                install_commands,
                dep_labels,
            ),
        },
    )


def status_hook(project_root: Path | None = None) -> ComponentStatusPayload:
    """Back-compat alias for the component status hook dotted path."""
    return status_payload(project_root)


register()
