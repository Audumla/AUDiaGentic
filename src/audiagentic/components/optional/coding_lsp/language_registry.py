"""Per-language LSP configuration registry.

Each supported language is declared in its own YAML file under
`config/components/optional/coding-lsp/`, mirroring the per-provider surface
descriptor pattern. A language file owns everything about that language:
server command, file extensions, detection markers, LSP languageId, and its
single dependency (probe + install recipe).

The coding-lsp component itself owns no language facts — it orchestrates
(enable/install/propagate) over this registry.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.foundation.toolchains.detect import tool_available
from audiagentic.paths import SRC_ROOT
from audiagentic.runtime.config import load_yaml_file

_LANGUAGE_CONFIG_DIR = SRC_ROOT / "audiagentic" / "config" / "components" / "optional" / "coding-lsp"

_REGISTRY: dict[str, LanguageSpec] = {}
_LOADED = False


@dataclass(frozen=True)
class LanguageDependency:
    """A language's single LSP server dependency.

    `cfg` is the raw dependency block (minus `id`) in the exact shape the
    foundation dependency workflow consumes: probe + toolchain/package or
    via/platform-fallback, optional display-name/uninstall-package/requires.
    """
    id: str
    cfg: dict[str, Any]


@dataclass(frozen=True)
class LanguageSpec:
    id: str
    display_name: str
    language_id: str
    command: tuple[str, ...]
    file_extensions: tuple[str, ...]
    workspace_config_files: tuple[str, ...] = ()
    detection_markers: tuple[str, ...] = ()
    dependency: LanguageDependency | None = None
    settings: dict[str, Any] = field(default_factory=dict)


def load_language_from_yaml(path: Path) -> LanguageSpec:
    data = load_yaml_file(path)
    if data.get("type") != "language":
        raise ValueError(f"{path.name}: expected type=language, got {data.get('type')}")
    server = data.get("server") or {}
    dep_raw = data.get("dependency") or {}
    dependency = None
    if dep_raw:
        dep_id = dep_raw["id"]
        cfg = {k: v for k, v in dep_raw.items() if k != "id"}
        dependency = LanguageDependency(id=dep_id, cfg=cfg)
    lang_id = data["id"]
    spec = LanguageSpec(
        id=lang_id,
        display_name=data.get("display-name", lang_id),
        language_id=data.get("language-id", lang_id),
        command=tuple(server.get("command", [])),
        file_extensions=tuple(server.get("file-extensions", [])),
        workspace_config_files=tuple(server.get("workspace-config-files", [])),
        detection_markers=tuple(data.get("detection-markers", [])),
        dependency=dependency,
        settings=dict(server.get("settings", {})),
    )
    _REGISTRY[spec.id] = spec
    return spec


def load_all_languages(config_dir: Path | None = None) -> dict[str, LanguageSpec]:
    target = (config_dir or _LANGUAGE_CONFIG_DIR).resolve()
    if target.exists():
        for path in sorted(target.glob("*.yaml")):
            try:
                data = load_yaml_file(path)
            except Exception:  # noqa: BLE001
                continue
            if data.get("type") == "language":
                load_language_from_yaml(path)
    return dict(_REGISTRY)


def _ensure_loaded() -> None:
    global _LOADED
    if not _LOADED:
        load_all_languages()
        _LOADED = True


def all_languages() -> dict[str, LanguageSpec]:
    _ensure_loaded()
    return dict(_REGISTRY)


def get_language(language_id: str) -> LanguageSpec | None:
    _ensure_loaded()
    return _REGISTRY.get(language_id)


def server_spec_dict(spec: LanguageSpec) -> dict[str, Any]:
    """Server config shape written into lsp.json `servers.<lang>`."""
    return {
        "command": list(spec.command),
        "file_extensions": list(spec.file_extensions),
        "workspace_config_files": list(spec.workspace_config_files),
        "settings": dict(spec.settings),
        "label": spec.display_name,
    }


def dependency_cfgs(language_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Return foundation dep-cfg dict keyed by dep id for the given languages.

    `language_ids=None` returns deps for every supported language. Restricting
    to configured languages is how install/status stay scoped: a non-enabled
    language's server never enters the workflow.
    """
    _ensure_loaded()
    langs = _REGISTRY.values() if language_ids is None else (
        _REGISTRY[lid] for lid in language_ids if lid in _REGISTRY
    )
    result: dict[str, dict[str, Any]] = {}
    for spec in langs:
        if spec.dependency is not None:
            result[spec.dependency.id] = dict(spec.dependency.cfg)
    return result


def dependency_ids(language_ids: list[str] | None = None) -> list[str]:
    """Dep ids for the given languages (or all)."""
    _ensure_loaded()
    langs = _REGISTRY.values() if language_ids is None else (
        _REGISTRY[lid] for lid in language_ids if lid in _REGISTRY
    )
    return [spec.dependency.id for spec in langs if spec.dependency is not None]


def probe_typescript_language_server() -> bool:
    """typescript-language-server also needs TypeScript's tsserver runtime."""
    return tool_available("typescript-language-server") and tool_available("tsserver")


def probe_rust_analyzer() -> bool:
    """Rustup may provide a shim on PATH even when rust-analyzer is unavailable."""
    if not tool_available("rust-analyzer"):
        return False
    try:
        result = subprocess.run(
            ["rust-analyzer", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError:
        return False
    return result.returncode == 0
