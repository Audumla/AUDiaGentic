from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import constants as _c


def _build_models_config(harness_cfg: dict, model_name: str, model_profile: dict) -> dict:
    ag = model_profile.get("ag", {}) if isinstance(model_profile, dict) else {}
    compat: dict = ag.get("compat", {
        "supportsDeveloperRole": False,
        "supportsReasoningEffort": False,
    })
    rig_port = int(harness_cfg.get("rig", {}).get("port", _c.DEFAULT_RIG_PORT))
    endpoint = f"http://127.0.0.1:{rig_port}/v1"
    api_key = _c.DEFAULT_API_KEY
    return {
        "providers": {
            _c.DEFAULT_PROVIDER: {
                "baseUrl": endpoint,
                "api": "openai-completions",
                "apiKey": api_key,
                "compat": compat,
                "models": [
                    {
                        "id": model_name,
                        "name": "AUDiaGentic local planner",
                        "reasoning": bool(ag.get("reasoning", False)),
                        "input": ["text"],
                        "contextWindow": int(ag.get("context_window", 262144)),
                        "maxTokens": int(ag.get("max_tokens", 4096)),
                        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    }
                ],
            }
        }
    }


def _resolve_project_root(project_root: Path | None = None) -> Path:
    if project_root is not None:
        return project_root

    import os

    env_project_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if env_project_root:
        return Path(env_project_root)

    return Path.cwd()


def _build_mcp_config(harness_cfg: dict, *, project_root: Path | None = None) -> dict:
    """Build mcp.json config dynamically from installed components."""
    from audiagentic.runtime.mcp_config_builder import build_mcp_config

    # Load extra config from harness_cfg
    extra_config = {"mcp": harness_cfg.get("mcp", {})}
    return build_mcp_config(_resolve_project_root(project_root), extra_config)


def _build_settings_config(harness_cfg: dict, target: Path) -> dict:
    ui = harness_cfg.get("ui", {})
    theme_name: str = ui.get("theme", "dark")
    theme_colors = ui.get("theme_colors") or {}

    if theme_colors:
        base_theme_dir = (
            target / "cli" / "node_modules"
            / "@earendil-works" / "pi-coding-agent"
            / "dist" / "modes" / "interactive" / "theme"
        )
        base_path = base_theme_dir / f"{theme_name}.json"
        base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {"vars": {}, "colors": {}, "export": {}}
        base.setdefault("colors", {}).update(theme_colors)
        themes_dir = target / "agent" / "themes"
        themes_dir.mkdir(parents=True, exist_ok=True)
        custom_theme_path = themes_dir / "audiagentic.json"
        custom_theme_path.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
        theme_name = str(custom_theme_path)

    settings: dict = {
        "theme": theme_name,
        "extensions": [
            "extensions/footer.ts",
            "extensions/follow_up_actions.ts",
        ],
    }
    for key, dest, cast in [
        ("quiet_startup",      "quietStartup",         bool),
        ("collapse_changelog", "collapseChangelog",    bool),
        ("hide_thinking_block","hideThinkingBlock",     bool),
        ("thinking",           "defaultThinkingLevel", str),
        ("editor_padding_x",   "editorPaddingX",       int),
    ]:
        if key in ui:
            settings[dest] = cast(ui[key])
    if "hide_tool_use" in ui:
        settings["audiagenticHideToolUse"] = bool(ui["hide_tool_use"])
    return settings


def _build_system_md(target: Path, harness_cfg: dict, *, project_root: Path | None = None) -> None:
    """Build SYSTEM.md with dynamic tool list from installed components."""
    from audiagentic.runtime.mcp_config_builder import (
        apply_system_md_injections,
        build_system_md_injections,
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
    """Write all agent config files from Python dicts. Called at install time.

    Static files (SYSTEM.md, extensions/) are also copied here so the agent
    directory is fully populated after install with no further writes needed at
    launch time.
    """
    agent_dir = target / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Build SYSTEM.md dynamically
    _build_system_md(target, harness_cfg, project_root=project_root)

    # Copy APPEND_SYSTEM.md
    append_src = _c._TEMPLATES_DIR / "APPEND_SYSTEM.md"
    if append_src.exists():
        shutil.copy2(append_src, agent_dir / "APPEND_SYSTEM.md")

    ext_src = _c._TEMPLATES_DIR / "extensions"
    if ext_src.exists():
        shutil.copytree(ext_src, agent_dir / "extensions", dirs_exist_ok=True)

    model_name: str = harness_cfg.get("model")
    if not model_name:
        raise SystemExit("No model configured in harness config. Set 'model' in ag.yaml or via AUDIAGENTIC_PI_MODEL env var.")
    model_profile: dict = {}
    if _c._MODELS_JSON.exists():
        try:
            data = json.loads(_c._MODELS_JSON.read_text(encoding="utf-8"))
            model_profile = data.get("models", {}).get(model_name, {})
        except Exception:
            pass

    model_id: str = harness_cfg.get("model-id", "audiagentic-rig")
    (agent_dir / "models.json").write_text(
        json.dumps(_build_models_config(harness_cfg, model_id, model_profile), indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_dir / "mcp.json").write_text(
        json.dumps(_build_mcp_config(harness_cfg, project_root=project_root), indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_dir / "settings.json").write_text(
        json.dumps(_build_settings_config(harness_cfg, target), indent=2) + "\n",
        encoding="utf-8",
    )

    _c._print(f"Materialized agent config in {agent_dir}")
