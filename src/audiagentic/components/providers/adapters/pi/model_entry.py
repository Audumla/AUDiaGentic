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
    payload: dict[str, Any] = {
        "model_id": entry.model_id,
        "visible_name": entry.visible_name,
        "connector": entry.connector,
    }
    if endpoint.get("base-url"):
        payload["base_url"] = endpoint["base-url"]
    if endpoint.get("single-model"):
        payload["compat"] = True
    if connector_opts := endpoint.get("connector-options"):
        payload.update(connector_opts)
    if limits := entry.limits:
        payload["limits"] = dict(limits)
    # auth_ref not wired — Pi requires literal apiKey; blocked per SECRET
    # POSTURE rule until sponsor-approved secret-materialization decision.
    return (entry.visible_name, payload)
