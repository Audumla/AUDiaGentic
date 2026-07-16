"""Pi model config managed-config adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_pi_models(config_path: Path) -> dict[str, tuple[str, Any]]:
    """Read pi's models.json and return managed_id -> (name, payload)."""
    if not config_path.is_file():
        return {}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    result: dict[str, tuple[str, Any]] = {}
    for model in data.get("models", []):
        mid = model.get("managed_id") or model.get("model_id", "")
        if not mid:
            continue
        name = model.get("visible_name", model.get("model_id", ""))
        result[mid] = (name, dict(model))
    return result


def write_pi_models(
    config_path: Path,
    desired: dict[str, tuple[str, Any]],
) -> None:
    """Write pi's models.json from the managed-config desired dict.

    Preserves any non-AUDiaGentic-owned entries already in the file.
    """
    current_data = {}
    if config_path.is_file():
        current_data = json.loads(config_path.read_text(encoding="utf-8"))
    existing_models = {m.get("managed_id") or m.get("model_id", ""): m for m in current_data.get("models", [])}
    models_list = list(existing_models.values())
    seen_ids = set(existing_models.keys())
    for mid, (name, payload) in desired.items():
        entry = dict(payload)
        entry["managed_id"] = mid
        if mid in existing_models:
            idx = models_list.index(existing_models[mid])
            models_list[idx] = entry
        else:
            models_list.append(entry)
            seen_ids.add(mid)
    current_data["models"] = models_list
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(current_data, indent=2), encoding="utf-8")


def remove_pi_model(config_path: Path, managed_id: str) -> bool:
    """Remove one model entry from pi's models.json. Returns True if removed."""
    if not config_path.is_file():
        return False
    data = json.loads(config_path.read_text(encoding="utf-8"))
    original_len = len(data.get("models", []))
    data["models"] = [
        m for m in data.get("models", [])
        if (m.get("managed_id") or m.get("model_id", "")) != managed_id
    ]
    removed = len(data["models"]) < original_len
    if removed:
        config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return removed
