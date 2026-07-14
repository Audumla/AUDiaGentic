"""LSP config and dependency management API.

Handles language enable/disable, dependency installation, and config status.
Separated from lsp_api.py (LSP protocol operations) for single-responsibility.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Any

from audiagentic.components.coding_lsp import language_registry
from audiagentic.components.coding_lsp.coding_lsp_config import (
    CODING_LSP_DIR,
    available_language_specs,
    detect_project_languages,
    load_runtime_servers,
    write_lsp_config,
)
from audiagentic.components.coding_lsp.runtime_resolver import (
    active_language_bindings,
    active_lsp_implementation,
    resolve_active_runtime_servers,
)
from audiagentic.foundation.components.dependencies import (
    build_dependency_probes,
    build_dependency_workflow,
    detect_missing,
)
from audiagentic.foundation.features.base import FeatureState
from audiagentic.foundation.features.lifecycle import enable_implementation
from audiagentic.foundation.features.options import validate_option
from audiagentic.foundation.features.registry import get_implementation, get_implementations
from audiagentic.foundation.features.state import (
    get_feature_state,
    set_feature_state,
)
from audiagentic.foundation.steps import SequenceStep

from .lsp_api import _sync_to_providers, resolve_project_root

_COMPONENT_ID = "coding-lsp"


def _lsp_probes() -> dict[str, Any]:
    """Probes for every supported language (status checks scope by configured ids).

    Resolved lazily, not at import: the language catalog is sourced from the
    registered feature descriptors, which are not populated until
    register_all_components() runs.
    """
    return build_dependency_probes(language_registry.dependency_cfgs())


def _configured_language_ids(project_root: Path | None) -> list[str]:
    """Languages enabled in feature state and supported by the active implementation."""
    if project_root is None:
        return []
    return [binding.feature for binding in active_language_bindings(resolve_project_root(project_root))]


def configured_dependency_ids(project_root: Path | None) -> list[str]:
    """Return dependency IDs for active language features."""
    return language_registry.dependency_ids(_configured_language_ids(project_root))


def active_implementation_dependency_cfgs(project_root: Path | None) -> dict[str, dict[str, Any]]:
    if project_root is None:
        return {}
    implementation_id = active_lsp_implementation(resolve_project_root(project_root))
    descriptor = get_implementation(_COMPONENT_ID, implementation_id)
    return dict(descriptor.dependencies) if descriptor else {}


def active_dependency_cfgs(project_root: Path | None) -> dict[str, dict[str, Any]]:
    if project_root is None:
        return {}
    resolved = resolve_project_root(project_root)
    return {
        **active_implementation_dependency_cfgs(resolved),
        **language_registry.dependency_cfgs(_configured_language_ids(resolved)),
    }


def active_dependency_ids(project_root: Path | None) -> list[str]:
    return list(active_dependency_cfgs(project_root))


def _set_language_feature_enabled(project_root: Path, language: str, enabled: bool) -> None:
    state = get_feature_state(project_root, _COMPONENT_ID, "language", language)
    set_feature_state(
        project_root,
        _COMPONENT_ID,
        "language",
        language,
        FeatureState(enabled=enabled, options=state.options),
    )


def _regenerate_lsp_cache(project_root: Path) -> None:
    """Regenerate the lsp.json cache as a pure projection of feature state.

    lsp.json is a generated cache only — the source of truth is feature state plus
    active implementation bindings (`resolve_active_runtime_servers`, which already
    merges language-spec settings with feature `server-settings`). Enable/disable
    and option changes mutate only feature state, then call this to refresh the
    cache; nothing read-modify-writes individual lsp.json entries.
    """
    servers = resolve_active_runtime_servers(project_root)
    payload: dict[str, Any] = {}
    for language, cfgs in servers.items():
        if len(cfgs) == 1:
            cfg = cfgs[0]
            payload[language] = {
                "command": list(cfg.command),
                "fileExtensions": list(cfg.file_extensions),
                "workspaceConfigFiles": list(cfg.workspace_config_files),
                "settings": dict(cfg.settings),
                "label": cfg.label,
            }
        else:
            payload[language] = [
                {
                    "server_id": cfg.server_id,
                    "command": list(cfg.command),
                    "fileExtensions": list(cfg.file_extensions),
                    "workspaceConfigFiles": list(cfg.workspace_config_files),
                    "settings": dict(cfg.settings),
                    "label": cfg.label,
                }
                for cfg in cfgs
            ]
    write_lsp_config(project_root / CODING_LSP_DIR / "lsp.json", payload)


def set_language_option(root: str, language: str, key: str, value: Any) -> dict[str, Any]:
    project_root = resolve_project_root(root)
    spec = language_registry.get_language(language)
    if spec is None:
        return {"ok": False, "error": f"Unknown language: {language}"}
    schema = spec.options_schema.get(key)
    if schema is None:
        return {"ok": False, "error": f"unknown option: {key}"}
    try:
        validate_option(key, value, schema)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    state = get_feature_state(project_root, _COMPONENT_ID, "language", language)
    options = dict(state.options)
    options[key] = value
    set_feature_state(
        project_root,
        _COMPONENT_ID,
        "language",
        language,
        FeatureState(enabled=state.enabled, options=options),
    )
    _regenerate_lsp_cache(project_root)
    _sync_to_providers(project_root)
    return {"ok": True, "language": language, "option": key, "value": value}


def reset_language_option(root: str, language: str, key: str) -> dict[str, Any]:
    project_root = resolve_project_root(root)
    spec = language_registry.get_language(language)
    if spec is None:
        return {"ok": False, "error": f"Unknown language: {language}"}
    if key not in spec.options_schema:
        return {"ok": False, "error": f"unknown option: {key}"}
    state = get_feature_state(project_root, _COMPONENT_ID, "language", language)
    options = dict(state.options)
    removed = key in options
    options.pop(key, None)
    set_feature_state(
        project_root,
        _COMPONENT_ID,
        "language",
        language,
        FeatureState(enabled=state.enabled, options=options),
    )
    _regenerate_lsp_cache(project_root)
    _sync_to_providers(project_root)
    return {"ok": True, "language": language, "option": key, "removed": removed}


def missing_configured_dependencies(project_root: Path | None) -> list[str]:
    """Dep ids for active implementation/languages whose binaries are not installed."""
    configured = active_dependency_ids(project_root)
    probes = build_dependency_probes(active_dependency_cfgs(project_root))
    return detect_missing(probes, configured)


def config_status(root: str = ".") -> dict[str, Any]:
    project_root = resolve_project_root(root)
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    _cache_config, config_errors, config_exists = load_runtime_servers(lsp_path)
    configured = resolve_active_runtime_servers(project_root)
    deps = _lsp_probes()
    missing_deps = detect_missing(deps, configured_dependency_ids(project_root))

    language_status: dict[str, dict[str, Any]] = {}
    for lang, cfgs in configured.items():
        lang_spec = language_registry.get_language(lang)
        dep_ids = (lang_spec.dependency.id,) if (lang_spec and lang_spec.dependency) else ()
        binary_ok = all(dep_id not in missing_deps for dep_id in dep_ids)
        feature_state = get_feature_state(project_root, _COMPONENT_ID, "language", lang)
        language_status[lang] = {
            "configured": True,
            "feature_enabled": feature_state.enabled,
            "feature_options": dict(feature_state.options),
            "binary_available": binary_ok,
            "servers": [
                {
                    "server_id": cfg.server_id,
                    "command": cfg.command,
                }
                for cfg in cfgs
            ],
        }

    return {
        "project_root": str(project_root),
        # Health of the generated .coding-lsp/lsp.json cache/projection — not the
        # source of truth for configuration (that is feature state + bindings).
        "projection_cache": {
            "exists": config_exists,
            "valid": config_exists and not config_errors,
            "errors": config_errors,
        },
        "implementation": active_lsp_implementation(project_root),
        "languages": language_status,
        "missing_binaries": [lang for lang, status in language_status.items() if not status["binary_available"]],
        "detectable": list(detect_project_languages(project_root).keys()),
    }


def list_implementations(root: str = ".") -> dict[str, Any]:
    from audiagentic.foundation.features.registry import is_default_implementation

    project_root = resolve_project_root(root)
    implementations = get_implementations(_COMPONENT_ID)
    return {
        "active": active_lsp_implementation(project_root),
        "implementations": {
            implementation_id: {
                "display_name": descriptor.display_name,
                "description": descriptor.description,
                "is_default": is_default_implementation(descriptor),
            }
            for implementation_id, descriptor in implementations.items()
        },
    }


def select_implementation(root: str, implementation: str) -> dict[str, Any]:
    project_root = resolve_project_root(root)
    result = enable_implementation(project_root, _COMPONENT_ID, implementation)
    if not result.get("ok"):
        return result
    _sync_to_providers(project_root)
    return result


def get_config(root: str = ".", implementation_id: str | None = None) -> dict[str, Any]:
    """Return resolved config and settable-option schema for an LSP implementation.

    ``schema`` lets a caller discover every option this implementation accepts
    (type, description, required, default, allowed values) generically, then
    set any of them via ``set_config`` — e.g. ag-lsp's ``mutation-enabled``.
    """
    from audiagentic.foundation.features.options import option_schema_to_dict
    from audiagentic.foundation.features.registry import is_default_implementation
    from audiagentic.foundation.features.state import get_implementation_state

    project_root = resolve_project_root(root)
    target_impl = implementation_id or active_lsp_implementation(project_root)
    if not target_impl:
        return {"implementation": None, "config": {}, "schema": {}, "error": "No active implementation"}

    desc = get_implementation(_COMPONENT_ID, target_impl)
    impl_state = get_implementation_state(project_root, _COMPONENT_ID, target_impl)

    config = dict(impl_state.options) if impl_state.options else {}
    schema: dict[str, Any] = {}

    if desc and desc.options_schema:
        for key, opt_schema in desc.options_schema.items():
            if key not in config and opt_schema.default is not None:
                config[key] = opt_schema.default
            schema[key] = option_schema_to_dict(opt_schema)

    return {
        "implementation": target_impl,
        "config": config,
        "schema": schema,
        "enabled": impl_state.enabled,
        "is_default": bool(desc and is_default_implementation(desc)),
    }


def set_config(root: str, implementation_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist config updates for an LSP implementation."""
    from audiagentic.foundation.features.base import ImplementationState
    from audiagentic.foundation.features.state import (
        get_implementation_state,
        set_implementation_state,
    )

    project_root = resolve_project_root(root)
    desc = get_implementation(_COMPONENT_ID, implementation_id)
    if desc is None:
        return {"ok": False, "error": f"unknown LSP implementation: {implementation_id}"}

    if desc.options_schema:
        for key, value in updates.items():
            schema = desc.options_schema.get(key)
            if schema is None:
                if not any(s.allow_unknown for s in desc.options_schema.values()):
                    return {
                        "ok": False,
                        "error": f"unknown option: {key!r} for implementation {implementation_id!r}",
                        "valid_options": list(desc.options_schema.keys()),
                    }
            else:
                from audiagentic.foundation.contracts.errors import AudiaGenticError
                try:
                    validate_option(key, value, schema)
                except (AudiaGenticError, ValueError) as exc:
                    return {"ok": False, "error": f"invalid value for option {key!r}: {exc}"}

    impl_state = get_implementation_state(project_root, _COMPONENT_ID, implementation_id)
    options = dict(impl_state.options)
    options.update(updates)

    new_state = ImplementationState(enabled=impl_state.enabled, options=options)
    set_implementation_state(project_root, _COMPONENT_ID, implementation_id, new_state)

    return {
        "ok": True,
        "implementation": implementation_id,
        "config": options,
        "updated_keys": list(updates.keys()),
    }


