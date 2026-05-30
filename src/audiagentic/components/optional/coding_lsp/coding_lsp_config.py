"""LSP configuration: lsp.json parsing, language detection, server discovery.

Config is explicit (lsp.json) merged with auto-detected project languages.
Server availability is probed via foundation.system.probe.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from audiagentic.foundation.system.probe import ProbeSpec, probe_binary

from .lsp_lifecycle import ServerConfig

CODING_LSP_DIR = Path(".coding-lsp")

# ── default server specs ────────────────────────────────────────────────────

_DEFAULT_SERVERS: dict[str, ServerConfig] = {
    "python": ServerConfig(
        command=["pyright-langserver", "--stdio"],
        file_extensions=[".py", ".pyi"],
        workspace_config_files=["pyrightconfig.json"],
        label="Python (pyright)",
    ),
    "typescript": ServerConfig(
        command=["typescript-language-server", "--stdio"],
        file_extensions=[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"],
        workspace_config_files=["tsconfig.json"],
        label="TypeScript (tsserver)",
    ),
    "rust": ServerConfig(
        command=["rust-analyzer"],
        file_extensions=[".rs"],
        workspace_config_files=["Cargo.toml", "Cargo.lock"],
        label="Rust (rust-analyzer)",
    ),
    "cpp": ServerConfig(
        command=["clangd"],
        file_extensions=[".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx"],
        workspace_config_files=[".clangd", "compile_commands.json", "CMakeLists.txt"],
        label="C/C++ (clangd)",
    ),
}

# ── project detection markers ───────────────────────────────────────────────

_DETECTION_MARKERS: dict[str, list[str]] = {
    "python": ["pyproject.toml", "setup.py", "requirements.txt", "setup.cfg", "Pipfile"],
    "typescript": ["tsconfig.json", "package.json"],
    "rust": ["Cargo.toml", "Cargo.lock"],
    "cpp": [".clangd", "compile_commands.json", "CMakeLists.txt"],
}

# ── probe specs ─────────────────────────────────────────────────────────────

_PROBE_SPECS: dict[str, ProbeSpec] = {
    "python": ProbeSpec("python", ("pyright",)),
    "typescript": ProbeSpec("typescript", ("typescript-language-server",)),
    "rust": ProbeSpec("rust", ("rust-analyzer",)),
    "cpp": ProbeSpec("cpp", ("clangd",)),
}


# ── public API ──────────────────────────────────────────────────────────────


def available_language_specs() -> dict[str, dict[str, Any]]:
    """Return all available language server specifications."""
    return {name: asdict(cfg) for name, cfg in _DEFAULT_SERVERS.items()}


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
    """Scan project root for config files, return {language: marker_file}."""
    if isinstance(project_root, str):
        project_root = Path(project_root)
    detected: dict[str, str] = {}
    for language, markers in _DETECTION_MARKERS.items():
        for marker in markers:
            marker_path = project_root / marker
            if marker_path.exists():
                detected[language] = marker
                break
    return detected


def merge_server_configs(
    explicit: dict[str, dict[str, Any]],
    detected: dict[str, str],
    defaults: dict[str, ServerConfig] | None = None,
) -> dict[str, ServerConfig]:
    """Merge explicit config with detected languages.

    Explicit config wins. Detected languages fill gaps with defaults.
    """
    if defaults is None:
        defaults = _DEFAULT_SERVERS
    merged: dict[str, ServerConfig] = {}

    # Explicit config overrides everything
    for name, cfg_dict in explicit.items():
        cmd = cfg_dict.get("command")
        if cmd:
            merged[name] = ServerConfig(
                command=cmd if isinstance(cmd, list) else [cmd],
                file_extensions=cfg_dict.get("fileExtensions", cfg_dict.get("file_extensions", [])),
                workspace_config_files=cfg_dict.get("workspaceConfigFiles", cfg_dict.get("workspace_config_files", [])),
                settings=cfg_dict.get("settings", {}),
                label=cfg_dict.get("label", name),
            )

    # Detected languages fill gaps
    for lang in detected:
        if lang not in merged and lang in defaults:
            merged[lang] = defaults[lang]

    return merged


def discover_language_servers(project_root: Path | str) -> dict[str, bool]:
    """Discover available language servers for a project.

    Returns {language: available} for each configured/detected server.
    """
    if isinstance(project_root, str):
        project_root = Path(project_root)

    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    explicit = read_lsp_config(lsp_path)
    detected = detect_project_languages(project_root)
    servers = merge_server_configs(explicit, detected)

    results: dict[str, bool] = {}
    for name in servers:
        spec = _PROBE_SPECS.get(name)
        if spec:
            results[name] = probe_binary(spec.name, spec.requires, spec.probe_cmd)
        else:
            results[name] = shutil.which(servers[name].command[0]) is not None

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
