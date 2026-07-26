"""Runtime status helpers for the core session component.

RU02: session component never queries rig internals directly —
runtime resolves ProviderSessionInfo and passes it in as input.
The session functions just display what the provider gives them.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from audiagentic.components.providers.contracts.session_status import (
    ProviderSessionInfo,
)
from audiagentic.foundation.config import load_layered_config
from audiagentic.foundation.contracts.errors import make_error

logger = logging.getLogger(__name__)


def versions(ctx: ProviderSessionInfo) -> dict[str, Any]:
    """Return version info from provider session info."""
    payload: dict[str, Any] = {
        "audiagentic": ctx.agent_version or "unknown",
        "mcp_adapter": ctx.mcp_adapter_version or "unknown",
    }
    if ctx.server_version:
        payload["llama_server"] = ctx.server_version
    return payload


def model_info(ctx: ProviderSessionInfo) -> dict[str, Any]:
    """Return model info from provider session info."""
    configured = ctx.configured_model
    if not configured or not configured.strip():
        raise make_error(
            prefix="CFG",
            component="session",
            number=1,
            kind="session",
            message="missing configured model in harness config",
            details={},
        )
    info: dict[str, Any] = {
        "configured_model": configured,
        "profile_name": ctx.model_profile_name,
        "model_file": ctx.model_file,
    }
    if ctx.server_version:
        info["server_version"] = ctx.server_version
    return info


def harness_config(ctx: ProviderSessionInfo) -> dict[str, Any]:
    """Return harness config from provider session info."""
    from pathlib import Path

    from audiagentic.foundation.paths.home import global_harness_runtime

    cfg_path = ctx.config_path
    if not cfg_path:
        raise make_error(
            prefix="RES",
            component="session",
            number=4,
            kind="session",
            message="no harness config path available",
            details={},
        )
    harness_cfg = load_layered_config(
        pkg_default_path=Path(cfg_path),
        project_root=None,
        namespace="harness/ag",
    )
    payload: dict[str, Any] = {
        "config": harness_cfg,
        "config_path": cfg_path,
    }

    # Models JSON is pre-resolved by runtime in the context
    if ctx.models_data is not None:
        payload["models"] = ctx.models_data
    else:
        # Check if harness exists but models.json is missing
        harness = global_harness_runtime()
        if harness:
            models_path = harness / "agent" / "models.json"
            raise make_error(
                prefix="RES",
                component="session",
                number=1,
                kind="session",
                message="missing materialized models config",
                details={"path": str(models_path)},
            )
    return payload


def endpoint_info(ctx: ProviderSessionInfo) -> dict[str, Any]:
    """Return endpoint info from provider session info."""
    base_url = ctx.base_url or os.environ.get("AUDIAGENTIC_AG_BASE_URL")
    if not base_url:
        return {"base_url": None, "endpoint_reachable": False}

    info: dict[str, Any] = {
        "base_url": base_url,
        "rig_type": os.environ.get("AUDIAGENTIC_RIG_TYPE", "unknown"),
        "rig_profile": os.environ.get("AUDIAGENTIC_RIG_PROFILE"),
    }

    try:
        import urllib.request

        with urllib.request.urlopen(f"{base_url}/models", timeout=5) as resp:
            info["endpoint_reachable"] = resp.status == 200
    except Exception:
        logger.warning("Failed to reach endpoint at %s", base_url, exc_info=True)
        info["endpoint_reachable"] = False

    return info