def add_language(root: str, language: str) -> dict[str, Any]:
    project_root = resolve_project_root(root)
    specs = available_language_specs()
    if language not in specs:
        return {"ok": False, "error": f"Unknown language: {language}. Available: {list(specs.keys())}"}
    # Enablement is feature state; lsp.json is then regenerated as a pure cache.
    _set_language_feature_enabled(project_root, language, True)
    _regenerate_lsp_cache(project_root)
    _sync_to_providers(project_root)
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    return {"ok": True, "language": language, "path": str(lsp_path)}


def _install_succeeded(result: Any) -> bool:
    """Install returns a dict on early-return, else a StepResult with .status."""
    if isinstance(result, dict):
        return bool(result.get("ok", False))
    return getattr(result, "status", None) == "ok"


async def enable_language(root: str, language: str) -> dict[str, Any]:
    """Enable a language and install its server binaries in one step.

    The client only names the language; dependency ids and server binaries are
    resolved internally. Atomic for a newly added language: if the dependency
    install fails, the language feature is disabled again so generated cache
    never references an uninstalled server. Re-enabling an already-configured
    language is not rolled back on install failure.
    """
    project_root = resolve_project_root(root)
    already_configured = get_feature_state(project_root, _COMPONENT_ID, "language", language).enabled

    added = add_language(str(project_root), language)
    if not added.get("ok"):
        return added

    missing = detect_missing(_lsp_probes(), language_registry.dependency_ids([language]))
    if not missing:
        return {**added, "dependencies": "already installed"}

    install = await install_lsp_dependencies(missing, root=str(project_root))
    if _install_succeeded(install):
        return {**added, "installed": missing, "install": install}

    if not already_configured:
        remove_language(str(project_root), language)
    return {
        "ok": False,
        "language": language,
        "error": "dependency install failed; language not enabled",
        "install": install,
        "rolled_back": not already_configured,
    }


