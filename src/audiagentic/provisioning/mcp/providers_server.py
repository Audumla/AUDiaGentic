"""AUDiaGentic providers component MCP server.

Exposes provider configuration status and runtime catalog info to the Pi TUI.
Reads AUDIAGENTIC_REPO_ROOT from env to locate the target project.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

from audiagentic.foundation.config.provider_catalog import (
    catalog_is_stale,
    runtime_catalog_path,
    runtime_catalog_root,
)


def _descriptor_ids() -> frozenset[str]:
    """Return provider IDs from the descriptor registry (lazy import, avoids init cost)."""
    from audiagentic.interoperability.providers.descriptors.registry import all_descriptors
    return frozenset(all_descriptors())


def _project_root() -> Path:
    repo_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if not repo_root:
        raise RuntimeError("AUDIAGENTIC_REPO_ROOT not set")
    return Path(repo_root)


def _providers_config_path(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "config" / "runtime" / "providers.yaml"


def _read_providers_yaml(project_root: Path) -> dict[str, Any] | None:
    path = _providers_config_path(project_root)
    if not path.exists():
        return None
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None


def _read_catalog(project_root: Path, provider_id: str) -> dict[str, Any] | None:
    path = runtime_catalog_path(project_root, provider_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def build_server() -> FastMCP:
    mcp = FastMCP(
        "audiagentic-providers",
        instructions=(
            "AUDiaGentic providers component server. "
            "Use list_providers to see all providers and their status, "
            "provider_status to inspect a specific provider's runtime catalog."
        ),
    )

    @mcp.tool(description="List all known providers and their configuration/catalog status.")
    def list_providers() -> dict[str, Any]:
        project_root = _project_root()
        providers_yaml = _read_providers_yaml(project_root)
        catalogs_dir = runtime_catalog_root(project_root)

        configured_ids: set[str] = set()
        if providers_yaml:
            configured_ids = set(providers_yaml.get("providers", {}).keys())

        catalog_ids: set[str] = set()
        if catalogs_dir.exists():
            catalog_ids = {p.name for p in catalogs_dir.iterdir() if p.is_dir()}

        descriptor_ids = _descriptor_ids()
        all_ids = descriptor_ids | configured_ids | catalog_ids

        from audiagentic.interoperability.providers.descriptors.registry import (
            _list_vscode_extensions,
        )
        from audiagentic.interoperability.providers.descriptors.registry import (
            all_descriptors as _all_desc,
        )
        descriptors = _all_desc()
        is_vscode_project = (project_root / ".vscode").exists()
        installed_extensions: list[str] | None = _list_vscode_extensions(allow_probe=True) if is_vscode_project else None

        result = []
        for provider_id in sorted(all_ids):
            catalog = _read_catalog(project_root, provider_id)
            cfg = providers_yaml.get("providers", {}).get(provider_id, {}) if providers_yaml else {}
            desc = descriptors.get(provider_id)
            install_method = (desc.cli_install.package_manager if desc and desc.cli_install else "") or ""

            vscode_exts: list[dict[str, Any]] = []
            if desc and desc.vscode_extensions and is_vscode_project:
                for ext in desc.vscode_extensions:
                    vscode_exts.append({
                        "extension_id": ext.extension_id,
                        "display_name": ext.display_name,
                        "installed": (
                            ext.extension_id.lower() in installed_extensions
                            if installed_extensions is not None else False
                        ),
                    })

            entry: dict[str, Any] = {
                "provider_id": provider_id,
                "known": provider_id in descriptor_ids,
                "configured": provider_id in configured_ids,
                "enabled": cfg.get("enabled", False),
                "install_method": install_method,
                "access_mode": cfg.get("access-mode", ""),
                "default_model": cfg.get("default-model", ""),
                "has_catalog": catalog is not None,
                "catalog_fetched_at": catalog.get("fetched-at", "") if catalog else "",
                "catalog_model_count": len(catalog.get("models", [])) if catalog else 0,
                "catalog_stale": catalog_is_stale(catalog, max_age_hours=24) if catalog else False,
            }
            if vscode_exts:
                entry["vscode_extensions"] = vscode_exts
            result.append(entry)

        return {
            "project_root": str(project_root),
            "vscode_project": is_vscode_project,
            "providers_yaml_exists": providers_yaml is not None,
            "providers": result,
        }

    @mcp.tool(description="Return detailed status for a specific provider including catalog contents.")
    def provider_status(provider_id: str) -> dict[str, Any]:
        project_root = _project_root()
        providers_yaml = _read_providers_yaml(project_root)

        config: dict[str, Any] | None = None
        if providers_yaml:
            config = providers_yaml.get("providers", {}).get(provider_id)

        catalog = _read_catalog(project_root, provider_id)

        from audiagentic.interoperability.providers.descriptors.registry import (
            _list_vscode_extensions,
            get_descriptor,
        )
        desc = get_descriptor(provider_id)
        install_method = (desc.cli_install.package_manager if desc and desc.cli_install else "") or ""
        is_vscode_project = (project_root / ".vscode").exists()

        vscode_exts: list[dict[str, Any]] = []
        if desc and desc.vscode_extensions and is_vscode_project:
            installed_extensions = _list_vscode_extensions()
            for ext in desc.vscode_extensions:
                vscode_exts.append({
                    "extension_id": ext.extension_id,
                    "display_name": ext.display_name,
                    "installed": (
                        ext.extension_id.lower() in installed_extensions
                        if installed_extensions is not None else False
                    ),
                })

        result: dict[str, Any] = {
            "provider_id": provider_id,
            "project_root": str(project_root),
            "vscode_project": is_vscode_project,
            "configured": config is not None,
            "enabled": config.get("enabled", False) if config else False,
            "install_method": install_method,
            "access_mode": config.get("access-mode", "") if config else "",
            "default_model": config.get("default-model", "") if config else "",
            "config": config or {},
            "catalog": catalog or {},
            "catalog_stale": catalog_is_stale(catalog, max_age_hours=24) if catalog else False,
        }
        if vscode_exts:
            result["vscode_extensions"] = vscode_exts
        return result

    @mcp.tool(
        description=(
            "Interrogate a provider: check CLI availability, VS Code extension install status, "
            "permissions model, and which agent files are present in the project."
        )
    )
    def interrogate_provider(provider_id: str) -> dict[str, Any]:
        from audiagentic.interoperability.providers.descriptors import interrogate
        project_root = _project_root()
        return interrogate(provider_id, project_root)

    @mcp.tool(description="List all registered provider descriptors (static metadata).")
    def list_provider_descriptors() -> list[dict[str, Any]]:
        from audiagentic.interoperability.providers.descriptors import all_descriptors
        return [
            {
                "provider_id": d.provider_id,
                "display_name": d.display_name,
                "description": d.description,
                "url": d.url,
                "has_cli": d.cli_probe is not None,
                "cli_probe": d.cli_probe,
                "vscode_extensions": [
                    {"extension_id": e.extension_id, "display_name": e.display_name}
                    for e in d.vscode_extensions
                ],
                "permissions": {
                    "can_write_files": d.permissions.can_write_files,
                    "can_execute_shell": d.permissions.can_execute_shell,
                    "can_browse_web": d.permissions.can_browse_web,
                    "can_read_env": d.permissions.can_read_env,
                    "notes": d.permissions.notes,
                },
                "agent_files": [
                    {"rel_path": f.rel_path, "managed": f.managed, "description": f.description}
                    for f in d.agent_files
                ],
            }
            for d in sorted(all_descriptors().values(), key=lambda x: x.provider_id)
        ]

    @mcp.tool(description="List model IDs from a provider's runtime catalog.")
    def list_provider_models(provider_id: str) -> dict[str, Any]:
        project_root = _project_root()
        catalog = _read_catalog(project_root, provider_id)
        if catalog is None:
            return {"provider_id": provider_id, "models": [], "error": "no catalog found"}
        models = [
            {
                "model_id": m.get("model-id", ""),
                "label": m.get("label", ""),
                "context_window": m.get("context-window", 0),
            }
            for m in catalog.get("models", [])
        ]
        return {
            "provider_id": provider_id,
            "fetched_at": catalog.get("fetched-at"),
            "models": models,
        }

    # --- lifecycle tools (write) ---

    @mcp.tool(
        description=(
            "Install a provider CLI. Pass dry_run=true (default) to see what would run "
            "without touching the host. Pass dry_run=false to execute."
        )
    )
    def install_provider(provider_id: str, dry_run: bool = True) -> dict[str, Any]:
        from audiagentic.interoperability.providers.lifecycle import install_provider_cli
        project_root = _project_root()
        return install_provider_cli(provider_id, dry_run=dry_run, project_root=project_root)

    @mcp.tool(
        description=(
            "Uninstall a provider CLI. Pass dry_run=true (default) to see what would run "
            "without touching the host. Pass dry_run=false to execute."
        )
    )
    def uninstall_provider(provider_id: str, dry_run: bool = True) -> dict[str, Any]:
        from audiagentic.interoperability.providers.lifecycle import uninstall_provider_cli
        project_root = _project_root()
        return uninstall_provider_cli(provider_id, dry_run=dry_run, project_root=project_root)

    @mcp.tool(
        description=(
            "Repair a provider CLI: installs it if missing, no-op if already available. "
            "Pass dry_run=true (default) to preview. Pass dry_run=false to execute."
        )
    )
    def repair_provider(provider_id: str, dry_run: bool = True) -> dict[str, Any]:
        from audiagentic.interoperability.providers.lifecycle import repair_provider_cli
        project_root = _project_root()
        return repair_provider_cli(provider_id, dry_run=dry_run, project_root=project_root)

    @mcp.tool(
        description=(
            "Enable or disable a provider in providers.yaml. "
            "Does not install or uninstall the CLI — use install_provider / uninstall_provider for that."
        )
    )
    def set_provider_enabled(provider_id: str, enabled: bool) -> dict[str, Any]:
        from audiagentic.foundation.config.provider_config import (
            set_provider_enabled as _set_enabled,
        )
        project_root = _project_root()
        _set_enabled(project_root, provider_id, enabled=enabled)
        return {"provider_id": provider_id, "enabled": enabled, "ok": True}

    @mcp.tool(
        description=(
            "Apply managed surface blocks (rules, skills, config) to a provider's agent files. "
            "Idempotent — safe to run at any time. Omit provider_id to apply all providers."
        )
    )
    def apply_provider_surfaces(provider_id: str | None = None) -> dict[str, Any]:
        from audiagentic.interoperability.providers.surfaces.manager import (
            apply_provider_surfaces as _apply,
        )
        project_root = _project_root()
        return _apply(project_root, provider_id=provider_id)

    @mcp.tool(
        description=(
            "Remove stale managed surface blocks from a provider's agent files — "
            "blocks whose contributing component no longer exists. "
            "Omit provider_id to scan all providers."
        )
    )
    def prune_provider_surfaces(provider_id: str | None = None) -> dict[str, Any]:
        from audiagentic.interoperability.providers.surfaces.manager import (
            prune_provider_surfaces as _prune,
        )
        project_root = _project_root()
        return _prune(project_root, provider_id=provider_id)

    @mcp.tool(
        description=(
            "Reconcile a single provider: probe host CLI availability, then sync providers.yaml. "
            "Enables + applies surfaces if CLI found but not enabled; disables + prunes if CLI gone "
            "but still marked enabled. No-op if already in sync."
        )
    )
    def reconcile_provider(provider_id: str) -> dict[str, Any]:
        from audiagentic.interoperability.providers.lifecycle import (
            reconcile_provider as _reconcile,
        )
        project_root = _project_root()
        return _reconcile(provider_id, project_root=project_root)

    @mcp.tool(
        description=(
            "Reconcile all registered providers against host state. "
            "For each provider: enables/disables and applies/prunes surfaces as needed."
        )
    )
    def reconcile_all_providers() -> dict[str, Any]:
        from audiagentic.interoperability.providers.lifecycle import (
            reconcile_all_providers as _reconcile_all,
        )
        project_root = _project_root()
        return _reconcile_all(project_root=project_root)

    return mcp


def main() -> int:
    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
