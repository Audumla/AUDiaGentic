"""Harness facade — single import surface for all harness operations.

All callers outside the harness package should import from here, not from
harness.<type>.* directly. The active harness is selected by ``harness.type``
in ag.yaml (default: ``pi``). Adding a new harness means:

  1. Create ``runtime/harness/<type>/`` with ``install`` and ``runner`` submodules
     that expose the same interface as ``pi/install`` and ``pi/runner``.
  2. Set ``harness.type: <type>`` in ag.yaml or a project-local override.
"""
from __future__ import annotations

import importlib
import logging
import re
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.foundation.event import subscribe_component_lifecycle
from audiagentic.foundation.interaction import ask, push_status

logger = logging.getLogger(__name__)


@dataclass
class RunnerParams:
    """Harness-agnostic runner parameters.

    Each harness's translate_agent_args converts these to CLI flags.
    """
    prompt: str | None = None
    mode: str | None = None   # "text" | "json"
    verbose: bool = False


_HARNESS_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _harness_error(code_number: int, message: str, **details: object) -> AudiaGenticError:
    return make_error(
        prefix="CFG",
        component="HRN",
        number=code_number,
        kind="harness",
        message=message,
        details=details,
    )


def _forward(module_key: str, fn_name: str, *args, **kwargs):
    """Forward a call to the active harness module."""
    project_root = kwargs.get("project_root") or (args[0] if args and hasattr(args[0], "resolve") else None)
    mod = _mod(module_key, project_root)
    return getattr(mod, fn_name)(*args, **kwargs)


def default_config_path() -> Path:
    """Package-default harness config path (config/provisioning/harness/ag.yaml)."""
    from .paths import _HARNESS_CONFIG
    return _HARNESS_CONFIG


def get_harness_type(project_root: Path | None = None) -> str:
    """Return the configured harness type for the given project root."""
    from audiagentic.foundation.config import load_layered_config
    cfg = load_layered_config(
        pkg_default_path=default_config_path(),
        project_root=project_root,
        namespace="harness/ag",
    )
    return cfg.get("harness", {}).get("type", "pi")


def _mod(subpath: str, project_root: Path | None = None):
    t = get_harness_type(project_root)
    if not isinstance(t, str) or not _HARNESS_TYPE_PATTERN.fullmatch(t):
        raise _harness_error(
            1,
            f"Invalid harness type {t!r}. "
            "Use a package-style identifier such as 'pi' or 'opencode'.",
            harness_type=t,
        )
    try:
        return importlib.import_module(f"audiagentic.runtime.harness.{t}.{subpath}")
    except ModuleNotFoundError as exc:
        expected = f"audiagentic.runtime.harness.{t}"
        if exc.name and (exc.name == expected or exc.name.startswith(f"{expected}.")):
            raise _harness_error(
                2,
                f"Unknown harness type {t!r}. "
                "Create runtime/harness/<type>/ or set harness.type in ag.yaml.",
                harness_type=t,
            ) from exc
        raise


# --- install / lifecycle ---

def install_to(target: Path, project_root: Path | None = None) -> int:
    return _forward("install", "install_to", target, project_root=project_root)


def version_info(project_root: Path | None = None) -> dict[str, str]:
    """Configured agent + MCP adapter versions for the active harness."""
    return _forward("install", "version_info", project_root=project_root)


def uninstall_from(target: Path) -> int:
    return _forward("install", "uninstall_from", target)


def build_runtime_sync(
    *,
    reason: str,
    component_id: str | None = None,
    target: str | None = None,
    has_mcp_servers: bool = True,
) -> dict[str, object]:
    mod = _mod("install")
    kw: dict = {"reason": reason, "component_id": component_id, "has_mcp_servers": has_mcp_servers}
    if target is not None:
        kw["target"] = target
    return mod.build_runtime_sync(**kw)


def refresh_harness_config_if_installed(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
) -> bool:
    return _forward("install", "refresh_harness_config_if_installed", project_root, reason=reason, component_id=component_id)


def refresh_materialized_agent_config(
    target: Path, project_root: Path | None = None
) -> int:
    return _forward("install", "refresh_materialized_agent_config", target, project_root=project_root)


def request_runtime_reload(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
    has_mcp_servers: bool = True,
) -> Path:
    return _forward("install", "request_runtime_reload", project_root, reason=reason, component_id=component_id, has_mcp_servers=has_mcp_servers)


# --- runner interface ---

def build_global_context(
    *, project_root: Path, agent_runtime: Path, enable_mcp: bool
):
    return _forward("runner", "build_global_context", project_root=project_root, agent_runtime=agent_runtime, enable_mcp=enable_mcp)


