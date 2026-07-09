from __future__ import annotations

import json
import shutil
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.runtime.harness.config import require_harness_provider, require_harness_rig_port
from audiagentic.runtime.harness.paths import _RIG_CONFIG
from audiagentic.runtime.rig.embedded.config import load_rig_model, resolve_profile_definition

from . import constants as _c


def _require_harness_provider(harness_cfg: dict) -> str:
    return require_harness_provider(harness_cfg)


def _require_harness_rig_port(harness_cfg: dict) -> int:
    return require_harness_rig_port(harness_cfg)


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


def _build_mcp_config(harness_cfg: dict, *, project_root: Path | None = None) -> dict:
    """Build pi mcp.json from installed components via the pi harness adaptor."""
    from audiagentic.runtime.harness.mcp_collector import collect_mcp_servers
    from audiagentic.runtime.harness.pi.mcp_format import build_pi_mcp_dict

    enabled = harness_cfg.get("mcp", {}).get("enabled", True)
    if not enabled:
        return build_pi_mcp_dict({}, enabled=False)

    entries = collect_mcp_servers(_resolve_project_root(project_root))
    return build_pi_mcp_dict(entries)


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
    pi_cfg = _c.load_ag_config(project_root=project_root)

    agent_dir = target / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    _build_system_md(target, project_root=project_root)

    stale = agent_dir / "SYSTEM.md"
    if stale.exists():
        stale.unlink()

    append_src = _c._TEMPLATES_DIR / "APPEND_SYSTEM.md"
    if append_src.exists():
        shutil.copy2(append_src, agent_dir / "APPEND_SYSTEM.md")

    ext_src = _c._TEMPLATES_DIR / "extensions"
    if ext_src.exists():
        shutil.copytree(ext_src, agent_dir / "extensions", dirs_exist_ok=True)

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

    (agent_dir / "models.json").write_text(
        json.dumps(_build_models_config(harness_cfg, model_id, model_profile), indent=2) + "\n",
        encoding="utf-8",
    )
    from audiagentic.runtime.harness.pi.mcp_format import pi_mcp_path
    mcp_path = pi_mcp_path(_resolve_project_root(project_root))
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_path.write_text(
        json.dumps(_build_mcp_config(harness_cfg, project_root=project_root), indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_dir / "settings.json").write_text(
        json.dumps(_build_settings_config(pi_cfg, target), indent=2) + "\n",
        encoding="utf-8",
    )

    print_message(f"Materialized agent config in {agent_dir}")
