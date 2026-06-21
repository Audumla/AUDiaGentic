"""Rig model profile resolution.

Loads and resolves model profiles from the rig config (rig.yaml).
Used by any harness that launches the embedded rig.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error

logger = logging.getLogger(__name__)


def _rig_model_error(code_number: int, message: str, **details: object) -> AudiaGenticError:
    return make_error(
        prefix="CFG",
        component="RIG",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def load_model_profile(
    requested: str | None,
    model: str,
    rig_config: Path | None = None,
) -> tuple[str, dict[str, object]]:
    """Resolve a model profile from the rig config.

    Returns (profile_name, profile_dict). Raises AudiaGenticError if not found.
    rig_config defaults to the package-bundled rig.yaml.
    """
    from audiagentic.runtime.rig.embedded.config import (
        load_rig_model,
        load_rig_profiles,
        resolve_profile_definition,
    )

    if rig_config is None:
        from audiagentic.runtime.harness.paths import _RIG_CONFIG
        rig_config = _RIG_CONFIG

    data = load_rig_profiles(rig_config)
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise _rig_model_error(1, f"Invalid rig config: {rig_config}", path=str(rig_config))

    rig_profile, rig_model_id = load_rig_model(rig_config)
    target = (
        requested
        or os.environ.get("AUDIAGENTIC_RIG_MODEL_PROFILE")
        or os.environ.get("AUDIAGENTIC_AG_MODEL_PROFILE")
    )
    if target == rig_model_id:
        target = rig_profile
    if not target:
        if model in models:
            target = model
        elif model == rig_model_id:
            target = rig_profile
    if not target:
        raise _rig_model_error(
            2,
            f"Model profile not found: {model}. "
            f"Set AUDIAGENTIC_AG_MODEL, set model in harness config, or ensure "
            f"the model name matches an entry in {rig_config}.",
            model=model,
            path=str(rig_config),
        )
    if target not in models:
        raise _rig_model_error(3, f"Model profile not found: {target}", profile=target, path=str(rig_config))
    return target, resolve_profile_definition(target, rig_config)


def query_server_version(bin_dir: Path, timeout: float = 10.0) -> str | None:
    """Return the llama-server version string, or None if binary is absent."""
    import subprocess
    import sys as _sys

    from audiagentic.foundation.system.process import executable_command
    from audiagentic.runtime.rig.embedded.process import resolve_platform_dirs
    try:
        server_dir, _ = resolve_platform_dirs(bin_dir)
        server_bin = server_dir / ("llama-server.exe" if _sys.platform == "win32" else "llama-server")
        if not server_bin.exists():
            return None
        result = subprocess.run(
            [*executable_command(server_bin), "--version"],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            return (result.stdout + result.stderr).strip().split("\n")[0]
    except Exception:
        logger.warning("Failed to get server version from %s", bin_dir, exc_info=True)
    return None


def query_server_model(endpoint: str, timeout: float = 10.0) -> str | None:
    """Return the first model ID reported by the rig's /models endpoint."""
    from audiagentic.runtime.rig.http import probe_models_endpoint
    probe = probe_models_endpoint(endpoint, timeout=timeout)
    return None if probe is None else probe.first_model_id
