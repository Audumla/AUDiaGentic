"""Pi provider config materialization — owns Pi's own config shapes and templates.

Moved from runtime/harness/pi/install/config.py as part of HA11: the runtime
should not need a bespoke module per harness type when the provider already
knows its own config shapes and delivery mechanism.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.runtime.harness.paths import _RIG_CONFIG
from audiagentic.runtime.rig.embedded.config import load_rig_model, resolve_profile_definition


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
        apply_system_prompt_injections,
        build_system_prompt_injections,
    )

    # Read the base SYSTEM.md template — bundled with this adapter.
    template_path = _TEMPLATES_DIR / "SYSTEM.md"
    if not template_path.exists():
        return

    content = template_path.read_text(encoding="utf-8")

    # Get injections from installed components.
    injections = build_system_prompt_injections(_resolve_project_root(project_root))
    if injections:
        content = apply_system_prompt_injections(content, injections)

    (target / "SYSTEM.md").write_text(content, encoding="utf-8")


def materialize_provider_config(
    project_root: Path,
    harness_cfg: dict,
    *,
    agent_runtime: Path | None = None,
) -> None:
    """Write all Pi-specific config files.

    Called at install and refresh time. Writes:
      - <agent_runtime>/agent/models.json   — rig provider entry
      - <agent_runtime>/agent/settings.json — UI settings
      - <agent_runtime>/SYSTEM.md           — provisioning agent prompt (then stale-deleted from agent/)
      - <agent_runtime>/agent/APPEND_SYSTEM.md — enforcement reminders
    And applies provider surface contributions for Pi.

    Args:
        project_root: Project root for component discovery and surface apply.
        harness_cfg: Harness config dict (rig.model, rig.port, rig.provider).
        agent_runtime: Target directory for agent files (harness runtime root).
            Defaults to the global harness runtime from foundation.paths.home.
    """
    from audiagentic.components.providers.adapters.pi import local_rig_config as _rig
    from audiagentic.foundation.config import load_layered_config
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.runtime.harness.config import (
        require_harness_provider,
        require_harness_rig_port,
    )

    if agent_runtime is None:
        runtime = global_harness_runtime()
        if runtime is None:
            from audiagentic.foundation.contracts.errors import make_error

            raise make_error(
                prefix="CFG",
                component="HCFG",
                number=8,
                kind="harness-config",
                message="No agent runtime directory configured.",
            )
        agent_runtime = runtime

    # Load Pi-specific config (theme, UI options).
    pi_cfg_path = _TEMPLATES_DIR.parent.parent / "pi.yaml"
    if pi_cfg_path.exists():
        pi_cfg = load_layered_config(
            pkg_default_path=pi_cfg_path,
            project_root=project_root,
            namespace="harness/pi",
        )
    else:
        pi_cfg = {}

    agent_dir = agent_runtime / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    # SYSTEM.md — template + injections.
    _build_system_md(agent_runtime, project_root=project_root)

    # Remove stale SYSTEM.md from agent/ (it belongs at the harness root).
    stale = agent_dir / "SYSTEM.md"
    if stale.exists():
        stale.unlink()

    # APPEND_SYSTEM.md — copy from template.
    append_src = _TEMPLATES_DIR / "APPEND_SYSTEM.md"
    if append_src.exists():
        shutil.copy2(append_src, agent_dir / "APPEND_SYSTEM.md")

    # models.json — rig provider entry (shape builder lives here).
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

    models_config = _rig.build_models_config(
        provider_id=require_harness_provider(harness_cfg),
        rig_port=require_harness_rig_port(harness_cfg),
        api_key=DEFAULT_API_KEY,
        model_id=model_id,
        model_profile=model_profile,
    )
    (agent_dir / "models.json").write_text(
        json.dumps(models_config, indent=2) + "\n",
        encoding="utf-8",
    )

    # settings.json — UI settings (shape builder lives here).
    (agent_dir / "settings.json").write_text(
        json.dumps(
            _rig.build_settings_config(pi_cfg.get("ui", {}), target=agent_runtime),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Apply provider surface contributions for Pi.
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

    print_message(f"Materialized Pi config in {agent_dir}")


# --------------------------------------------------------------------------- #
# Templates bundled with this adapter
# --------------------------------------------------------------------------- #

_TEMPLATES_DIR = Path(__file__).parent / "templates" / "agent"
DEFAULT_API_KEY = "dummy"
