"""Pi model config managed-config adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import atomic_write_json


def resolve_pi_models_config_path(project_root: Path | None) -> Path:
    """Resolve Pi's models.json path.

    Uses $PI_CODING_AGENT_DIR if set (harness-isolated), otherwise falls back
    to the default user-global location ~/.pi/agent/models.json.
    """
    agent_dir = os.environ.get("PI_CODING_AGENT_DIR")
    if agent_dir:
        return Path(agent_dir) / "models.json"
    return Path.home() / ".pi" / "agent" / "models.json"


def read_pi_models(config_path: Path) -> dict[str, tuple[str, Any]]:
    """Read pi's models.json and return managed_id -> (name, payload)."""
    if not config_path.is_file():
        return {}
    # pi-lens-ignore: ast-grep:unchecked-throwing-call-python
    # pi-lens-ignore: ast-grep:unchecked-throwing-call-python
    data = json.loads(config_path.read_text(encoding="utf-8"))
    result: dict[str, tuple[str, Any]] = {}
    for provider_id, provider in (data.get("providers") or {}).items():
        for model in provider.get("models", []) if isinstance(provider, dict) else []:
            mid = model.get("managed_id") or model.get("model_id", "")
            if mid:
                result[mid] = (str(model.get("name") or model.get("id") or mid), dict(model))
    return result


def write_pi_models(
    config_path: Path,
    desired: dict[str, tuple[str, Any]],
) -> None:
    """Write pi's models.json from the managed-config desired dict.

    Preserves any non-AUDiaGentic-owned entries already in the file.
    """
    current_data = {}
    # pi-lens-ignore: ast-grep:unchecked-throwing-call-python
    if config_path.is_file():
        current_data = json.loads(config_path.read_text(encoding="utf-8"))
    providers = current_data.setdefault("providers", {})
    for name, payload in desired.items():
        entry = dict(payload) if isinstance(payload, dict) else {}
        mid = entry.get("managed_id") or name
        provider_id = str(entry.pop("provider_id"))
        provider = providers.setdefault(provider_id, {})
        for key in ("baseUrl", "api", "apiKey", "compat"):
            provider[key] = entry.pop(key)
        models = provider.setdefault("models", [])
        native = {
            "id": entry.pop("model_id"),
            "name": entry.pop("visible_name"),
            "reasoning": False,
            "input": ["text"],
            "contextWindow": entry.pop("contextWindow"),
            "maxTokens": entry.pop("maxTokens"),
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "managed_id": mid,
        }
        for index, existing in enumerate(models):
            if existing.get("managed_id") == mid:
                models[index] = native
                break
        else:
            models.append(native)
    atomic_write_json(config_path, current_data, sort_keys=False)


def remove_pi_model(config_path: Path, managed_id: str) -> bool:
    """Remove one model entry from pi's models.json. Returns True if removed."""
    # pi-lens-ignore: ast-grep:unchecked-throwing-call-python
    if not config_path.is_file():
        return False
    data = json.loads(config_path.read_text(encoding="utf-8"))
    removed = False
    for provider in (data.get("providers") or {}).values():
        if not isinstance(provider, dict):
            continue
        models = provider.get("models") or []
        kept = [m for m in models if m.get("managed_id") != managed_id]
        removed = removed or len(kept) != len(models)
        provider["models"] = kept
    if removed:
        atomic_write_json(config_path, data, sort_keys=False)
    return removed
