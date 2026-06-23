from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.runtime.config import load_yaml_file


def _embedded_config_error(code_number: int, message: str, **details: object) -> AudiaGenticError:
    return make_error(
        prefix="CFG",
        component="RIGCFG",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


@dataclass
class ModelProfile:
    name: str
    model_file: str | None
    server_cfg: dict[str, object]
    agent_cfg: dict[str, object]
    chat_template_kwargs: dict[str, object]
    tool_call_proxy: str | None


def rig_config_path() -> Path:
    from audiagentic.runtime.harness.paths import _RIG_CONFIG
    return _RIG_CONFIG


def load_rig_profiles(profiles_path: Path | None = None) -> dict[str, object]:
    path = profiles_path or rig_config_path()
    if not path.exists():
        raise _embedded_config_error(1, f"Rig config not found: {path}", path=str(path))
    return load_yaml_file(path)


def load_rig_model(profiles_path: Path | None = None) -> tuple[str, str]:
    data = load_rig_profiles(profiles_path)
    raw = data.get("rig_model", {})
    if not isinstance(raw, dict):
        raise _embedded_config_error(2, f"Invalid rig_model config: {rig_config_path()}")
    profile = raw.get("profile")
    model_id = raw.get("model_id")
    if not isinstance(profile, str) or not profile:
        raise _embedded_config_error(3, f"rig_model.profile is required in {rig_config_path()}")
    if not isinstance(model_id, str) or not model_id:
        raise _embedded_config_error(4, f"rig_model.model_id is required in {rig_config_path()}")
    return profile, model_id


def resolve_profile_definition(profile_name: str, profiles_path: Path | None = None) -> dict[str, object]:
    data = load_rig_profiles(profiles_path)
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise _embedded_config_error(5, f"Invalid rig config: {rig_config_path()}")
    raw = models.get(profile_name)
    if not isinstance(raw, dict):
        raise _embedded_config_error(6, f"Model profile not found: {profile_name}", profile=profile_name)

    settings = data.get("profile_settings", {})
    if not isinstance(settings, dict):
        settings = {}

    merged: dict[str, object] = {}
    extends = raw.get("extends", [])
    if isinstance(extends, str):
        extends = [extends]
    for setting_name in extends:
        block = settings.get(setting_name, {})
        if not isinstance(block, dict):
            raise _embedded_config_error(
                7,
                f"Profile setting not found or invalid: {setting_name}",
                setting=setting_name,
            )
        _deep_merge(merged, block)

    local = {k: v for k, v in raw.items() if k != "extends"}
    _deep_merge(merged, local)

    server_cfg = merged.get("server", {})
    agent_cfg = merged.get("agent", {})
    prompt_cfg = merged.get("prompt", {})
    proxy_cfg = merged.get("proxy", {})
    if not isinstance(server_cfg, dict):
        server_cfg = {}
    if not isinstance(agent_cfg, dict):
        agent_cfg = {}
    if not isinstance(prompt_cfg, dict):
        prompt_cfg = {}
    if not isinstance(proxy_cfg, dict):
        proxy_cfg = {}

    if "context_size" not in agent_cfg and "context_size" in server_cfg:
        agent_cfg["context_size"] = server_cfg["context_size"]
    if "reasoning" not in agent_cfg and "reasoning" in server_cfg:
        raw_reasoning = server_cfg["reasoning"]
        agent_cfg["reasoning"] = str(raw_reasoning).lower() in {"1", "true", "on", "yes"}

    merged["server"] = server_cfg
    merged["agent"] = agent_cfg
    merged["prompt"] = prompt_cfg
    merged["proxy"] = proxy_cfg
    return merged
def load_rig_config(profile_name: str) -> tuple[dict[str, object], dict[str, object], str | None]:
    resolved = resolve_profile_definition(profile_name)
    server_cfg = resolved.get("server", {})
    prompt_cfg = resolved.get("prompt", {})
    proxy_cfg = resolved.get("proxy", {})
    chat_template_kwargs = prompt_cfg.get("chat_template", {}) if isinstance(prompt_cfg, dict) else {}
    tool_call_proxy = proxy_cfg.get("tool_call") if isinstance(proxy_cfg, dict) else None
    return (
        server_cfg if isinstance(server_cfg, dict) else {},
        chat_template_kwargs if isinstance(chat_template_kwargs, dict) else {},
        tool_call_proxy if isinstance(tool_call_proxy, str) else None,
    )


def resolve_model_profile(
    requested: str | None,
    model_file: str | None,
    profiles_path: Path | None = None,
) -> ModelProfile:
    data = load_rig_profiles(profiles_path)
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise _embedded_config_error(8, f"Invalid rig config: {rig_config_path()}")

    target = requested or os.environ.get("AUDIAGENTIC_RIG_MODEL_PROFILE")
    rig_profile, rig_model_id = load_rig_model(profiles_path)
    if target == rig_model_id:
        target = rig_profile
    if not target and model_file:
        model_name = Path(model_file).name
        for name, raw_profile in models.items():
            if not isinstance(raw_profile, dict):
                continue
            if model_name == raw_profile.get("model_file"):
                target = str(name)
                break
    if not target:
        target = rig_profile
    if not target:
        raise _embedded_config_error(9, f"No model profile specified and no rig_model.profile set in {rig_config_path()}")

    raw = models.get(target)
    if not isinstance(raw, dict):
        raise _embedded_config_error(10, f"Model profile not found: {target}", profile=target)

    resolved = resolve_profile_definition(target, profiles_path)
    server_cfg = resolved.get("server", {})
    agent_cfg = resolved.get("agent", {})
    prompt_cfg = resolved.get("prompt", {})
    proxy_cfg = resolved.get("proxy", {})
    resolved_model_file = resolved.get("model_file")
    model_file_value: str | None = cast(str, resolved_model_file) if isinstance(resolved_model_file, str) else None
    return ModelProfile(
        name=target,
        model_file=model_file_value,
        server_cfg=server_cfg if isinstance(server_cfg, dict) else {},
        agent_cfg=agent_cfg if isinstance(agent_cfg, dict) else {},
        chat_template_kwargs=(
            prompt_cfg.get("chat_template", {})
            if isinstance(prompt_cfg, dict) and isinstance(prompt_cfg.get("chat_template", {}), dict)
            else {}
        ),
        tool_call_proxy=(
            proxy_cfg.get("tool_call")
            if isinstance(proxy_cfg, dict) and isinstance(proxy_cfg.get("tool_call"), str)
            else None
        ),
    )


def _deep_merge(base: dict[str, object], incoming: dict[str, object]) -> dict[str, object]:
    for key, value in incoming.items():
        current = base.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            _deep_merge(current, value)
        else:
            base[key] = copy.deepcopy(value)
    return base
