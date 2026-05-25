from __future__ import annotations

import json
import shutil
from pathlib import Path

from audiagentic.runtime.rig.embedded.config import load_rig_model, resolve_profile_definition

from . import constants as _c


def _require_harness_provider(harness_cfg: dict) -> str:
    provider = harness_cfg.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise SystemExit(
            "Harness config missing required 'provider'. "
            "Set it in config/provisioning/harness/ag.yaml or override config."
        )
    return provider.strip()


def _require_harness_rig_port(harness_cfg: dict) -> int:
    rig_cfg = harness_cfg.get("rig")
    if not isinstance(rig_cfg, dict):
        raise SystemExit(
            "Harness config missing required 'rig' section. "
            "Expected config/provisioning/harness/ag.yaml to define rig.port."
        )
    raw = rig_cfg.get("port")
    if raw is None:
        raise SystemExit(
            "Harness config missing required 'rig.port'. "
            "Set it in config/provisioning/harness/ag.yaml or override config."
        )
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"Invalid harness config value for rig.port: {raw!r}") from exc


def _build_models_config(harness_cfg: dict, model_name: str, model_profile: dict) -> dict:
    agent = model_profile.get("agent", {}) if isinstance(model_profile, dict) else {}
    compat: dict = agent.get("compat", {
        "supportsDeveloperRole": False,
        "supportsReasoningEffort": False,
    })
    rig_port = _require_harness_rig_port(harness_cfg)
    endpoint = f"http://127.0.0.1:{rig_port}/v1"
    api_key = _c.DEFAULT_API_KEY
    context_size = int(agent.get("context_size", 262144))
    return {
        "providers": {
            _require_harness_provider(harness_cfg): {
                "baseUrl": endpoint,
                "api": "openai-completions",
                "apiKey": api_key,
                "compat": compat,
                "models": [
                    {
                        "id": model_name,
                        "name": "AUDiaGentic local planner",
                        "reasoning": bool(agent.get("reasoning", False)),
                        "input": ["text"],
                        "contextWindow": context_size,
                        "maxTokens": int(agent.get("max_tokens", 4096)),
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


def _build_mcp_config(harness_cfg: dict, pi_cfg: dict, *, project_root: Path | None = None) -> dict:
    """Build mcp.json config dynamically from installed components."""
    from audiagentic.runtime.mcp_config_builder import build_mcp_config

    mcp = {**harness_cfg.get("mcp", {}), **pi_cfg.get("mcp", {})}
    return build_mcp_config(_resolve_project_root(project_root), {"mcp": mcp})


def _build_settings_config(pi_cfg: dict, target: Path) -> dict:
    ui = pi_cfg.get("ui", {})
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


def _build_system_md(target: Path, *, project_root: Path | None = None) -> None:
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
    """Write all agent config files. Called at install and refresh time."""
    pi_cfg = _c.load_pi_config(project_root=project_root)

    agent_dir = target / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    _build_system_md(target, project_root=project_root)

    append_src = _c._TEMPLATES_DIR / "APPEND_SYSTEM.md"
    if append_src.exists():
        shutil.copy2(append_src, agent_dir / "APPEND_SYSTEM.md")

    ext_src = _c._TEMPLATES_DIR / "extensions"
    if ext_src.exists():
        shutil.copytree(ext_src, agent_dir / "extensions", dirs_exist_ok=True)

    model_name: str = harness_cfg.get("model")
    if not model_name:
        raise SystemExit("No model configured. Set 'model' in ag.yaml or via AUDIAGENTIC_PI_MODEL env var.")
    model_profile: dict = {}
    model_id = model_name
    if _c._RIG_CONFIG.exists():
        profile_name, rig_model_id = load_rig_model(_c._RIG_CONFIG)
        if model_name == rig_model_id:
            model_id = rig_model_id
            model_profile = resolve_profile_definition(profile_name, _c._RIG_CONFIG)
        else:
            model_profile = resolve_profile_definition(model_name, _c._RIG_CONFIG)

    (agent_dir / "models.json").write_text(
        json.dumps(_build_models_config(harness_cfg, model_id, model_profile), indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_dir / "mcp.json").write_text(
        json.dumps(_build_mcp_config(harness_cfg, pi_cfg, project_root=project_root), indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_dir / "settings.json").write_text(
        json.dumps(_build_settings_config(pi_cfg, target), indent=2) + "\n",
        encoding="utf-8",
    )

    _c._print(f"Materialized agent config in {agent_dir}")
