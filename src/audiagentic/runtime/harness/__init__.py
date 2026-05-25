"""Harness facade — single import surface for all harness operations.

All callers outside the harness package should import from here, not from
harness.pi.* directly. This keeps Pi as one implementation detail behind a
stable interface, making harness substitution a localised change.
"""
from __future__ import annotations

from pathlib import Path

# --- install / lifecycle ---
from .pi.install import (
    build_runtime_sync,
    install_to,
    refresh_harness_config_if_installed,
    refresh_materialized_agent_config,
    request_runtime_reload,
    uninstall_from,
)

# --- runner interface ---
from .pi.runner import (
    AgentContext,
    RunnerParams,
    build_global_context,
    env_flag,
    run_agent,
    translate_agent_args,
)


def default_config_path() -> Path:
    """Return the harness default config path (source-tree template)."""
    from .pi.install.constants import _HARNESS_CONFIG
    return _HARNESS_CONFIG


def version_info() -> dict[str, str | None]:
    """Return harness component version strings."""
    from .pi.install.constants import AGENT_MCP_ADAPTER_VERSION, AGENT_VERSION
    return {
        "agent": AGENT_VERSION,
        "mcp_adapter": AGENT_MCP_ADAPTER_VERSION,
    }


def query_rig_server_version(bin_dir: Path, timeout: float = 10.0) -> str | None:
    """Query the llama-server binary version string."""
    from .pi.runner.smoke import query_server_version
    return query_server_version(bin_dir, timeout=timeout)


def load_active_profile(
    profiles_path: Path | None,
    model: str,
) -> tuple[str, dict[str, object]]:
    """Load and resolve the active rig model profile."""
    from .pi.runner.models import load_model_profile
    return load_model_profile(profiles_path, model)


def load_pi_config(project_root: Path | None = None) -> dict:
    """Load Pi-specific harness config (pi.yaml). Only used by Pi-aware callers."""
    from .pi.install.constants import load_pi_config as _load
    return _load(project_root=project_root)