def run_agent(ctx, params: list[str] | RunnerParams, **kw):
    return _forward("runner", "run_agent", ctx, params, **kw)


def translate_agent_args(params: RunnerParams) -> list[str]:
    return _mod("runner").translate_agent_args(params)


def env_flag(name: str, default: bool = False) -> bool:
    return _mod("runner").env_flag(name, default)


# --- MCP config dispatch ---

def mcp_config_path(project_root: Path | None = None) -> Path:
    return _forward("install", "mcp_config_path", project_root=project_root)


def read_mcp_config(path: Path) -> dict:
    return _mod("install").read_mcp_config(path)


def write_mcp_config(path: Path, entries: dict) -> None:
    return _mod("install").write_mcp_config(path, entries)


def remove_mcp_config(path: Path, name: str) -> bool:
    return _mod("install").remove_mcp_config(path, name)


# --- harness-specific helpers (pi-only until generalised) ---

def query_rig_server_version(bin_dir: Path, timeout: float = 10.0) -> str | None:
    from audiagentic.runtime.rig.models import query_server_version
    return query_server_version(bin_dir, timeout=timeout)


def load_active_profile(
    requested: str | None,
    model: str,
    *,
    rig_config: Path | None = None,
) -> tuple[str, dict[str, object]]:
    from audiagentic.runtime.rig.models import load_model_profile
    return load_model_profile(requested, model, rig_config=rig_config)


def load_pi_config(project_root: Path | None = None) -> dict:
    """Load Pi-specific harness config (pi.yaml). Only used by Pi-aware callers."""
    from .pi.install.constants import load_pi_config as _load
    return _load(project_root=project_root)


# Subscribe to component lifecycle events at module import time.
# Placed at EOF so the referenced functions are already defined.
# Wires ask/reload through foundation.interaction for reload_required actions.
# noqa: E402

_REASON_TO_VERB = {
    "component-installed": "installed",
    "component-enabled": "enabled",
    "component-disabled": "disabled",
    "component-uninstalled": "uninstalled",
    "component-config-changed": "config-changed",
}


def _harness_has_mcp_servers(component_id: str | None) -> bool:
    """Compute has_mcp_servers from the component descriptor, not a constant."""
    if not component_id:
        return True
    from audiagentic.foundation.components.registry import get_descriptor

    desc = get_descriptor(component_id)
    if not desc:
        return True
    return bool(desc.mcp_servers or desc.external_mcp_servers)


def _harness_lifecycle_handler(
    project_root: Path,
    payload: dict,
    metadata: dict,
    *,
    reason: str,
) -> None:
    from audiagentic.runtime.harness.reload import _runtime_action_for_reason

    component_id = payload.get("component_id")

    refresh_harness_config_if_installed(
        project_root,
        reason=reason,
        component_id=component_id,
    )

    action = _runtime_action_for_reason(reason, has_mcp_servers=_harness_has_mcp_servers(component_id))

    if action != "reload_required":
        verb = _REASON_TO_VERB.get(reason, reason)
        push_status(
            component="harness",
            message=f"Config refreshed after {verb}ing {component_id}.",
        )
        return

    verb = _REASON_TO_VERB.get(reason, reason)
    title = f"Reload harness after {verb}"
    description = (
        f"Component \"{component_id}\" was just {verb}. "
        "A full reload may be required to pick up the change."
    )
    resp = ask(
        title=title,
        description=description,
        choices=("reload-now", "later"),
        default_choice="reload-now",
    )

    if resp.choice == "reload-now":
        try:
            request_runtime_reload(
                project_root,
                reason=reason,
                component_id=component_id,
            )
            logger.info(
                "harness reload initiated via interaction ask",
                extra={"component": component_id, "reason": reason},
            )
        except Exception:
            logger.warning(
                "Failed to request runtime reload after user approval",
                extra={"component": component_id, "reason": reason},
                exc_info=True,
            )
    else:
        status_text = "deferred" if resp.choice == "later" else "timed out"
        push_status(
            component="harness",
            message=f"Harness reload {status_text} for component {component_id}.",
            level="info",
        )


subscribe_component_lifecycle(
    None,
    on_installed=partial(_harness_lifecycle_handler, reason="component-installed"),
    on_enabled=partial(_harness_lifecycle_handler, reason="component-enabled"),
    on_disabled=partial(_harness_lifecycle_handler, reason="component-disabled"),
    on_uninstalled=partial(_harness_lifecycle_handler, reason="component-uninstalled"),
    on_config_changed=partial(_harness_lifecycle_handler, reason="component-config-changed"),
)
