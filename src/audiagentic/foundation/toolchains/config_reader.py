"""Format-aware structured-config I/O shared by probes and the config patcher.

Detects TOML / JSON / YAML by file extension and provides load, dotted-key
lookup, and dump. Reads work for all three formats out of the box (``tomllib``
ships with Python). TOML *writing* requires an optional writer dependency
(``tomli_w`` or ``tomlkit``); without one, :func:`dump_config` raises a clear
error rather than emitting malformed TOML.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import tomllib
import yaml

from audiagentic.foundation.contracts.errors import AudiaGenticError


class _Unset:
    """Sentinel for "key absent" — distinct from a stored ``None``."""

    _instance: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()

_JSON = {".json"}
_YAML = {".yaml", ".yml"}
_TOML = {".toml"}


def detect_format(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in _JSON:
        return "json"
    if suffix in _YAML:
        return "yaml"
    if suffix in _TOML:
        return "toml"
    raise AudiaGenticError(
        code="VAL-CFG-001",
        kind="toolchains",
        message=f"unsupported config format for {path!r} (expected .json/.yaml/.toml)",
    )


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a config file into a dict. Missing file -> empty dict."""
    target = Path(path)
    if not target.exists():
        return {}
    text = target.read_text(encoding="utf-8")
    fmt = detect_format(target)
    if fmt == "json":
        data = json.loads(text) if text.strip() else {}
    elif fmt == "yaml":
        data = yaml.safe_load(text) or {}
    else:  # toml
        data = tomllib.loads(text)
    if not isinstance(data, dict):
        raise AudiaGenticError(
            code="VAL-CFG-002",
            kind="toolchains",
            message=f"config root is not a mapping: {path!r}",
        )
    return data


def read_config_value(path: str | Path, key_path: tuple[str, ...]) -> Any:
    """Return the value at ``key_path`` in the config, or :data:`UNSET` if absent."""
    node: Any = load_config(path)
    for segment in key_path:
        if not isinstance(node, dict) or segment not in node:
            return UNSET
        node = node[segment]
    return node


def dump_config(path: str | Path, data: dict[str, Any]) -> None:
    """Serialize ``data`` back to ``path`` in its detected format."""
    target = Path(path)
    fmt = detect_format(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    elif fmt == "yaml":
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    else:  # toml
        text = _dump_toml(data)
    target.write_text(text, encoding="utf-8")


def _dump_toml(data: dict[str, Any]) -> str:
    try:
        import tomli_w
    except ModuleNotFoundError:
        pass
    else:
        return tomli_w.dumps(data)
    try:
        import tomlkit
    except ModuleNotFoundError as exc:
        raise AudiaGenticError(
            code="CFG-TOML-001",
            kind="toolchains",
            message=(
                "writing TOML config requires a TOML writer; install 'tomli-w' "
                "(or 'tomlkit') to enable TOML-backed recipes"
            ),
        ) from exc
    return tomlkit.dumps(data)


__all__ = [
    "UNSET",
    "detect_format",
    "dump_config",
    "load_config",
    "read_config_value",
]
