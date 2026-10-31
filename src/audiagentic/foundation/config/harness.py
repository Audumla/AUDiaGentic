"""Validated reads for the shared harness configuration document.

This is configuration policy, not runtime orchestration.  Both the generic
harness runtime and provider materialization need the same validated model-server URL,
so keeping it in foundation prevents a provider -> runtime dependency.
"""
from __future__ import annotations

from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error


def _harness_config_error(code_number: int, message: str, **details: object) -> AudiaGenticError:
    return make_error(
        prefix="CFG",
        component="HCFG",
        number=code_number,
        kind="harness-config",
        message=message,
        details=details,
    )


def require_harness_endpoint(harness_cfg: dict[str, Any]) -> str:
    """Return the configured model-server URL or raise a stable config error."""
    endpoint_cfg = harness_cfg.get("endpoint")
    if not isinstance(endpoint_cfg, dict):
        raise _harness_config_error(
            2,
            "Harness config missing required 'endpoint' section. "
            "Expected config/provisioning/harness/ag.yaml to define endpoint.url.",
            field="endpoint",
        )
    raw = endpoint_cfg.get("url")
    if raw is None:
        raise _harness_config_error(
            3,
            "Harness config missing required 'endpoint.url'. "
            "Set it in config/provisioning/harness/ag.yaml or override config.",
            field="endpoint.url",
        )
    url = str(raw).strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise _harness_config_error(4, "endpoint.url must use http:// or https://", value=raw)
    return url


__all__ = ["require_harness_endpoint"]
