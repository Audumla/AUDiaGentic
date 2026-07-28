"""Validated reads for the shared harness configuration document.

This is configuration policy, not runtime orchestration.  Both the generic
harness runtime and provider materialization need the same validated rig port,
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


def require_harness_rig_port(harness_cfg: dict[str, Any]) -> int:
    """Return the configured embedded-rig port or raise a stable config error."""
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


__all__ = ["require_harness_rig_port"]
