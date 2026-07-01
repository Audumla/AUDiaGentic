"""Local OpenAI catalog functions."""
from __future__ import annotations

import json
import urllib.request
from typing import Any


def _fetch_catalog(provider_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch available models from the OpenAI-compatible endpoint."""
    base_url = (
        provider_cfg.get("api-base-url")
        or provider_cfg.get("apiBaseUrl")
        or provider_cfg.get("api_base_url")
        or "https://api.openai.com"
    )
    api_key = (
        provider_cfg.get("api-key")
        or provider_cfg.get("apiKey")
        or provider_cfg.get("api_key")
        or provider_cfg.get("OPENAI_API_KEY")
    )

    url = f"{base_url}/v1/models"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            if resp.status != 200:
                return []
            data = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(data)
    except Exception:
        return []

    models_data = payload.get("data", [])
    if not isinstance(models_data, list):
        return []

    result = []
    for m in models_data:
        if not isinstance(m, dict):
            continue
        model_id = m.get("id", "")
        if not model_id:
            continue
        result.append({
            "model-id": str(model_id),
            "display-name": str(m.get("name", model_id)),
            "status": "available",
            "supports-structured-output": False,
            "context-window": None,
        })

    return result
