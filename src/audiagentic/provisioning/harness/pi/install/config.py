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


def _build_mcp_config(harness_cfg: dict) -> dict:
    if not harness_cfg.get("mcp", {}).get("enabled", True):
        return {"settings": {"toolPrefix": "mcp", "idleTimeout": 10, "directTools": False}, "mcpServers": {}}

    import sys
    extra_args: list[str] = harness_cfg.get("mcp", {}).get("extra_server_args", [])
    src_dir = str(_c._SRC_DIR).replace("\\", "/")
    python = sys.executable.replace("\\", "/")

    def _server(
        module: str,
        base_args: list[str] = [],
        direct_tools: list[str] | bool = [],
    ) -> dict:
        s: dict = {
            "command": python,
            "args": ["-m", module] + base_args + extra_args,
            "env": {"PYTHONPATH": src_dir},
            "lifecycle": "lazy",
        }
        if direct_tools is True or direct_tools:
            s["directTools"] = direct_tools
        return s

    return {
        "settings": {"toolPrefix": "mcp", "idleTimeout": 10, "directTools": True},
        "mcpServers": {
            "audiagentic-session": _server(
                "audiagentic.provisioning.mcp.server",
                ["--readonly", "--smoke-only"],
                ["audiagentic_provisioning_status", "audiagentic_provisioning_config", "audiagentic_provisioning_set_auto_update"],
            ),
            "audiagentic-project": _server("audiagentic.provisioning.mcp.project_server"),
            "audiagentic-planning": _server("audiagentic.provisioning.mcp.planning_server"),
            "audiagentic-providers": _server("audiagentic.provisioning.mcp.providers_server", direct_tools=True),
            "audiagentic-release-please": _server("audiagentic.provisioning.mcp.release_please_server"),
        },
    }


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

    settings: dict = {"theme": theme_name, "extensions": ["extensions/footer.ts"]}
    for key, dest, cast in [
        ("quiet_startup",      "quietStartup",         bool),
        ("collapse_changelog", "collapseChangelog",    bool),
        ("hide_thinking_block","hideThinkingBlock",     bool),
        ("thinking",           "defaultThinkingLevel", str),
        ("editor_padding_x",   "editorPaddingX",       int),
    ]:
        if key in ui:
            settings[dest] = cast(ui[key])
    return settings


def materialize_agent_config(target: Path, harness_cfg: dict) -> None:
    """Write all agent config files from Python dicts. Called at install time.

    Static files (SYSTEM.md, extensions/) are also copied here so the agent
    directory is fully populated after install with no further writes needed at
    launch time.
    """
    agent_dir = target / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    for name in ("SYSTEM.md", "APPEND_SYSTEM.md"):
        src = _c._TEMPLATES_DIR / name
        if src.exists():
            shutil.copy2(src, agent_dir / name)

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
        json.dumps(_build_mcp_config(harness_cfg), indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_dir / "settings.json").write_text(
        json.dumps(_build_settings_config(harness_cfg, target), indent=2) + "\n",
        encoding="utf-8",
    )

    _c._print(f"Materialized agent config in {agent_dir}")
