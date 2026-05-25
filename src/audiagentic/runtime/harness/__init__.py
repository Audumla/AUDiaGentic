"""Harness facade — single import surface for all harness operations.

All callers outside the harness package should import from here, not from
harness.<type>.* directly. The active harness is selected by ``harness.type``
in ag.yaml (default: ``pi``). Adding a new harness means:

  1. Create ``runtime/harness/<type>/`` with ``install`` and ``runner`` submodules
     that expose the same interface as ``pi/install`` and ``pi/runner``.
  2. Add the type to ``_REGISTRY`` below.
  3. Set ``harness.type: <type>`` in ag.yaml or a project-local override.
"""
from __future__ import annotations

import importlib
from pathlib import Path

# Re-export concrete types from pi — these are the active harness types until
# a second harness is introduced, at which point RunnerParams moves to this
# module (it is harness-agnostic) and AgentContext becomes a protocol.
from .pi.runner import AgentContext, RunnerParams

# Registry: harness type name → base module path.
_REGISTRY: dict[str, str] = {
    "pi": "audiagentic.runtime.harness.pi",
    # "opencode": "audiagentic.runtime.harness.opencode",  # future
}

def _harness_cfg_path() -> Path:
    from .pi.install.constants import _HARNESS_CONFIG
    return _HARNESS_CONFIG


def get_harness_type(project_root: Path | None = None) -> str:
    """Return the configured harness type for the given project root."""
    from audiagentic.runtime.config import load_layered_config
    cfg = load_layered_config(
        pkg_default_path=_harness_cfg_path(),
        project_root=project_root,
        namespace="harness/ag",
    )
    return cfg.get("harness", {}).get("type", "pi")


def _mod(subpath: str, project_root: Path | None = None):
    t = get_harness_type(project_root)
    if t not in _REGISTRY:
        raise SystemExit(
            f"Unknown harness type {t!r}. "
            f"Supported: {sorted(_REGISTRY)}. "
            f"Set harness.type in ag.yaml."
        )
    return importlib.import_module(f"{_REGISTRY[t]}.{subpath}")


# --- install / lifecycle ---

def install_to(target: Path, project_root: Path | None = None) -> int:
    return _mod("install", project_root).install_to(target, project_root)


def uninstall_from(target: Path) -> int:
    return _mod("install").uninstall_from(target)


def build_runtime_sync(
    *,
    reason: str,
    component_id: str | None = None,
    target: str = "pi-runtime",
) -> dict[str, object]:
    return _mod("install").build_runtime_sync(
        reason=reason, component_id=component_id, target=target
    )


def refresh_harness_config_if_installed(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
) -> bool:
    return _mod("install", project_root).refresh_harness_config_if_installed(
        project_root, reason=reason, component_id=component_id
    )


def refresh_materialized_agent_config(
    target: Path, project_root: Path | None = None
) -> int:
    return _mod("install", project_root).refresh_materialized_agent_config(
        target, project_root
    )


def request_runtime_reload(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
) -> Path:
    return _mod("install", project_root).request_runtime_reload(
        project_root, reason=reason, component_id=component_id
    )


# --- runner interface ---

def build_global_context(
    *, project_root: Path, agent_runtime: Path, enable_mcp: bool
) -> AgentContext:
    return _mod("runner", project_root).build_global_context(
        project_root=project_root,
        agent_runtime=agent_runtime,
        enable_mcp=enable_mcp,
    )


def run_agent(ctx: AgentContext, params: RunnerParams, **kw):
    return _mod("runner", ctx.project_root).run_agent(ctx, params, **kw)


def translate_agent_args(params: RunnerParams) -> list[str]:
    return _mod("runner").translate_agent_args(params)


def env_flag(name: str, default: bool = False) -> bool:
    return _mod("runner").env_flag(name, default)


# --- harness-specific helpers (pi-only until generalised) ---

def query_rig_server_version(bin_dir: Path, timeout: float = 10.0) -> str | None:
    from .pi.runner.agent_run import query_server_version
    return query_server_version(bin_dir, timeout=timeout)


def load_active_profile(
    profiles_path: Path | None,
    model: str,
) -> tuple[str, dict[str, object]]:
    from .pi.runner.models import load_model_profile
    return load_model_profile(profiles_path, model)


def load_pi_config(project_root: Path | None = None) -> dict:
    """Load Pi-specific harness config (pi.yaml). Only used by Pi-aware callers."""
    from .pi.install.constants import load_pi_config as _load
    return _load(project_root=project_root)
