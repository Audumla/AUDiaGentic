"""OpenCode model config renderer."""
from __future__ import annotations

from typing import Any

from audiagentic.components.providers.services.catalog.models import MaterializedModelEntry


def render_opencode_model_entry(entry: MaterializedModelEntry) -> tuple[str, dict[str, Any]]:
    """Render a provider-neutral model entry into OpenCode's custom provider shape."""
    endpoint = entry.endpoint
    provider_overrides = endpoint.get("provider-overrides") or {}
    provider_id = str(provider_overrides.get("provider-id") or entry.source_id)
    model_id = entry.model_id

    payload: dict[str, Any] = {
        "provider_id": provider_id,
        "provider_name": provider_id,
        "npm": "@ai-sdk/openai-compatible",
        "model_id": model_id,
        "managed_id": entry.managed_id,
        "name": entry.visible_name,
    }
    if base_url := endpoint.get("base-url"):
        payload["baseURL"] = base_url
    if entry.auth_ref:
        if entry.auth_ref.startswith("env:"):
            payload["apiKey"] = "{" + entry.auth_ref + "}"
        else:
            payload["apiKey"] = entry.auth_ref
    limit: dict[str, int] = {}
    if context := entry.limits.get("context-window"):
        limit["context"] = int(context)
    if output := entry.limits.get("max-output-tokens"):
        limit["output"] = int(output)
    if limit:
        payload["limit"] = limit
    return (entry.visible_name, payload)
