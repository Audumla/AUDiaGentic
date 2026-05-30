"""Track AUDiaGentic-owned provider MCP entries by stable managed id."""
from __future__ import annotations

import json
from pathlib import Path


def _registry_path(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "providers" / "managed-mcp-servers.json"


def load_managed_mcp_registry(project_root: Path) -> dict[str, dict[str, str]]:
    path = _registry_path(project_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    providers = payload.get("providers", {})
    if not isinstance(providers, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for provider_id, managed in providers.items():
        if not isinstance(managed, dict):
            continue
        result[provider_id] = {
            str(managed_id): str(server_name)
            for managed_id, server_name in managed.items()
            if isinstance(managed_id, str) and isinstance(server_name, str)
        }
    return result


def save_managed_mcp_registry(project_root: Path, registry: dict[str, dict[str, str]]) -> None:
    path = _registry_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract-version": "v1",
        "providers": registry,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
