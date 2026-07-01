"""Claude catalog functions."""
from __future__ import annotations

import json
import subprocess
from typing import Any


def _fetch_claude_catalog(provider_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch models via `claude models --output-format json`."""
    try:
        result = subprocess.run(
            subprocess.list2cmdline(["claude", "models", "--output-format", "json"]),
            shell=True, capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        raw = json.loads(result.stdout)
    except (OSError, json.JSONDecodeError):
        return []

    entries = raw.get("data", raw) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []

    result = []
    for entry in entries:
        model_id = entry.get("id") or entry.get("model_id", "")
        if not model_id:
            continue
        result.append({
            "model-id": model_id,
            "display-name": entry.get("display_name") or entry.get("name") or model_id,
            "status": "active",
            "supports-structured-output": True,
            "context-window": max(int(entry.get("context_window") or 200_000), 1),
        })
    return result
