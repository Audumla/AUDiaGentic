"""Gateway settings: the ``gateway`` section of the resolved settings (CFG09).

The section's schema is ``config/components/agents/settings/gateway.schema.json``.
Each value comes from its legacy ``AUDIAGENTIC_GATEWAY_*`` variable when that is
set (kept for one transition release), else from settings, else the caller's
default. Settings are resolved once per process environment, so a changed file
applies when the gateway restarts.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import read_text_with_retry


def gateway_setting(key: str, env: str | None = None, default: Any = None) -> Any:
    """``env`` if set and non-empty (a string), else ``gateway.<key>``, else ``default``."""
    if env:
        raw = os.environ.get(env, "").strip()
        if raw:
            return raw
    value: Any = _gateway_section(*_environment())
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def policy_mapping(section: str, env: str, legacy_file: Path) -> dict[str, Any] | None:
    """One machine policy as the legacy kebab-case mapping, or None when unconfigured.

    The legacy variable names an explicit JSON file and wins during the
    transition. Otherwise ``gateway.<section>`` is used, and the legacy default
    file only when the section is absent; both present is ambiguous. Ambiguity
    and invalid settings raise ``ValueError`` so callers treat the policy as
    invalid (purges and deletions off) rather than pick one.
    """
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    override = os.environ.get(env)
    if override:
        return _read_json_policy(Path(override).expanduser())
    try:
        configured = _gateway_section(*_environment()).get(section)
    except AudiaGenticError as exc:
        raise ValueError(str(exc)) from exc
    if configured is not None:
        if legacy_file.is_file():
            raise ValueError(f"gateway.{section} in settings and legacy {legacy_file} both exist; remove one")
        return {key.replace("_", "-"): value for key, value in configured.items()}
    return _read_json_policy(legacy_file)


def _read_json_policy(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    raw = json.loads(read_text_with_retry(path))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} is not a JSON object")
    return raw


def _environment() -> tuple[str, ...]:
    """What settings resolution depends on, so tests and re-pointed processes get fresh values."""
    try:
        cwd = str(Path.cwd())
    except OSError:
        cwd = ""
    names = ("AUDIAGENTIC_PROJECT", "AUDIAGENTIC_CONFIG", "XDG_CONFIG_HOME", "HOME", "APPDATA")
    return (cwd, *(os.environ.get(name, "") for name in names))


@lru_cache(maxsize=8)
def _gateway_section(cwd: str, *_cache_key: str) -> dict[str, Any]:
    from audiagentic.foundation.config.settings import resolve_settings

    section = resolve_settings(cwd=Path(cwd) if cwd else None).get("gateway")
    return section if isinstance(section, dict) else {}


__all__ = ["gateway_setting", "policy_mapping"]
