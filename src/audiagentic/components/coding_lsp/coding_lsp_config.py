"""LSP cache parsing, language detection, and server discovery helpers.

Active runtime config is resolved from feature state and bindings by
runtime_resolver.py. `lsp.json` is kept as generated cache/projection data.
Project-language detection is advisory for status/UI flows, not an implicit
source of server config. Server availability is probed via foundation.system.probe.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from audiagentic.foundation.components.dependencies import build_dependency_probes

from . import language_registry
from .lsp_lifecycle import ServerConfig

CODING_LSP_DIR = Path(".coding-lsp")

# Language facts (server command, extensions, detection markers, dependency)
# live in per-language YAML files loaded via `language_registry`. This module
# owns parsing/validation of generated cache (`lsp.json`) and runtime
# discovery helpers — not the catalog of supported languages.


# ── public API ──────────────────────────────────────────────────────────────


def _as_path(path: str | Path) -> Path:
    """Convert str to Path, pass through Path unchanged."""
    return Path(path) if isinstance(path, str) else path


def available_language_specs() -> dict[str, dict[str, Any]]:
    """Return all supported language server specifications, keyed by language."""
    return {
        lang_id: language_registry.server_spec_dict(spec)
        for lang_id, spec in language_registry.all_languages().items()
    }


def read_lsp_config(path: Path | str) -> dict[str, dict[str, Any]]:
    """Read lsp.json and return configured servers dict."""
    path = _as_path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("servers", {})


def write_lsp_config(path: Path | str, servers: dict[str, dict[str, Any]]) -> None:
    """Write server configuration to lsp.json."""
    path = _as_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "servers": servers}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def detect_project_languages(project_root: Path | str) -> dict[str, str]:
    """Scan project root for config files, return {language: marker_file}.

    Advisory only — detection never activates a language. Active languages
    come from feature state and active implementation bindings.
    """
    project_root = _as_path(project_root)
    detected: dict[str, str] = {}
    for language, spec in language_registry.all_languages().items():
        for marker in spec.detection_markers:
            if (project_root / marker).exists():
                detected[language] = marker
                break
    return detected


def load_runtime_servers(path: Path | str) -> tuple[dict[str, ServerConfig], list[str], bool]:
    """Load validated generated runtime cache from lsp.json.

    Returns (servers, errors, exists). This validates cache/projection data; the
    active runtime source is feature state plus bindings.
    """
    path = _as_path(path)
    if not path.exists():
        return {}, [], False

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {}, [f"Invalid lsp.json: {exc}"], True

    if not isinstance(raw, dict):
        return {}, ["Invalid lsp.json: top-level object required"], True

    servers_raw = raw.get("servers", {})
    if not isinstance(servers_raw, dict):
        return {}, ["Invalid lsp.json: 'servers' must be an object"], True

    servers: dict[str, ServerConfig] = {}
    errors: list[str] = []
    for name, cfg_dict in servers_raw.items():
        if not isinstance(cfg_dict, dict):
            errors.append(f"{name}: config must be an object")
            continue

        command = cfg_dict.get("command")
        if isinstance(command, str):
            command = [command]
        if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
            errors.append(f"{name}: command must be non-empty list[str]")
            continue

        file_extensions = cfg_dict.get("fileExtensions", cfg_dict.get("file_extensions", []))
        if not isinstance(file_extensions, list) or not file_extensions or not all(isinstance(item, str) and item for item in file_extensions):
            errors.append(f"{name}: file_extensions must be non-empty list[str]")
            continue

        workspace_files = cfg_dict.get("workspaceConfigFiles", cfg_dict.get("workspace_config_files", []))
        if not isinstance(workspace_files, list) or not all(isinstance(item, str) for item in workspace_files):
            errors.append(f"{name}: workspace_config_files must be list[str]")
            continue

        settings = cfg_dict.get("settings", {})
        if not isinstance(settings, dict):
            errors.append(f"{name}: settings must be an object")
            continue

        label = cfg_dict.get("label", name)
        if not isinstance(label, str):
            errors.append(f"{name}: label must be string")
            continue

        init_wait = float(cfg_dict.get("init-wait", 0))

        servers[name] = ServerConfig(
            command=command,
            file_extensions=file_extensions,
            workspace_config_files=workspace_files,
            settings=settings,
            label=label,
            init_wait=init_wait,
        )

    return servers, errors, True


def discover_language_servers(project_root: Path | str) -> dict[str, bool]:
    """Discover available language servers for a project.

    Returns {language: available} for each active language. Active languages are
    resolved from feature state + the active implementation's bindings (the source
    of truth), not from the generated lsp.json cache.
    """
    project_root = _as_path(project_root)

    from audiagentic.components.coding_lsp.runtime_resolver import (
        resolve_active_runtime_servers,
    )

    servers = resolve_active_runtime_servers(project_root)

    results: dict[str, bool] = {}
    for language, cfgs in servers.items():
        lang = language_registry.get_language(language)
        if lang is not None and lang.dependency is not None:
            probe = build_dependency_probes({lang.dependency.id: lang.dependency.cfg})
            results[language] = probe[lang.dependency.id]()
        else:
            first_cmd = cfgs[0].command if cfgs else []
            results[language] = bool(first_cmd) and shutil.which(first_cmd[0]) is not None

    return results


def resolve_server_for_file(
    file_path: Path | str,
    servers: dict[str, ServerConfig] | dict[str, list[ServerConfig]],
) -> ServerConfig | None:
    """Find a language server that handles a given file extension.

    Accepts both old single-server dict and new multi-server dict shapes.
    """
    file_path = _as_path(file_path)
    ext = file_path.suffix.lower()
    for value in servers.values():
        if isinstance(value, list):
            for cfg in value:
                if ext in cfg.file_extensions:
                    return cfg
        else:
            if ext in value.file_extensions:
                return value
    return None


def resolve_root_uri(project_root: Path | str) -> str:
    """Convert project root path to file:// URI."""
    return _as_path(project_root).resolve().as_uri()
