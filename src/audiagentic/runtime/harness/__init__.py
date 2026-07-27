"""Harness facade — single import surface for all harness operations.

All callers outside the harness package should import from here, not from
harness.<type>.* directly. The active harness is selected by ``harness.type``
in ag.yaml (default: ``pi``). Config materialization routes through
providers_api.materialize_provider_config — the provider adapter owns its own
config shapes and delivery mechanism (HA11).
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from audiagentic.components.providers.contracts.session_status import (
    ProviderSessionInfo,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.foundation.event import (
    LifecycleEventPayload,
    subscribe_component_lifecycle,
)
from audiagentic.foundation.interaction import push_status

logger = logging.getLogger(__name__)


@dataclass
class RunnerParams:
    """Harness-agnostic runner parameters.

    Each harness's translate_agent_args converts these to CLI flags.
    """

    prompt: str | None = None
    mode: str | None = None  # "text" | "json"
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
    project_root = kwargs.get("project_root") or (
        args[0] if args and hasattr(args[0], "resolve") else None
    )
    mod = _mod(module_key, project_root)
    return getattr(mod, fn_name)(*args, **kwargs)


def default_config_path() -> Path:
    """Package-default harness config path (config/provisioning/harness/ag.yaml)."""
    from .paths import _HARNESS_CONFIG

    return _HARNESS_CONFIG


def get_harness_type(project_root: Path | None = None) -> str:
    """Resolve which harness to use for the given project root.

    Config-driven (``harness/ag`` namespace), no hardcoded harness name:

    1. An explicit ``harness.type`` pin wins if set (forces that harness).
    2. Otherwise ``harness.order`` is tried in order and the first harness whose
       CLI is installed on the system is used.
    3. If none in the order is installed, the most-preferred configured harness
       (``order[0]``) is returned so config/dispatch still target a valid
       harness; the not-installed condition surfaces at launch time.
    """
    from audiagentic.foundation.config import load_layered_config

    cfg = load_layered_config(
        pkg_default_path=default_config_path(),
        project_root=project_root,
        namespace="harness/ag",
    )
    harness_cfg = cfg.get("harness", {})

    pinned = harness_cfg.get("type")
    if pinned:
        return pinned

    order = harness_cfg.get("order") or []
    if not order:
        raise _harness_error(
            3,
            "no harness configured: set harness.type or harness.order in the harness/ag config.",
        )

    from .resolution import resolve_launch_harness

    resolved = resolve_launch_harness(order)
    return resolved.harness_type if resolved is not None else order[0]


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


def cleanup_runtime(target: Path) -> int:
    """Remove only AUDiaGentic-generated runtime state.

    A system-installed harness belongs to the user and is never removed by
    AUDiaGentic cleanup.
    """
    from .pi.install import cleanup_runtime as _cleanup_runtime

    return _cleanup_runtime(target)


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
    """Refresh harness config if a supported CLI is installed on the system.

    Routes through providers_api.materialize_provider_config (HA11).
    """
    from audiagentic.foundation.config import load_layered_config
    from audiagentic.runtime.harness.resolution import harness_cli_available

    harness_type = get_harness_type(project_root)
    if not harness_cli_available(harness_type):
        return False

    harness_cfg = load_layered_config(
        pkg_default_path=default_config_path(),
        project_root=project_root,
        namespace="harness/ag",
    )

    from audiagentic.components.providers import providers_api
    from audiagentic.foundation.paths.home import global_harness_runtime

    agent_runtime = global_harness_runtime()
    providers_api.materialize_provider_config(
        project_root,
        provider_id=harness_type,
        harness_cfg=harness_cfg,
        agent_runtime=agent_runtime if harness_type == "pi" else None,
    )
    return True


def refresh_materialized_agent_config(target: Path, project_root: Path | None = None) -> int:
    """Refresh materialized config for the active harness.

    Routes through providers_api.materialize_provider_config — the provider
    adapter owns its own config shapes and delivery mechanism (HA11).
    """
    from audiagentic.components.providers import providers_api
    from audiagentic.foundation.config import load_layered_config

    root = project_root or Path.cwd()
    harness_type = get_harness_type(root)
    harness_cfg = load_layered_config(
        pkg_default_path=default_config_path(),
        project_root=root,
        namespace="harness/ag",
    )

    providers_api.materialize_provider_config(
        root,
        provider_id=harness_type,
        harness_cfg=harness_cfg,
        agent_runtime=target if harness_type == "pi" else None,
    )
    return 0


def request_runtime_reload(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
    has_mcp_servers: bool = True,
) -> Path:
    return _forward(
        "install",
        "request_runtime_reload",
        project_root,
        reason=reason,
        component_id=component_id,
        has_mcp_servers=has_mcp_servers,
    )


# --- runner interface ---


def build_global_context(*, project_root: Path, agent_runtime: Path, enable_mcp: bool):
    return _forward(
        "runner",
        "build_global_context",
        project_root=project_root,
        agent_runtime=agent_runtime,
        enable_mcp=enable_mcp,
    )


def run_agent(ctx, params: list[str] | RunnerParams, **kw):
    if isinstance(params, RunnerParams):
        params = translate_agent_args(params)
    return _forward("runner", "run_agent", ctx, params, **kw)


def translate_agent_args(params: RunnerParams) -> list[str]:
    return _mod("runner").translate_agent_args(params)


def env_flag(name: str, default: bool = False) -> bool:
    return _mod("runner").env_flag(name, default)


# --- harness-specific helpers (pi-only until generalised) ---


def resolve_session_info(project_root: Path | None = None) -> ProviderSessionInfo:
    """Resolve provider session status for the active harness.

    Each harness resolves its own session info through its interface.
    Session component consumes this — it never touches rig internals.
    """
    from audiagentic.foundation.config import load_layered_config
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.runtime.rig.models import query_server_version

    info = ProviderSessionInfo()

    # Version info (always available)
    version_payload = version_info(project_root)
    info = ProviderSessionInfo(
        agent_version=version_payload.get("agent"),
        mcp_adapter_version=version_payload.get("mcp_adapter"),
        config_path=str(default_config_path()),
    )

    # Local rig: server version + models.json (if harness exists)
    harness = global_harness_runtime()
    if harness and (harness / "rig" / "bin").exists():
        server_ver = query_server_version(harness / "rig" / "bin")
        info = ProviderSessionInfo(**info.__dict__, server_version=server_ver)
        models_path = harness / "agent" / "models.json"
        if models_path.exists():
            try:
                models_json = json.loads(models_path.read_text(encoding="utf-8"))
                info = ProviderSessionInfo(**info.__dict__, models_data=models_json)
            except (OSError, json.JSONDecodeError):
                pass  # degraded: no models JSON

    # Endpoint from env (remote rig / OpenAI-compatible connection)
    base_url = os.environ.get("AUDIAGENTIC_AG_BASE_URL")
    info = ProviderSessionInfo(**info.__dict__, base_url=base_url)

    # Model config from harness config (shared across providers)
    requested = os.environ.get("AUDIAGENTIC_AG_MODEL")
    if not requested:
        cfg = load_layered_config(
            pkg_default_path=default_config_path(),
            project_root=None,
            namespace="harness/ag",
        )
        requested = cfg.get("model")

    info = ProviderSessionInfo(
        **info.__dict__,
        configured_model=requested if isinstance(requested, str) else None,
    )

    return info


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

_REASON_TO_ACTION = {
    "component-installed": ("install", "installing"),
    "component-enabled": ("enable", "enabling"),
    "component-disabled": ("disable", "disabling"),
    "component-uninstalled": ("uninstall", "uninstalling"),
    "component-config-changed": ("config change", "config change"),
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
    payload: LifecycleEventPayload,
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

    action = _runtime_action_for_reason(
        reason, has_mcp_servers=_harness_has_mcp_servers(component_id)
    )

    if action != "reload_required":
        verb, gerund = _REASON_TO_ACTION.get(reason, (reason, reason))
        push_status(
            component="harness",
            message=f"Config refreshed after {gerund} {component_id}.",
        )
        return

    logger.debug(
        "harness reload marker requested",
        extra={"component": component_id, "reason": reason},
    )


subscribe_component_lifecycle(
    None,
    on_installed=partial(_harness_lifecycle_handler, reason="component-installed"),
    on_enabled=partial(_harness_lifecycle_handler, reason="component-enabled"),
    on_disabled=partial(_harness_lifecycle_handler, reason="component-disabled"),
    on_uninstalled=partial(_harness_lifecycle_handler, reason="component-uninstalled"),
    on_config_changed=partial(_harness_lifecycle_handler, reason="component-config-changed"),
)
