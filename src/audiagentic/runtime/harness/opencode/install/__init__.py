"""OpenCode harness configuration materialization.

This module materializes configuration for an available OpenCode CLI. Explicit
CLI installation and removal belong to the provider lifecycle, not config
materialization or launch-time discovery.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.runtime.harness.reload import (
    build_runtime_sync as _build_sync,
)

from . import constants as _c

logger = logging.getLogger(__name__)
_TARGET = "opencode-runtime"


def build_runtime_sync(
    *,
    reason: str,
    component_id: str | None = None,
    target: str = _TARGET,
    has_mcp_servers: bool = True,
) -> dict[str, object]:
    return _build_sync(reason=reason, component_id=component_id, target=target, has_mcp_servers=has_mcp_servers)


def request_runtime_reload(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
    has_mcp_servers: bool = True,
) -> dict[str, object]:
    return _build_sync(reason=reason, component_id=component_id, target=_TARGET, has_mcp_servers=has_mcp_servers)


def _resolve_project_root(project_root: Path | None = None) -> Path:
    import os
    if project_root is not None:
        return project_root
    env = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    return Path(env) if env else Path.cwd()


def _build_agents_md(project_root: Path) -> str:
    from audiagentic.runtime.harness.system_prompt import (
        apply_system_prompt_injections,
        build_system_prompt_injections,
    )

    template_path = _c._TEMPLATES_DIR / "AGENTS.md"
    content = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
    injections = build_system_prompt_injections(project_root)
    if injections:
        content = apply_system_prompt_injections(content, injections)
    return content


def materialize_agent_config(
    target: Path,
    harness_cfg: dict,
    *,
    project_root: Path | None = None,
) -> None:
    """Write all opencode agent config files at the project root."""
    from audiagentic.runtime.harness.paths import _RIG_CONFIG
    from audiagentic.runtime.rig.embedded.config import load_rig_model, resolve_profile_definition

    root = _resolve_project_root(project_root)

    model_name: str = harness_cfg.get("rig", {}).get("model", "")
    if not model_name:
        raise make_error(
            prefix="CFG",
            component="HCFG",
            number=10,
            kind="harness-config",
            message="No model configured. Set 'model' in ag.yaml.",
            details={"field": "rig.model"},
        )

    model_profile: dict = {}
    if _RIG_CONFIG.exists():
        try:
            profile_name, rig_model_id = load_rig_model(_RIG_CONFIG)
            ref = profile_name if model_name == rig_model_id else model_name
            model_profile = resolve_profile_definition(ref, _RIG_CONFIG)
        except AudiaGenticError:
            logger.warning("could not resolve model profile, using empty", exc_info=True)

    # No .mcp.json write here: stock opencode never reads bare .mcp.json (only
    # its own opencode.json/.jsonc — confirmed empirically and against
    # upstream, which closed a request for .mcp.json support as not planned).
    # That path collides with pi's PROVIDER mcp_config target besides. The
    # AUDiaGentic-curated MCP surface for opencode is delivered at launch time
    # via OPENCODE_CONFIG_CONTENT (see opencode/mcp_surface.py), not a file.

    agents_md = _build_agents_md(root)
    if agents_md:
        (root / "AGENTS.md").write_text(agents_md, encoding="utf-8")

    # Layer in any provider-owned surface contributions (components declaring
    # content for opencode's AGENTS.md through the shared providers surfaces
    # registry) as a managed block appended after the template above --
    # apply_managed_blocks only touches its own previously-managed region, so
    # this cannot clobber the template or user-authored content.
    try:
        from audiagentic.components.providers import providers_api

        providers_api.operate_provider_surfaces(root, "opencode", mode="apply")
    except AudiaGenticError:
        logger.warning("Failed to apply opencode provider surface contributions", exc_info=True)

    from audiagentic.components.providers.adapters.opencode.local_rig_config import (
        build_provider_config,
    )
    from audiagentic.runtime.harness.config import (
        require_harness_provider,
        require_harness_rig_port,
    )

    provider_cfg = build_provider_config(
        provider_id=require_harness_provider(harness_cfg),
        rig_port=require_harness_rig_port(harness_cfg),
        api_key=_c.DEFAULT_API_KEY,
        model_name=harness_cfg.get("rig", {}).get("model", "audiagentic-rig"),
        model_profile=model_profile,
    )
    opencode_dir = root / ".opencode"
    opencode_dir.mkdir(parents=True, exist_ok=True)
    (opencode_dir / "config.json").write_text(
        json.dumps(provider_cfg, indent=2) + "\n",
        encoding="utf-8",
    )

    print_message(f"Materialized opencode config in {root}")


def install_to(target: Path, project_root: Path | None = None) -> int:
    root = _resolve_project_root(project_root)
    from audiagentic.runtime.harness.config import load_harness_config
    harness_cfg = load_harness_config(project_root=root)
    materialize_agent_config(target, harness_cfg, project_root=root)
    return 0


def cleanup_runtime(target: Path) -> int:
    """OpenCode materializes project-local files, not runtime-owned state."""
    del target
    return 0


def refresh_materialized_agent_config(target: Path, project_root: Path | None = None) -> int:
    from audiagentic.runtime.harness.config import load_harness_config
    root = _resolve_project_root(project_root)
    harness_cfg = load_harness_config(project_root=root)
    materialize_agent_config(target, harness_cfg, project_root=root)
    return 0


def refresh_harness_config_if_installed(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
) -> bool:
    from audiagentic.runtime.harness.lifecycle import (
        refresh_harness_config_if_installed as _shared_refresh,
    )

    return _shared_refresh(
        cli_installed=shutil.which("opencode") is not None,
        component_id=component_id,
        refresh=lambda: refresh_materialized_agent_config(project_root, project_root=project_root),
        request_reload=lambda: request_runtime_reload(project_root, reason=reason, component_id=component_id),
    )