def remove_language(root: str, language: str) -> dict[str, Any]:
    from audiagentic.components.coding_lsp.lsp_api import _session_manager

    project_root = resolve_project_root(root)
    state = get_feature_state(project_root, _COMPONENT_ID, "language", language)
    if not state.enabled:
        return {"ok": False, "error": f"Language not configured: {language}"}
    # Disable in feature state; lsp.json is then regenerated as a pure cache.
    _set_language_feature_enabled(project_root, language, False)
    _regenerate_lsp_cache(project_root)
    _session_manager.shutdown_session(project_root, language)
    # Prune the removed language from provider configs, then sync remaining state.
    from audiagentic.components.coding_lsp.language_servers_sync import (
        prune_language_servers_from_providers,
    )
    prune_language_servers_from_providers(project_root)
    _sync_to_providers(project_root)
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    return {"ok": True, "language": language, "path": str(lsp_path)}


def list_languages() -> dict[str, Any]:
    specs = available_language_specs()
    return {
        "languages": {
            name: {
                "command": spec["command"],
                "file_extensions": spec.get("file_extensions", []),
            }
            for name, spec in specs.items()
        },
    }


async def install_lsp_dependencies(
    names: list[str], *, root: str = "."
) -> dict[str, Any]:
    """Install language-server binaries — scoped to configured languages.

    The workflow is built from the active implementation plus enabled language
    feature dependencies, so a server for a non-enabled language can never be
    installed. Empty `names` installs the configured-but-missing set; explicit
    `names` must belong to configured dependencies or are rejected.
    """
    project_root = resolve_project_root(root)
    configured = active_dependency_ids(project_root)
    dep_cfgs = active_dependency_cfgs(project_root)

    if names:
        stray = [n for n in names if n not in configured]
        if stray:
            return {
                "ok": False,
                "error": f"not enabled for this project: {stray}. Configured: {configured}",
            }
        targets = list(names)
    else:
        targets = missing_configured_dependencies(project_root)

    if not targets:
        return {"ok": True, "installed": [], "skipped": "no missing dependencies for configured languages"}

    from audiagentic.components.coding_lsp.language_servers_sync import (
        provision_provider_lsp_support,
    )

    workflow = build_dependency_workflow(dep_cfgs, workflow_id="coding-lsp", action="install")
    filtered = tuple(s for s in workflow.steps if s.id in set(targets))
    seq = SequenceStep(id="install", steps=filtered, fail_fast=False)

    def _work():
        # Provider-side LSP provisioning (e.g. pi installing pi-lens) runs as part
        # of this explicit install — gated on coding-lsp being enabled, never on the
        # enable event. Best-effort: it never fails the server install.
        provision_provider_lsp_support(project_root)
        result = seq.run({})
        return {
            "status": result.status,
            "outputs": result.outputs,
            "progress": [asdict(p) for p in result.progress],
            "question": asdict(result.question) if result.question else None,
            "reason": result.reason,
        }

    return await asyncio.to_thread(_work)


def list_missing(root: str = ".") -> dict[str, Any]:
    project_root = resolve_project_root(root)
    deps = _lsp_probes()
    missing = detect_missing(deps, configured_dependency_ids(project_root))
    return {
        "project_root": str(project_root),
        "missing": missing,
        "hint": (
            "Missing servers auto-install on first file-based LSP use; "
            "use lsp_install_dependencies only for eager install or retry."
            if missing
            else "All configured language servers are available."
        ),
    }
