"""Harness-generic config helpers.

Reads the layered ag.yaml harness config and extracts well-known keys.
These helpers are shared across all harness implementations — no harness
should import config readers from another harness.
"""
from __future__ import annotations

import os
from pathlib import Path

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


def load_harness_config(project_root: Path | None = None) -> dict:
    from audiagentic.foundation.config import load_layered_config
    from audiagentic.runtime.harness.paths import _HARNESS_CONFIG
    return load_layered_config(
        pkg_default_path=_HARNESS_CONFIG,
        project_root=project_root,
        namespace="harness/ag",
    )


def require_harness_provider(harness_cfg: dict) -> str:
    provider = harness_cfg.get("rig", {}).get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise _harness_config_error(
            1,
            "Harness config missing required 'provider'. "
            "Set it in config/provisioning/harness/ag.yaml or override config.",
            field="rig.provider",
        )
    return provider.strip()


def require_harness_rig_port(harness_cfg: dict) -> int:
    rig_cfg = harness_cfg.get("rig")
    if not isinstance(rig_cfg, dict):
        raise _harness_config_error(
            2,
            "Harness config missing required 'rig' section. "
            "Expected config/provisioning/harness/ag.yaml to define rig.port.",
            field="rig",
        )
    raw = rig_cfg.get("port")
    if raw is None:
        raise _harness_config_error(
            3,
            "Harness config missing required 'rig.port'. "
            "Set it in config/provisioning/harness/ag.yaml or override config.",
            field="rig.port",
        )
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise _harness_config_error(4, f"Invalid harness config value for rig.port: {raw!r}", value=raw) from exc


def require_smoke_timeout(harness_cfg: dict) -> float:
    smoke_cfg = harness_cfg.get("smoke")
    if not isinstance(smoke_cfg, dict):
        raise _harness_config_error(
            5,
            "Harness config missing required 'smoke' section. "
            "Expected config/provisioning/harness/ag.yaml to define smoke.timeout.",
            field="smoke",
        )
    raw = smoke_cfg.get("timeout")
    if raw is None:
        raise _harness_config_error(
            6,
            "Harness config missing required 'smoke.timeout'. "
            "Set it in config/provisioning/harness/ag.yaml or override config.",
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


def env_flag(name: str, default: bool = False) -> bool:
    truthy = {"1", "true", "yes", "on"}
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in truthy
