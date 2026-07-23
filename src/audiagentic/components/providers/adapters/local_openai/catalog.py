"""Local OpenAI catalog functions."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from audiagentic.components.providers.services.secrets import resolve_secret_ref
from audiagentic.foundation.contracts.errors import AudiaGenticError

_logger = logging.getLogger(__name__)


# Upstream OpenAI-compatible /v1/models "status"-shaped values mapped onto the
# provider-model-catalog.schema.json enum (active|deprecated|experimental).
# Table lookup per arch-standards §2 — no if/elif on status strings.
_STATUS_MAP: dict[str, str] = {
    "available": "active",
    "active": "active",
    "ready": "active",
    "deprecated": "deprecated",
    "sunset": "deprecated",
    "experimental": "experimental",
    "preview": "experimental",
    "beta": "experimental",
}
_DEFAULT_STATUS = "active"

# Fallback used when an upstream model omits context length entirely.
_DEFAULT_CONTEXT_WINDOW = 4096


def _normalize_status(raw: Any) -> str:
    if not isinstance(raw, str):
        return _DEFAULT_STATUS
    return _STATUS_MAP.get(raw.strip().lower(), _DEFAULT_STATUS)


def _normalize_context_window(raw: Any, provider_cfg: dict[str, Any]) -> int:
    if isinstance(raw, bool):
        raw = None
    if isinstance(raw, int) and raw >= 1:
        return raw
    override = provider_cfg.get("context-window-fallback") or provider_cfg.get(
        "context-window"
    )
    if isinstance(override, int) and not isinstance(override, bool) and override >= 1:
        return override
    return _DEFAULT_CONTEXT_WINDOW


def _fetch_catalog(provider_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch available models from the OpenAI-compatible endpoint."""
    base_url = (
        provider_cfg.get("api-base-url")
        or provider_cfg.get("apiBaseUrl")
        or provider_cfg.get("api_base_url")
        or "https://api.openai.com"
    )
    secret_ref = provider_cfg.get("auth-ref") or provider_cfg.get("api-key-ref")
    try:
        api_key = resolve_secret_ref(secret_ref) if secret_ref else None
    except AudiaGenticError:
        _logger.warning(
            "local-openai catalog: secret resolution failed — returning empty catalog",
            exc_info=True,
        )
        return []

    url = f"{base_url}/v1/models"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            if resp.status != 200:
                _logger.warning(
                    "local-openai catalog: unexpected HTTP %s from %s — returning empty",
                    resp.status,
                    url,
                )
                return []
            data = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(data)
    except urllib.error.HTTPError as http_err:
        _logger.warning(
            "local-openai catalog: HTTP error %s %s from %s — returning empty",
            http_err.code,
            http_err.reason,
            url,
            exc_info=True,
        )
        return []
    except (urllib.error.URLError, OSError, json.JSONDecodeError, Exception):
        _logger.warning(
            "local-openai catalog: fetch failed from %s — returning empty",
            url,
            exc_info=True,
        )
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
            "status": _normalize_status(m.get("status")),
            "supports-structured-output": bool(m.get("supports-structured-output", False)),
            "context-window": _normalize_context_window(
                m.get("context-window") or m.get("context_length"), provider_cfg
            ),
        })

    return result
