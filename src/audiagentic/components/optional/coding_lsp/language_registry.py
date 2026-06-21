"""LSP language adapter over the foundation feature catalog.

Each supported language is registered by the generic foundation feature loader
from `config/components/optional/coding-lsp/`. This module does not scan YAML or
own a separate catalog; it adapts registered coding-lsp `FeatureDescriptor`s
into the LSP runtime shape used by session startup, detection, and dependency
installation.

`LanguageSpec` remains coding-lsp local because server commands, file
extensions, detection markers, LSP language IDs, and probe/install recipes are
LSP-domain facts rather than foundation feature fields.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any

from audiagentic.foundation.components.ids import COMPONENT_CODING_LSP
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.foundation.features.base import FeatureDescriptor, OptionSchema
from audiagentic.foundation.features.options import load_option_schema
from audiagentic.foundation.toolchains.detect import tool_available

_REGISTRY: dict[str, LanguageSpec] = {}
_LOADED = False


def _lsp_error(code_number: int, message: str, **details: Any) -> AudiaGenticError:
    return make_error(
        prefix="VAL",
        component="LSP",
        number=code_number,
        kind="coding-lsp",
        message=message,
        details=details,
    )


@dataclass(frozen=True)
class LanguageDependency:
    """A language's LSP server dependency.

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
    options_schema: dict[str, OptionSchema] = field(default_factory=dict)


def _is_language_feature(data: dict[str, Any]) -> bool:
    return (
        data.get("type") == "feature"
        and data.get("kind") == "language"
        and data.get("parent") == "coding-lsp"
    )


def language_spec_from_data(data: dict[str, Any], *, source: str = "<descriptor>") -> LanguageSpec:
    """Build a LanguageSpec from a coding-lsp language feature mapping.

    The mapping is the descriptor body — identical whether it came from the
    registered FeatureDescriptor's ``raw`` or from a YAML file on disk.
    """
    if not _is_language_feature(data):
        raise _lsp_error(
            1,
            f"{source}: expected coding-lsp language feature",
            source=source,
            descriptor_type=data.get("type"),
            kind=data.get("kind"),
            parent=data.get("parent"),
        )
    server = data.get("server") or {}
    dep_raw = data.get("dependency") or {}
    dependencies = data.get("dependencies") or {}
    if not dep_raw and dependencies:
        if not isinstance(dependencies, dict):
            raise _lsp_error(2, f"{source}: dependencies must be a mapping", source=source)
        dep_id, dep_cfg = next(iter(dependencies.items()))
        dep_raw = {"id": dep_id, **dict(dep_cfg or {})}
    dependency = None
    if dep_raw:
        dep_id = dep_raw["id"]
        cfg = {k: v for k, v in dep_raw.items() if k != "id"}
        dependency = LanguageDependency(id=dep_id, cfg=cfg)
    lang_id = data["id"]
    return LanguageSpec(
        id=lang_id,
        display_name=data.get("display-name", lang_id),
        language_id=data.get("language-id", lang_id),
        command=tuple(server.get("command", [])),
        file_extensions=tuple(server.get("file-extensions", [])),
        workspace_config_files=tuple(server.get("workspace-config-files", [])),
        detection_markers=tuple(data.get("detection-markers", [])),
        dependency=dependency,
        settings=dict(server.get("settings", {})),
        options_schema=load_option_schema(data.get("options-schema")),
    )


def language_spec_from_feature(descriptor: FeatureDescriptor) -> LanguageSpec:
    spec = language_spec_from_data(descriptor.raw, source=f"feature:{descriptor.feature_id}")
    return LanguageSpec(
        id=spec.id,
        display_name=spec.display_name,
        language_id=spec.language_id,
        command=spec.command,
        file_extensions=spec.file_extensions,
        workspace_config_files=spec.workspace_config_files,
        detection_markers=spec.detection_markers,
        dependency=spec.dependency,
        settings=spec.settings,
        options_schema=descriptor.options_schema,
    )


def _load_from_feature_registry() -> bool:
    """Populate the registry from registered coding-lsp language features.

    The foundation feature loader already parses every language YAML into a
    FeatureDescriptor whose ``raw`` is the descriptor body, so the registered
    catalog is the source of truth. Returns True if any language was loaded.
    """
    # Imported lazily so module import does not depend on registration order.
    from audiagentic.foundation.features.registry import get_features

    loaded = False
    for descriptor in get_features(COMPONENT_CODING_LSP, "language").values():
        if not isinstance(descriptor.raw, dict) or not _is_language_feature(descriptor.raw):
            continue
        spec = language_spec_from_feature(descriptor)
        _REGISTRY[spec.id] = spec
        loaded = True
    return loaded


def _ensure_feature_catalog_loaded() -> None:
    """Load component descriptors so coding-lsp language features are registered."""
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.features.registry import get_features

    if get_features(COMPONENT_CODING_LSP, "language"):
        return
    register_all_components()


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    _ensure_feature_catalog_loaded()
    _load_from_feature_registry()
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
