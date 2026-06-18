"""LSP config and dependency management API.

Handles language enable/disable, dependency installation, and config status.
Separated from lsp_api.py (LSP protocol operations) for single-responsibility.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.optional.coding_lsp import language_registry
from audiagentic.components.optional.coding_lsp.coding_lsp_config import (
    CODING_LSP_DIR,
    available_language_specs,
    detect_project_languages,
    load_runtime_servers,
    read_lsp_config,
    write_lsp_config,
)
from audiagentic.foundation.components.dependencies import (
    build_dependency_probes,
    build_dependency_workflow,
    detect_missing,
)
from audiagentic.foundation.workflow.invocation.steps import SequenceStep

from .lsp_api import _sync_to_providers, resolve_project_root

# Probes for every supported language (status checks scope by configured ids).
_LSP_PROBES = build_dependency_probes(language_registry.dependency_cfgs())


def _configured_language_ids(project_root: Path | None) -> list[str]:
    """Languages explicitly enabled in lsp.json — the sole source of activation."""
    if project_root is None:
        return []
    lsp_json = resolve_project_root(project_root) / CODING_LSP_DIR / "lsp.json"
    configured, _, _ = load_runtime_servers(lsp_json)
    return list(configured.keys())


def configured_dependency_ids(project_root: Path | None) -> list[str]:
    """Return dependency IDs for languages explicitly configured in lsp.json."""
    return language_registry.dependency_ids(_configured_language_ids(project_root))


def missing_configured_dependencies(project_root: Path | None) -> list[str]:
    """Dep ids for configured languages whose server binary is not installed."""
    configured = configured_dependency_ids(project_root)
    probes = build_dependency_probes(
        language_registry.dependency_cfgs(_configured_language_ids(project_root))
    )
    return detect_missing(probes, configured)


def config_status(root: str = ".") -> dict[str, Any]:
    project_root = resolve_project_root(root)
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    configured, config_errors, config_exists = load_runtime_servers(lsp_path)
    deps = _LSP_PROBES
    missing_deps = detect_missing(deps, configured_dependency_ids(project_root))

    language_status: dict[str, dict[str, Any]] = {}
    for lang, cfg in configured.items():
        lang_spec = language_registry.get_language(lang)
        dep_ids = (lang_spec.dependency.id,) if (lang_spec and lang_spec.dependency) else ()
        binary_ok = all(dep_id not in missing_deps for dep_id in dep_ids)
        language_status[lang] = {
            "configured": True,
            "binary_available": binary_ok,
            "command": cfg.command,
        }

    return {
        "project_root": str(project_root),
        "config_exists": config_exists,
        "config_valid": config_exists and not config_errors,
        "config_errors": config_errors,
        "languages": language_status,
        "missing_binaries": [lang for lang, status in language_status.items() if not status["binary_available"]],
        "detectable": list(detect_project_languages(project_root).keys()),
    }


def add_language(root: str, language: str) -> dict[str, Any]:
    project_root = resolve_project_root(root)
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    specs = available_language_specs()
    if language not in specs:
        return {"ok": False, "error": f"Unknown language: {language}. Available: {list(specs.keys())}"}
    configured = read_lsp_config(lsp_path)
    configured[language] = specs[language]
    write_lsp_config(lsp_path, configured)
    _sync_to_providers(project_root)
    return {"ok": True, "language": language, "path": str(lsp_path)}


def _install_succeeded(result: Any) -> bool:
    """Install returns a dict on early-return, else a StepResult with .status."""
    if isinstance(result, dict):
        return bool(result.get("ok", False))
    return getattr(result, "status", None) == "ok"


async def enable_language(root: str, language: str, *, run_with_output) -> dict[str, Any]:
    """Enable a language and install its server binaries in one step.

    The client only names the language; dependency ids and server binaries are
    resolved internally. Atomic for a newly added language: if the dependency
    install fails, the language is removed again so lsp.json never references an
    uninstalled server. Re-enabling an already-configured language is not rolled
    back on install failure.
    """
    project_root = resolve_project_root(root)
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    already_configured = language in read_lsp_config(lsp_path)

    added = add_language(str(project_root), language)
    if not added.get("ok"):
        return added

    missing = detect_missing(_LSP_PROBES, language_registry.dependency_ids([language]))
    if not missing:
        return {**added, "dependencies": "already installed"}

    install = await install_lsp_dependencies(
        missing, run_with_output=run_with_output, root=str(project_root)
    )
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
    from audiagentic.components.optional.coding_lsp.lsp_api import _session_manager

    project_root = resolve_project_root(root)
    lsp_path = project_root / CODING_LSP_DIR / "lsp.json"
    configured = read_lsp_config(lsp_path)
    if language not in configured:
        return {"ok": False, "error": f"Language not configured: {language}"}
    del configured[language]
    write_lsp_config(lsp_path, configured)
    _sync_to_providers(project_root)
    _session_manager.shutdown_session(project_root, language)
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
    names: list[str], *, run_with_output, root: str = "."
) -> dict[str, Any]:
    """Install language-server binaries — scoped to configured languages.

    The workflow is built only from dependencies of languages enabled in
    lsp.json, so a server for a non-enabled language can never be installed.
    Empty `names` installs the configured-but-missing set; explicit `names`
    must belong to configured languages or are rejected.
    """
    project_root = resolve_project_root(root)
    configured = configured_dependency_ids(project_root)
    dep_cfgs = language_registry.dependency_cfgs(_configured_language_ids(project_root))

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

    workflow = build_dependency_workflow(dep_cfgs, workflow_id="coding-lsp", action="install")
    filtered = tuple(s for s in workflow.steps if s.id in set(targets))
    seq = SequenceStep(id="install", steps=filtered, fail_fast=False)
    return await run_with_output(
        ctx=None,
        logger="coding-lsp.dependencies.install",
        heartbeat_message="LSP dependency install still running...",
        work=lambda _: seq.run({}),
    )


def list_missing(root: str = ".") -> dict[str, Any]:
    project_root = resolve_project_root(root)
    deps = _LSP_PROBES
    missing = detect_missing(deps, configured_dependency_ids(project_root))
    return {
        "project_root": str(project_root),
        "missing": missing,
        "hint": "Use lsp_install_dependencies to install missing servers." if missing else "All configured language servers are available.",
    }
