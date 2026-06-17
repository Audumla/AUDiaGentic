"""Runtime status helpers for the core session component."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from audiagentic.runtime.config import load_layered_config

logger = logging.getLogger(__name__)


def versions() -> dict[str, Any]:
    from audiagentic.runtime.harness import query_rig_server_version, version_info
    from audiagentic.runtime.home import global_harness_runtime

    version_payload = version_info()
    payload: dict[str, Any] = {
        "audiagentic": version_payload["agent"],
        "mcp_adapter": version_payload["mcp_adapter"],
    }

    harness = global_harness_runtime()
    if harness and (harness / "rig" / "bin").exists():
        server_ver = query_rig_server_version(harness / "rig" / "bin")
        if server_ver:
            payload["llama_server"] = server_ver
    return payload


def model_info() -> dict[str, Any]:
    from audiagentic.runtime.harness import (
        default_config_path,
        load_active_profile,
        query_rig_server_version,
    )
    from audiagentic.runtime.home import global_harness_runtime

    requested = os.environ.get("AUDIAGENTIC_AG_MODEL")
    if not requested:
        cfg = load_layered_config(
            pkg_default_path=default_config_path(),
            project_root=None,
            namespace="harness/ag",
        )
        requested = cfg.get("model")

    if not isinstance(requested, str) or not requested.strip():
        raise RuntimeError("missing configured model in harness config")

    profile_name, profile = load_active_profile(None, requested)
    info: dict[str, Any] = {
        "configured_model": requested,
        "profile_name": profile_name,
        "model_file": profile.get("model_file"),
    }

    harness = global_harness_runtime()
    if harness and (harness / "rig" / "bin").exists():
        server_ver = query_rig_server_version(harness / "rig" / "bin")
        if server_ver:
            info["server_version"] = server_ver

    return info


def harness_config() -> dict[str, Any]:
    from audiagentic.runtime.harness import default_config_path
    from audiagentic.runtime.home import global_harness_runtime

    harness = global_harness_runtime()
    cfg_path = default_config_path()
    harness_cfg = load_layered_config(
        pkg_default_path=cfg_path,
        project_root=None,
        namespace="harness/ag",
    )
    payload: dict[str, Any] = {
        "config": harness_cfg,
        "config_path": str(cfg_path),
    }

    if harness:
        models_path = harness / "agent" / "models.json"
        if not models_path.exists():
            raise RuntimeError(f"missing materialized models config: {models_path}")
        payload["models_path"] = str(models_path)
        payload["models"] = json.loads(models_path.read_text(encoding="utf-8"))

    return payload


def endpoint_info() -> dict[str, Any]:
    base_url = os.environ.get("AUDIAGENTIC_AG_BASE_URL")
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
