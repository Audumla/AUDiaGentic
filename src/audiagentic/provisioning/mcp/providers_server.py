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

# Known provider IDs — derived from surfaces registry without importing it at server init.
_KNOWN_PROVIDERS = (
    "claude",
    "codex",
    "cline",
    "copilot",
    "gemini",
    "opencode",
    "qwen",
    "local-openai",
)


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

        all_ids = set(_KNOWN_PROVIDERS) | configured_ids | catalog_ids

        result = []
        for provider_id in sorted(all_ids):
            catalog = _read_catalog(project_root, provider_id)
            entry: dict[str, Any] = {
                "provider_id": provider_id,
                "known": provider_id in _KNOWN_PROVIDERS,
                "configured": provider_id in configured_ids,
                "has_catalog": catalog is not None,
            }
            if catalog is not None:
                entry["catalog_model_count"] = len(catalog.get("models", []))
                entry["catalog_fetched_at"] = catalog.get("fetched-at")
                entry["catalog_stale"] = catalog_is_stale(catalog, max_age_hours=24)
            result.append(entry)

        return {
            "project_root": str(project_root),
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

        return {
            "provider_id": provider_id,
            "project_root": str(project_root),
            "configured": config is not None,
            "config": config,
            "catalog": catalog,
            "catalog_stale": catalog_is_stale(catalog, max_age_hours=24) if catalog else None,
        }

    @mcp.tool(description="List model IDs from a provider's runtime catalog.")
    def list_provider_models(provider_id: str) -> dict[str, Any]:
        project_root = _project_root()
        catalog = _read_catalog(project_root, provider_id)
        if catalog is None:
            return {"provider_id": provider_id, "models": [], "error": "no catalog found"}
        models = [
            {
                "model_id": m.get("model-id"),
                "label": m.get("label"),
                "context_window": m.get("context-window"),
            }
            for m in catalog.get("models", [])
        ]
        return {
            "provider_id": provider_id,
            "fetched_at": catalog.get("fetched-at"),
            "models": models,
        }

    return mcp


def main() -> int:
    build_server().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
