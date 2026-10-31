"""Harness-generic config helpers.

Reads the layered ag.yaml harness config and extracts well-known keys.
These helpers are shared across all harness implementations — no harness
should import config readers from another harness.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.config.harness import require_harness_endpoint
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error

__all__ = ["require_harness_endpoint"]


def _harness_config_error(code_number: int, message: str, **details: object) -> AudiaGenticError:
    return make_error(
        prefix="CFG",
        component="HCFG",
        number=code_number,
        kind="harness-config",
        message=message,
        details=details,
    )


def load_harness_config(project_root: Path | None = None) -> dict:
    from audiagentic.foundation.config.harness_settings import harness_ag_config

    return harness_ag_config(project_root)


def require_harness_provider(harness_cfg: dict) -> str:
    provider = harness_cfg.get("endpoint", {}).get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise _harness_config_error(
            1,
            "Harness config missing required 'provider'. "
            "Set harness.endpoint in your settings (audiagentic config set).",
            field="endpoint.provider",
        )
    return provider.strip()


def require_smoke_timeout(harness_cfg: dict) -> float:
    smoke_cfg = harness_cfg.get("smoke")
    if not isinstance(smoke_cfg, dict):
        raise _harness_config_error(
            5,
            "Harness config missing required 'smoke' section. "
            "Expected the packaged defaults (provisioning/foundation/settings.yaml, harness section) to define smoke.timeout.",
            field="smoke",
        )
    raw = smoke_cfg.get("timeout")
    if raw is None:
        raise _harness_config_error(
            6,
            "Harness config missing required 'smoke.timeout'. "
            "Set harness.endpoint in your settings (audiagentic config set).",
            field="smoke.timeout",
        )
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise _harness_config_error(
            7,
            f"Invalid harness config value for smoke.timeout: {raw!r}",
            value=raw,
        ) from exc


