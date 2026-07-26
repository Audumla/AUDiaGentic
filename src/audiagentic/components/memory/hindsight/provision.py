"""Hindsight provisioning entrypoint — family-preference orchestration over providers_api.

Memory orchestrates by querying each provider's automation capabilities and selecting
the first supported family in fixed order (managed-hooks > managed-mcp > plugin-entry).
The provider-owned side (hook/mcp/plugin *entries*) is delegated to providers_api family
functions. The Hindsight-owned side (~/.hindsight artifacts: codex scripts + config,
pi host block) is expressed as declarative recipes in ``recipes/`` and run through the
generic recipe engine — no hand-rolled per-provider writers, no provider-id branches.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.export import (
    HindsightBackendConfig,
    build_hindsight_backend,
)
from audiagentic.components.memory.hindsight.mcp_recipe import (
    HINDSIGHT_MANAGED_ID,
    build_hindsight_managed_entry,
    hindsight_ownership_scope,
)
from audiagentic.components.providers.providers_api import (
    ManagedHooksEntry,
    ManagedHooksRequest,
    ManagedHooksResult,
    ManagedMcpRequest,
    ManagedMcpResult,
    PluginEntryRequest,
    PluginEntryResult,
    list_provider_descriptors,
    list_providers,
    manage_hook_entries,
    manage_mcp_entries,
    manage_plugin_entry,
)
from audiagentic.foundation.toolchains.recipe_contract import RecipeResult
from audiagentic.foundation.toolchains.recipe_execution import execute_recipe_mode
from audiagentic.foundation.toolchains.recipe_loader import load_recipe_from_yaml

_HINDSIGHT_OWNERSHIP = "hindsight"

# Provider -> Hindsight-owned artifact recipe. Providers absent from this table
# have no Hindsight-owned side files; their integration is entirely the provider
# managed family (mcp/plugin). Adding a new integration is a YAML drop-in here,
# never new Python.
_RECIPE_DIR = Path(__file__).resolve().parents[3] / "config" / "components" / "memory" / "recipes"
_ARTIFACT_RECIPES = {
    "codex": "hindsight-codex.yaml",
    "pi": "hindsight-pi.yaml",
}

_HOOK_EVENTS = (
    ("session_start.py", "SessionStart", 5),
    ("recall.py", "UserPromptSubmit", 12),
    ("retain.py", "Stop", 30),
)


def _quote_command_part(value: Path | str) -> str:
    text = str(value)
    return '"' + text.replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
# Hindsight-owned artifact recipes — declarative, run through the generic engine
# ---------------------------------------------------------------------------

def _artifact_recipe_path(provider_id: str) -> Path | None:
    """Return the Hindsight-owned artifact recipe for a provider, or None."""
    name = _ARTIFACT_RECIPES.get(provider_id)
    return _RECIPE_DIR / name if name else None


def _recipe_params(backend: HindsightBackendConfig) -> dict[str, str]:
    """Build provider-agnostic recipe parameters from backend config.

    Recipe-level defaults supply per-provider bank ids and the literal
    ``{project}`` template, so no provider-id branch is needed here.
    """
    params = {"URL": backend.base_url, "TOKEN": backend.api_key or ""}
    if backend.bank_id:
        params["BANK_ID"] = backend.bank_id
    return params


def _run_artifact_recipe(
    provider_id: str, backend: HindsightBackendConfig, mode: str,
) -> RecipeResult | None:
    """Run a provider's Hindsight-owned artifact recipe in *mode*, or None if absent.

    Params are filtered to the recipe's declared parameters so each recipe
    receives only what it uses (the strict materializer rejects unknown keys).
    """
    path = _artifact_recipe_path(provider_id)
    if path is None:
        return None
    declared = {p.name for p in load_recipe_from_yaml(path).parameters}
    params = {k: v for k, v in _recipe_params(backend).items() if k in declared}
    return execute_recipe_mode(path, params, mode)


# ---------------------------------------------------------------------------
# Family resolution — fixed preference order, no provider-id branches
# ---------------------------------------------------------------------------

def _hindsight_families() -> list[str]:
    """Return the fixed Hindsight family preference order."""
    return ["managed-hooks", "managed-mcp", "plugin-entry"]


def _provider_capability_map() -> dict[str, frozenset[str]]:
    """Return provider automation families through the sanctioned public query."""
    return {
        str(descriptor["provider_id"]): frozenset(
            str(capability["family_id"])
            for capability in descriptor.get("automation_capabilities", [])
        )
        for descriptor in list_provider_descriptors()
    }


def _resolve_family(
    provider_id: str,
    capability_map: dict[str, frozenset[str]] | None = None,
) -> str | None:
    """Resolve the first supported family for a provider in Hindsight preference order.

    Fixed order: managed-hooks > managed-mcp > plugin-entry.
    If none supported, returns None (guidance-only fallback).
    """
    supported = (capability_map or _provider_capability_map()).get(provider_id)
    if supported is None:
        return None
    for family_id in _hindsight_families():
        if family_id in supported:
            return family_id
    return None


# ---------------------------------------------------------------------------
# Codex managed-hooks integration — Hindsight-owned artifacts
# ---------------------------------------------------------------------------

def _build_codex_hook_entries() -> tuple[ManagedHooksEntry, ...]:
    """Build the Codex hook entries pointing at the recipe-fetched scripts.

    The scripts themselves and codex.json are provisioned by the artifact recipe;
    these entries only register the per-event commands in Codex's own config.
    """
    interpreter_path = Path(sys.executable)
    script_dir = Path.home() / ".hindsight" / "codex" / "scripts"
    return tuple(
        ManagedHooksEntry(
            managed_id=f"hindsight/{event.lower()}",
            event=event,
            command=f"{_quote_command_part(interpreter_path)} {_quote_command_part(script_dir / script_name)}",
            timeout=timeout,
        )
        for script_name, event, timeout in _HOOK_EVENTS
    )


# ---------------------------------------------------------------------------
# Family-specific apply/prune/status — provider-owned entries only.
# Hindsight-owned side artifacts (codex scripts + config, pi host block) are
# provisioned by the declarative artifact recipe, not here.
# ---------------------------------------------------------------------------

def _apply_hooks(provider_id: str, project_root: Path) -> ManagedHooksResult:
    """Register the provider-owned Codex hook entries (scripts/config are recipe-owned)."""
    managed_entries = _build_codex_hook_entries()

    return manage_hook_entries(
        project_root,
        provider_id,
        mode="apply",
        request=ManagedHooksRequest(
            ownership_scope=_HINDSIGHT_OWNERSHIP,
            entries=managed_entries,
        ),
    )


def _prune_hooks(provider_id: str, project_root: Path) -> ManagedHooksResult:
    """Prune managed-hooks integration for a provider."""
    return manage_hook_entries(
        project_root,
        provider_id,
        mode="prune",
        request=ManagedHooksRequest(
            ownership_scope=_HINDSIGHT_OWNERSHIP,
            entries=(),
        ),
    )


def _status_hooks(provider_id: str, project_root: Path) -> ManagedHooksResult:
    """Status query for managed-hooks integration."""
    return manage_hook_entries(
        project_root,
        provider_id,
        mode="status",
        request=ManagedHooksRequest(
            ownership_scope=_HINDSIGHT_OWNERSHIP,
            entries=(),
        ),
    )


def _apply_mcp(provider_id: str, project_root: Path, backend: HindsightBackendConfig) -> ManagedMcpResult:
    """Register the provider-owned MCP entry (any host-side config is recipe-owned)."""
    return manage_mcp_entries(
        project_root,
        provider_id,
        mode="apply",
        request=ManagedMcpRequest(
            ownership_scope=hindsight_ownership_scope(backend),
            entries=(build_hindsight_managed_entry(backend),),
        ),
    )


def _prune_mcp(provider_id: str, project_root: Path, backend: HindsightBackendConfig) -> ManagedMcpResult:
    """Prune the provider-owned MCP entry (any host-side config is recipe-owned)."""
    return manage_mcp_entries(
        project_root,
        provider_id,
        mode="prune",
        request=ManagedMcpRequest(
            ownership_scope=hindsight_ownership_scope(backend),
            entries=(),
        ),
    )


def _status_mcp(provider_id: str, project_root: Path, backend: HindsightBackendConfig) -> ManagedMcpResult:
    """Status query for managed-mcp integration."""
    return manage_mcp_entries(
        project_root,
        provider_id,
        mode="status",
        request=ManagedMcpRequest(
            ownership_scope=hindsight_ownership_scope(backend),
            entries=(build_hindsight_managed_entry(backend),),
        ),
    )


def _apply_plugin(provider_id: str, project_root: Path, backend: HindsightBackendConfig) -> PluginEntryResult:
    """Apply plugin-entry integration for a provider."""
    return manage_plugin_entry(
        project_root,
        provider_id,
        mode="apply",
        request=PluginEntryRequest(
            entry_id=HINDSIGHT_MANAGED_ID,
            ownership_scope=hindsight_ownership_scope(backend),
        ),
    )


def _prune_plugin(provider_id: str, project_root: Path) -> PluginEntryResult:
    """Prune plugin-entry integration for a provider."""
    return manage_plugin_entry(
        project_root,
        provider_id,
        mode="prune",
        request=PluginEntryRequest(
            entry_id=HINDSIGHT_MANAGED_ID,
            ownership_scope=_HINDSIGHT_OWNERSHIP,
        ),
    )


# ---------------------------------------------------------------------------
# Per-provider dispatch — provider-owned family + Hindsight-owned artifact recipe
# ---------------------------------------------------------------------------

def _apply_family(family_id: str | None, pid: str, root: Path, backend: HindsightBackendConfig) -> Any:
    if family_id == "managed-hooks":
        return _apply_hooks(pid, root)
    if family_id == "managed-mcp":
        return _apply_mcp(pid, root, backend)
    if family_id == "plugin-entry":
        return _apply_plugin(pid, root, backend)
    return None


def _prune_family(family_id: str | None, pid: str, root: Path, backend: HindsightBackendConfig) -> Any:
    if family_id == "managed-hooks":
        return _prune_hooks(pid, root)
    if family_id == "managed-mcp":
        return _prune_mcp(pid, root, backend)
    if family_id == "plugin-entry":
        return _prune_plugin(pid, root)
    return None


def _combine_summary(
    fam_result: Any,
    art_result: RecipeResult | None,
    operation: str,
    absent_role: str,
) -> dict[str, Any]:
    """Fold the provider-family result and the artifact-recipe result into one entry.

    Either side may be absent (a provider with no supported family, or no
    Hindsight-owned artifacts). When both are absent the provider had nothing to
    do and reports ``absent_role``.
    """
    if fam_result is None and art_result is None:
        return {"success": True, "state": "ABSENT", "role": absent_role}

    fam_ok = fam_result is None or bool(getattr(fam_result, "ok", False))
    art_ok = art_result is None or art_result.success
    ok = fam_ok and art_ok

    if operation == "install" and ok:
        state = "VERIFIED"
    elif ok:
        state = "ABSENT"
    else:
        state = "FAILED"

    entry: dict[str, Any] = {"success": ok, "state": state, "role": operation}
    if not ok:
        fam_err = None
        if fam_result is not None and not fam_ok:
            fam_err = getattr(fam_result, "error_code", None) or getattr(fam_result, "action_needed", None)
        art_err = art_result.status if (art_result is not None and not art_ok) else None
        entry["error"] = fam_err or art_err or "unknown failure"
    return entry


# ---------------------------------------------------------------------------
# Top-level orchestration — reconcile_hindsight / build_hindsight_status_report
# ---------------------------------------------------------------------------

def discover_provider_ids(project_root: Path | str) -> tuple[list[str], list[str]]:
    """Return (all_provider_ids, enabled_provider_ids).

    Provider discovery and enablement stay behind the provider public API so
    Memory never reproduces provider registry/config mechanics.
    """
    root = Path(project_root)
    all_ids = sorted(_provider_capability_map())
    status = list_providers(root)
    enabled_ids = sorted(
        str(provider["provider_id"])
        for provider in status.get("providers", [])
        if provider.get("enabled") is True
    )
    return all_ids, enabled_ids


def reconcile_hindsight(
    project_root: Path | str,
    provider_ids: list[str] | None = None,
    *,
    all_provider_ids: list[str] | None = None,
    active: bool = True,
) -> dict[str, Any]:
    """Apply or tear down Hindsight integration across providers.

    Uses family-preference orchestration: for each provider, resolves the first
    supported family in fixed order (managed-hooks > managed-mcp > plugin-entry)
    and calls the corresponding providers_api function.

    Returns ``{"action": action, "providers": {id: {"success", "state", "role", ["error"]}}}``.
    """
    root = Path(project_root)
    ids = list(provider_ids or [])
    all_ids = list(all_provider_ids or ids)
    backend = build_hindsight_backend(root) if active else None
    capability_map = _provider_capability_map()

    providers: dict[str, Any] = {}

    if backend is None:
        # Off (disabled) or unconfigured: uninstall from all.
        action = "torn-down"
        placeholder = HindsightBackendConfig(base_url="http://removed.invalid")
        for pid in all_ids:
            family_id = _resolve_family(pid, capability_map)
            fam_result = _prune_family(family_id, pid, root, placeholder)
            art_result = _run_artifact_recipe(pid, placeholder, "prune")
            providers[pid] = _combine_summary(fam_result, art_result, "uninstall", "uninstalled")
    else:
        action = "applied"
        enabled_set = set(ids)

        # Apply to enabled providers.
        for pid in ids:
            family_id = _resolve_family(pid, capability_map)
            fam_result = _apply_family(family_id, pid, root, backend)
            art_result = _run_artifact_recipe(pid, backend, "apply")
            providers[pid] = _combine_summary(fam_result, art_result, "install", "guidance-only")

        # Prune stale providers (no longer enabled).
        stale = [pid for pid in all_ids if pid not in enabled_set]
        for pid in stale:
            family_id = _resolve_family(pid, capability_map)
            fam_result = _prune_family(family_id, pid, root, backend)
            art_result = _run_artifact_recipe(pid, backend, "prune")
            providers[pid] = _combine_summary(fam_result, art_result, "prune", "pruned-stale")

    return {
        "action": action,
        "providers": providers,
    }


def build_hindsight_status_report(project_root: Path | str) -> dict[str, Any]:
    """Build per-provider Hindsight status report via family queries.

    Returns ``{"configured": True/False, "providers": {id: status}}``.

    For each provider with a backend, resolves the first supported family and
    queries its status via providers_api. Maps the result to the common shape.
    """
    root = Path(project_root)
    backend = build_hindsight_backend(root)

    if backend is None:
        return {"configured": False, "providers": {}}

    providers: dict[str, Any] = {}
    capability_map = _provider_capability_map()
    for provider_id in sorted(capability_map):
        family_id = _resolve_family(provider_id, capability_map)

        if family_id == "managed-hooks":
            result = _status_hooks(provider_id, root)
            status = _map_hook_status(result)
        elif family_id == "managed-mcp":
            result = _status_mcp(provider_id, root, backend)
            status = _map_mcp_status(result)
        else:
            # No supported family — guidance only.
            status = {"status": "not_registered", "action_needed": None}

        providers[provider_id] = status

    return {"configured": True, "providers": providers}


def _map_hook_status(result: ManagedHooksResult) -> dict[str, Any]:
    """Map ManagedHooksResult to common status shape."""
    if result.ok:
        return {"status": "active", "action_needed": result.action_needed}
    return {"status": "inactive", "action_needed": result.action_needed or result.error_code}


def _map_mcp_status(result: ManagedMcpResult) -> dict[str, Any]:
    """Map ManagedMcpResult to common status shape."""
    if result.ok:
        return {"status": "active", "action_needed": result.action_needed}
    return {"status": "inactive", "action_needed": result.action_needed or result.error_code}
