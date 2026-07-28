"""Pi model config renderer — converts MaterializedModelEntry to pi native shape."""

from __future__ import annotations

from typing import Any

from audiagentic.components.providers.services.catalog.models import MaterializedModelEntry


def render_pi_model_entry(entry: MaterializedModelEntry) -> tuple[str, dict[str, Any]]:
    """Render one model entry for pi's models.json format.

    Returns (name, payload) where payload is the object that goes into
    the provider's config file. The name is used as the key in the managed
    config container; the payload contains provider-native fields.

    Credential wiring (MO19): entry.auth_ref is deliberately NOT wired here.
    Pi's models.json schema uses a literal ``apiKey`` string — no env-var
    reference syntax exists (PROVIDER_CAPABILITY_REFERENCE/harnesses/profiles/pi.md:
    custom endpoints require ``apiKey`` as a structured JSON field; native
    vendor keys are injected via env vars at launch, not via config). Per the
    SECRET POSTURE rule, Pi is BLOCKED for credential injection until a
    sponsor-approved secret-materialization decision exists. Do not write
    a literal key.
    """
    endpoint = entry.endpoint
    overrides = endpoint.get("provider-overrides") or {}
    payload: dict[str, Any] = {
        "provider_id": str(overrides.get("provider-id") or entry.source_id),
        "baseUrl": endpoint.get("base-url", ""),
        "api": "openai-completions",
        "apiKey": "dummy",
        "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": False},
        "model_id": entry.model_id,
        "visible_name": entry.visible_name,
        "contextWindow": int(entry.limits.get("context-window", 262144)),
        "maxTokens": int(entry.limits.get("max-output-tokens", 4096)),
    }
    return (entry.visible_name, payload)
