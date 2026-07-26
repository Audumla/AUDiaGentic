"""Pi-specific config shapes for the local embedded rig connection.

Runtime install/materialize orchestrates *when* these are written (harness
config resolution, file placement); only this module knows the JSON shapes
pi's own ``models.json`` and ``settings.json`` expect.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_models_config(
    *,
    provider_id: str,
    rig_port: int,
    api_key: str,
    model_id: str,
    model_profile: dict[str, Any],
) -> dict[str, Any]:
    agent = model_profile.get("agent", {}) if isinstance(model_profile, dict) else {}
    compat: dict = agent.get("compat", {
        "supportsDeveloperRole": False,
        "supportsReasoningEffort": False,
    })
    context_size = int(agent.get("context_size", 262144))
    return {
        "providers": {
            provider_id: {
                "baseUrl": f"http://127.0.0.1:{rig_port}/v1",
                "api": "openai-completions",
                "apiKey": api_key,
                "compat": compat,
                "models": [
                    {
                        "id": model_id,
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


def build_settings_config(ui_cfg: dict[str, Any], *, target: Path) -> dict[str, Any]:
    """Build pi's settings.json, materializing a custom theme file if needed."""
    theme_name: str = ui_cfg.get("theme", "dark")
    theme_colors = ui_cfg.get("theme_colors") or {}

    if theme_colors:
        from audiagentic.components.providers import providers_api

        pkg = providers_api.get_pi_coding_agent_package_dir()
        base_theme_dir = (
            pkg / "dist" / "modes" / "interactive" / "theme" if pkg is not None
            else target / "dist" / "modes" / "interactive" / "theme"  # absent -> guarded below
        )
        base_path = base_theme_dir / f"{theme_name}.json"
        base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {"vars": {}, "colors": {}, "export": {}}
        base.setdefault("colors", {}).update(theme_colors)
        themes_dir = target / "agent" / "themes"
        themes_dir.mkdir(parents=True, exist_ok=True)
        custom_theme_path = themes_dir / "audiagentic.json"
        custom_theme_path.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
        theme_name = str(custom_theme_path)

    settings: dict[str, Any] = {"theme": theme_name}
    for key, dest, cast in [
        ("quiet_startup",      "quietStartup",         bool),
        ("collapse_changelog", "collapseChangelog",    bool),
        ("thinking",           "defaultThinkingLevel", str),
        ("editor_padding_x",   "editorPaddingX",       int),
    ]:
        if key in ui_cfg:
            settings[dest] = cast(ui_cfg[key])
    return settings


__all__ = ["build_models_config", "build_settings_config"]
