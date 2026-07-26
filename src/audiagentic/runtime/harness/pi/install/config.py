from __future__ import annotations

import json
import shutil
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.runtime.harness.config import require_harness_provider, require_harness_rig_port
from audiagentic.runtime.harness.paths import _RIG_CONFIG
from audiagentic.runtime.rig.embedded.config import load_rig_model, resolve_profile_definition

from . import constants as _c


def _resolve_project_root(project_root: Path | None = None) -> Path:
    if project_root is not None:
        return project_root

    import os

    env_project_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if env_project_root:
        return Path(env_project_root)

    return Path.cwd()


def _build_system_md(target: Path, *, project_root: Path | None = None) -> None:
    """Build SYSTEM.md with dynamic tool list from installed components."""
    from audiagentic.runtime.harness.system_prompt import (
        apply_system_prompt_injections as apply_system_md_injections,
    )
    from audiagentic.runtime.harness.system_prompt import (
        build_system_prompt_injections as build_system_md_injections,
    )

    # Read the base SYSTEM.md template
    template_path = _c._TEMPLATES_DIR / "SYSTEM.md"
    if not template_path.exists():
        return

    content = template_path.read_text(encoding="utf-8")

    # Get injections from installed components
    injections = build_system_md_injections(_resolve_project_root(project_root))

    if injections:
        # Apply injections to the template content
        content = apply_system_md_injections(content, injections)

    (target / "SYSTEM.md").write_text(content, encoding="utf-8")


def materialize_agent_config(
    target: Path,
    harness_cfg: dict,
    *,
    project_root: Path | None = None,
) -> None:
    """Write all agent config files. Called at install and refresh time."""
    pi_cfg = _c.load_pi_config(project_root=project_root)

    agent_dir = target / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    _build_system_md(target, project_root=project_root)

    stale = agent_dir / "SYSTEM.md"
    if stale.exists():
        stale.unlink()

    append_src = _c._TEMPLATES_DIR / "APPEND_SYSTEM.md"
    if append_src.exists():
        shutil.copy2(append_src, agent_dir / "APPEND_SYSTEM.md")

    model_name: str = harness_cfg.get("rig", {}).get("model")
    if not model_name:
        from audiagentic.foundation.contracts.errors import make_error

        raise make_error(
            prefix="CFG",
            component="HCFG",
            number=8,
            kind="harness-config",
            message="No model configured. Set 'model' in ag.yaml or via AUDIAGENTIC_PI_MODEL env var.",
            details={"field": "rig.model"},
        )
    model_profile: dict = {}
    model_id = model_name
    if _RIG_CONFIG.exists():
        profile_name, rig_model_id = load_rig_model(_RIG_CONFIG)
        if model_name == rig_model_id:
            model_id = rig_model_id
            model_profile = resolve_profile_definition(profile_name, _RIG_CONFIG)
        else:
            model_profile = resolve_profile_definition(model_name, _RIG_CONFIG)

    from audiagentic.components.providers.adapters.pi.local_rig_config import (
        build_models_config,
        build_settings_config,
    )

    models_config = build_models_config(
        provider_id=require_harness_provider(harness_cfg),
        rig_port=require_harness_rig_port(harness_cfg),
        api_key=_c.DEFAULT_API_KEY,
        model_id=model_id,
        model_profile=model_profile,
    )
    (agent_dir / "models.json").write_text(
        json.dumps(models_config, indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_dir / "settings.json").write_text(
        json.dumps(build_settings_config(pi_cfg.get("ui", {}), target=target), indent=2) + "\n",
        encoding="utf-8",
    )

    # Layer in component-declared contributions as a managed block
    # (components declaring content for AGENTS.md through the shared
    # provider surfaces registry — same mechanism used by every other
    # provider adapter)
    root = _resolve_project_root(project_root)
    try:
        from audiagentic.components.providers import providers_api

        providers_api.operate_provider_surfaces(root, "pi", mode="apply")
    except Exception:  # noqa: BLE001 — contribution rendering is non-fatal
        import logging

        logging.getLogger(__name__).warning(
            "Failed to apply pi provider surface contributions",
            exc_info=True,
        )

    print_message(f"Materialized agent config in {agent_dir}")
