"""LSP configuration: lsp.json parsing, language detection, server discovery.

Active runtime config is explicit (`lsp.json`) only. Project-language detection
is advisory for status/UI flows, not an implicit source of server config.
Server availability is probed via foundation.system.probe.
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
# owns parsing/validation of the active config (`lsp.json`) and runtime
# discovery — not the catalog of supported languages.


# ── public API ──────────────────────────────────────────────────────────────


def available_language_specs() -> dict[str, dict[str, Any]]:
    """Return all supported language server specifications, keyed by language."""
    return {
        lang_id: language_registry.server_spec_dict(spec)
        for lang_id, spec in language_registry.all_languages().items()
    }


def read_lsp_config(path: Path | str) -> dict[str, dict[str, Any]]:
    """Read lsp.json and return configured servers dict."""
    if isinstance(path, str):
        path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("servers", {})


def write_lsp_config(path: Path | str, servers: dict[str, dict[str, Any]]) -> None:
    """Write server configuration to lsp.json."""
    if isinstance(path, str):
        path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "servers": servers}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def detect_project_languages(project_root: Path | str) -> dict[str, str]:
    """Scan project root for config files, return {language: marker_file}.

    Advisory only — detection never activates a language. Active languages
    come solely from `lsp.json`.
    """
    if isinstance(project_root, str):
        project_root = Path(project_root)
    detected: dict[str, str] = {}
    for language, spec in language_registry.all_languages().items():
        for marker in spec.detection_markers:
            if (project_root / marker).exists():
                detected[language] = marker
                break
    return detected


def load_runtime_servers(path: Path | str) -> tuple[dict[str, ServerConfig], list[str], bool]:
    """Load validated runtime servers from lsp.json.

    Returns (servers, errors, exists). Runtime is config-first:
    missing or invalid config yields no synthesized server entries.
    """
    if isinstance(path, str):
        path = Path(path)
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

        servers[name] = ServerConfig(
            command=command,
            file_extensions=file_extensions,
            workspace_config_files=workspace_files,
            settings=settings,
            label=label,
        )

    return servers, errors, True


def discover_language_servers(project_root: Path | str) -> dict[str, bool]:
    """Discover available language servers for a project.

    Returns {language: available} for each configured/detected server.
    """
    if isinstance(project_root, str):
        project_root = Path(project_root)

    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    servers, _, _ = load_runtime_servers(lsp_path)

    results: dict[str, bool] = {}
    for name in servers:
        lang = language_registry.get_language(name)
        if lang is not None and lang.dependency is not None:
            probe = build_dependency_probes({lang.dependency.id: lang.dependency.cfg})
            results[name] = probe[lang.dependency.id]()
        else:
            command = servers[name].command
            results[name] = bool(command) and shutil.which(command[0]) is not None

    return results


def resolve_server_for_file(file_path: Path | str, servers: dict[str, ServerConfig]) -> ServerConfig | None:
    """Find the language server that handles a given file extension."""
    if isinstance(file_path, str):
        file_path = Path(file_path)
    ext = file_path.suffix.lower()
    for server in servers.values():
        if ext in server.file_extensions:
            return server
    return None


def resolve_root_uri(project_root: Path | str) -> str:
    """Convert project root path to file:// URI."""
    if isinstance(project_root, str):
        project_root = Path(project_root)
    return project_root.resolve().as_uri()
