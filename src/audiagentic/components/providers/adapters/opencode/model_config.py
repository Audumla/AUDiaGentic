"""OpenCode model config managed-config adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import atomic_write_json


def _registry_path(config_path: Path) -> Path:
    return config_path.with_name("audiagentic-models.json")


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        return {"$schema": "https://opencode.ai/config.json"}
    return json.loads(config_path.read_text(encoding="utf-8"))


def _load_registry(config_path: Path) -> dict[str, Any]:
    registry = _registry_path(config_path)
    if not registry.is_file():
        return {"entries": {}}
    loaded = json.loads(registry.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {"entries": {}}


def _write_registry(config_path: Path, registry: dict[str, Any]) -> None:
    atomic_write_json(_registry_path(config_path), registry, sort_keys=True)


def read_opencode_models(config_path: Path) -> dict[str, tuple[str, Any]]:
    """Read AUDiaGentic-managed custom model entries from opencode.json."""
    data = _load_config(config_path)
    registry = _load_registry(config_path)
    entries = registry.get("entries") if isinstance(registry.get("entries"), dict) else {}
    result: dict[str, tuple[str, Any]] = {}
    for _managed_id, marker in entries.items():
        if not isinstance(marker, dict):
            continue
        provider_id = marker.get("provider_id")
        model_id = marker.get("model_id")
        if not isinstance(provider_id, str) or not isinstance(model_id, str):
            continue
        provider = (data.get("provider") or {}).get(provider_id)
        if not isinstance(provider, dict):
            continue
        model = (provider.get("models") or {}).get(model_id)
        if not isinstance(model, dict):
            continue
        payload = dict(model)
        payload["provider_id"] = provider_id
        payload["model_id"] = model_id
        result[str(model.get("name") or model_id)] = payload
    return result


def write_opencode_models(
    config_path: Path,
    desired: dict[str, Any],
) -> None:
    """Write desired model entries while preserving unrelated OpenCode config."""
    data = _load_config(config_path)
    providers = data.setdefault("provider", {})
    registry = _load_registry(config_path)
    registry_entries = registry.setdefault("entries", {})
    for _name, payload in desired.items():
        provider_id = str(payload["provider_id"])
        model_id = str(payload["model_id"])
        managed_id = str(payload["managed_id"])
        provider = providers.setdefault(provider_id, {})
        provider.setdefault("npm", payload.get("npm", "@ai-sdk/openai-compatible"))
        provider.setdefault("name", payload.get("provider_name", provider_id))
        options = provider.setdefault("options", {})
        if payload.get("baseURL"):
            options["baseURL"] = payload["baseURL"]
        models = provider.setdefault("models", {})
        entry = dict(payload)
        managed_id = str(entry.pop("managed_id"))
        for key in ("provider_id", "model_id", "provider_name", "npm", "baseURL", "apiKey"):
            entry.pop(key, None)
        models[model_id] = entry
        registry_entries[managed_id] = {
            "provider_id": provider_id,
            "model_id": model_id,
            "name": _name,
        }
    atomic_write_json(config_path, data, sort_keys=False)
    _write_registry(config_path, registry)


def remove_opencode_model(config_path: Path, name: str) -> bool:
    """Remove one AUDiaGentic-managed model entry from opencode.json."""
    if not config_path.is_file():
        return False
    data = _load_config(config_path)
    registry = _load_registry(config_path)
    registry_entries = registry.get("entries") if isinstance(registry.get("entries"), dict) else {}
    marker = None
    managed_id = None
    if isinstance(registry_entries, dict):
        for candidate_id, candidate in registry_entries.items():
            if isinstance(candidate, dict) and candidate.get("name") == name:
                marker = candidate
                managed_id = candidate_id
                break
    removed = False
    if isinstance(marker, dict):
        provider_id = marker.get("provider_id")
        model_id = marker.get("model_id")
        provider = (data.get("provider") or {}).get(provider_id)
        if isinstance(provider, dict) and isinstance(model_id, str):
            models = provider.get("models") or {}
            if model_id in models:
                del models[model_id]
                removed = True
        if managed_id is not None:
            del registry_entries[managed_id]
    if removed:
        atomic_write_json(config_path, data, sort_keys=False)
    if isinstance(registry_entries, dict):
        _write_registry(config_path, registry)
    return removed
