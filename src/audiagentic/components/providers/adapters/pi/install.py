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


def materialize_model_config_path(project_root: Path, agent_runtime: Path | None) -> Path:
    """Pi launches read models from the isolated agent runtime."""
    from audiagentic.foundation.paths.home import global_harness_runtime

    return (agent_runtime or global_harness_runtime()) / "agent" / "models.json"


def _resolve_project_root(project_root: Path | None = None) -> Path:
    if project_root is not None:
        return project_root

    import os

    env_project_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if env_project_root:
        return Path(env_project_root)

    return Path.cwd()


def _build_system_md(target: Path, *, project_root: Path | None = None) -> None:
    """Copy Pi's provider-owned provisioning template without regeneration."""
    del project_root

    # Read the base SYSTEM.md template — bundled with this adapter.
    template_path = _TEMPLATES_DIR / "SYSTEM.md"
    if not template_path.exists():
        return

    (target / "SYSTEM.md").write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")


def _build_settings_config(ui_cfg: dict, *, target: Path) -> dict:
    """Render Pi UI settings; model projection owns models.json separately."""
    theme_name = ui_cfg.get("theme", "dark")
    theme_colors = ui_cfg.get("theme_colors") or {}
    if theme_colors:
        from audiagentic.components.providers import providers_api

        pkg = providers_api.get_pi_coding_agent_package_dir()
        theme_dir = pkg / "dist" / "modes" / "interactive" / "theme" if pkg else target
        base_path = theme_dir / f"{theme_name}.json"
        base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {"vars": {}, "colors": {}, "export": {}}
        base.setdefault("colors", {}).update(theme_colors)
        custom = target / "agent" / "themes" / "audiagentic.json"
        custom.parent.mkdir(parents=True, exist_ok=True)
        custom.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
        theme_name = str(custom)
    settings: dict = {"theme": theme_name}
    for key, dest, cast in (("quiet_startup", "quietStartup", bool), ("collapse_changelog", "collapseChangelog", bool), ("thinking", "defaultThinkingLevel", str), ("editor_padding_x", "editorPaddingX", int)):
        if key in ui_cfg:
            settings[dest] = cast(ui_cfg[key])
    return settings


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
    from audiagentic.foundation.config import load_layered_config
    from audiagentic.foundation.paths.home import global_harness_runtime

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

    # settings.json — UI settings (shape builder lives here).
    (agent_dir / "settings.json").write_text(
        json.dumps(
            _build_settings_config(pi_cfg.get("ui", {}), target=agent_runtime),
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
