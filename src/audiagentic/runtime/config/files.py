from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.io import atomic_write_text


def load_yaml_value(path: Path, default: Any = None) -> Any:
    """Load YAML from path.

    Missing files return ``default``.
    Malformed YAML raises ``SystemExit`` with the file path.
    ``None`` payloads normalize to ``default``.
    """
    if not path.exists():
        return default
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SystemExit(f"Invalid YAML config: {path}") from exc
    return default if data is None else data


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit(f"Invalid YAML config: {label} must be a mapping")
    return value


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load YAML mapping from path."""
    return require_mapping(load_yaml_value(path, {}), str(path))


def save_yaml_file(
    path: Path,
    payload: Any,
    *,
    sort_keys: bool = False,
    allow_unicode: bool = True,
    atomic: bool = False,
) -> None:
    text = yaml.safe_dump(
        payload,
        sort_keys=sort_keys,
        allow_unicode=allow_unicode,
        default_flow_style=False,
    )
    if atomic:
        atomic_write_text(path, text)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
