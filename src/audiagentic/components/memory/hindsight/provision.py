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
    build_hindsight_managed_entry,
    hindsight_ownership_scope,
)
from audiagentic.components.providers.providers_api import (
    ManagedHooksRequest,
    ManagedHooksResult,
    ManagedMcpRequest,
    ManagedMcpResult,
    describe_provider,
    list_provider_descriptors,
    list_providers,
    manage_hook_entries,
    manage_mcp_entries,
)

# Import provider-layer recipe steps so their types are registered before
# _run_recipe loads recipes (managed-mcp, managed-hooks, managed-plugin).
from audiagentic.components.providers.services.capabilities import recipe_steps  # noqa: F401
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
    "aider": "hindsight-aider.yaml",
    "codex": "hindsight-codex.yaml",
    "copilot": "hindsight-copilot.yaml",
    "openhands": "hindsight-openhands.yaml",
    "pi": "hindsight-pi.yaml",
    "roo": "hindsight-roo.yaml",
}


# ---------------------------------------------------------------------------
# Hindsight-owned artifact recipes — declarative, run through the generic engine
# ---------------------------------------------------------------------------


def _artifact_recipe_path(provider_id: str) -> Path | None:
    """Return the Hindsight-owned artifact recipe for a provider, or None."""
    name = _ARTIFACT_RECIPES.get(provider_id)
    return _RECIPE_DIR / name if name else None


# ---------------------------------------------------------------------------
# Family resolution — fixed preference order, no provider-id branches
# ---------------------------------------------------------------------------


def _hindsight_families() -> list[str]:
    """Return the Hindsight family preference order.

    managed-hooks beats all (Cline, Codex).
    plugin-entry beats managed-mcp (Claude, OpenCode — full integration wins over raw MCP).
    """
    return ["managed-hooks", "plugin-entry", "managed-mcp"]


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
# Recipe resolution — generic family recipes + provider compound recipes
# ---------------------------------------------------------------------------

_REMOTE_CAPABILITY = "remote"
_GENERIC_MCP = "hindsight-managed-mcp.yaml"
_GENERIC_MCP_STDIO = "hindsight-managed-mcp-stdio.yaml"
_PLUGIN_RECIPE = "hindsight-plugin.yaml"


def _mcp_surface(pid: str, root: Path) -> dict[str, Any]:
    """Return the MCP config surface entry for a provider, or empty dict."""
    for s in describe_provider(root, pid).get("config_surfaces", []):
        if s.get("kind") == "mcp":
            return s
    return {}


def _resolve_recipe(
    pid: str,
    root: Path,
    backend: HindsightBackendConfig,
) -> tuple[Path | None, dict[str, str]]:
    """Resolve the recipe path and params for a provider.

    Returns (recipe_path, params) or (None, {}) when no recipe applies.
    Compound providers (codex/pi) get their full recipe; others get generic
    family recipes chosen by _resolve_family + mcp surface capabilities.
    """
    scope = hindsight_ownership_scope(backend)
    auth = backend.headers().get("Authorization", "")
    base_params: dict[str, str] = {
        "PROVIDER": pid,
        "OWNERSHIP_SCOPE": scope,
        "AUTH": auth,
        "MCP_URL": backend.mcp_url,
        "BANK_ID": backend.bank_id or "",
    }

    if pid in _ARTIFACT_RECIPES:
        # Compound: full provider-specific recipe (codex, pi)
        params = {
            "URL": backend.base_url,
            "TOKEN": backend.api_key or "",
            **base_params,
        }
        if pid == "codex":
            params["INTERP"] = str(Path(sys.executable))
            params["SCRIPT_DIR"] = str(Path.home() / ".hindsight" / "codex" / "scripts")
        path = _RECIPE_DIR / _ARTIFACT_RECIPES[pid]
        return path, params

    family = _resolve_family(pid)
    if family == "managed-mcp":
        if _REMOTE_CAPABILITY in _mcp_surface(pid, root).get("capabilities", []):
            return _RECIPE_DIR / _GENERIC_MCP, base_params
        return _RECIPE_DIR / _GENERIC_MCP_STDIO, {
            "PROVIDER": pid,
            "OWNERSHIP_SCOPE": scope,
            "BASE_URL": backend.base_url,
            "BANK_ID": backend.bank_id or "",
        }
    if family == "plugin-entry":
        return _RECIPE_DIR / _PLUGIN_RECIPE, base_params
    # No family supported — guidance-only, no recipe
    return None, {}


def _run_recipe(
    pid: str,
    root: Path,
    backend: HindsightBackendConfig,
    mode: str,
) -> tuple[RecipeResult | None, list[dict[str, Any]]]:
    """Run the resolved recipe for a provider in *mode*.

    Returns (recipe_result, managed_results) where managed_results is the list of
    family result mappings stashed by managed-* steps during execution.
    """
    path, params = _resolve_recipe(pid, root, backend)
    if path is None:
        return None, []
    declared = {p.name for p in load_recipe_from_yaml(path).parameters}
    filtered = {k: v for k, v in params.items() if k in declared}
    ctx: dict[str, Any] = {
        "project_root": str(root),
        "managed_results": [],
    }
    result = execute_recipe_mode(
        path,
        filtered,
        mode,
        context=ctx,
    )
    return result, ctx.get("managed_results", [])


# ---------------------------------------------------------------------------
# Family-specific status — used by build_hindsight_status_report
# ---------------------------------------------------------------------------


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


def _status_mcp(
    provider_id: str, project_root: Path, backend: HindsightBackendConfig
) -> ManagedMcpResult:
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


# ---------------------------------------------------------------------------
# Lifecycle hints — restart-required, collision, deprecation (DE03)
# ---------------------------------------------------------------------------


def _mcp_refresh_mode(pid: str, root: Path) -> str | None:
    """Return the MCP config surface refresh_mode for a provider, or None."""
    for s in describe_provider(root, pid).get("config_surfaces", []):
        if s.get("kind") == "mcp":
            return s.get("refresh_mode")
    return None


def _lifecycle_hint(
    pid: str,
    root: Path,
    managed_results: list[dict[str, Any]],
) -> str | None:
    """Produce a lifecycle hint string from the managed family result + descriptor.

    Checks in order:
    1. restart-required — changed but not auto-refreshed
    2. collisions — unmanaged entries detected
    3. action_needed — provider-specific guidance from the family result
    4. deprecation — descriptor-level deprecation flag
    """
    if not managed_results:
        return None
    # Use the last managed result (the primary managed-* step)
    fam = managed_results[-1]
    parts: list[str] = []

    # Restart-required: changed but not auto-refreshed, or descriptor says restart.
    changed = fam.get("changed", False)
    if changed:
        auto = fam.get("auto_refreshed")
        mode = _mcp_refresh_mode(pid, root)
        if not auto or mode == "restart-required":
            parts.append("restart the harness for the change to take effect")

    # Collisions: surface even on ok (do not drop as current status mapping does).
    if fam.get("collision_ids"):
        parts.append(f"unmanaged entries collide: {', '.join(fam['collision_ids'])}")

    # Action needed from family result.
    if fam.get("action_needed"):
        parts.append(fam["action_needed"])

    # Deprecation (boolean-only, descriptor-driven).
    from audiagentic.components.providers.descriptors.registry import get_descriptor

    desc = get_descriptor(pid)
    if desc is not None and getattr(desc, "deprecated", False):
        parts.append("Provider is deprecated — check annotations for migration guidance.")

    return ", ".join(parts) or None


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
            fam_err = getattr(fam_result, "error_code", None) or getattr(
                fam_result, "action_needed", None
            )
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
        if provider.get("enabled")
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

    providers: dict[str, Any] = {}

    if backend is None:
        # Off (disabled) or unconfigured: uninstall from all.
        action = "torn-down"
        placeholder = HindsightBackendConfig(base_url="http://removed.invalid")
        for pid in all_ids:
            result, managed_results = _run_recipe(pid, root, placeholder, "prune")
            entry = _combine_summary(None, result, "uninstall", "uninstalled")
            hint = _lifecycle_hint(pid, root, managed_results)
            if hint:
                entry["action_needed"] = hint
            providers[pid] = entry
    else:
        action = "applied"
        enabled_set = set(ids)

        # Apply to enabled providers.
        for pid in ids:
            result, managed_results = _run_recipe(pid, root, backend, "apply")
            entry = _combine_summary(None, result, "install", "guidance-only")
            hint = _lifecycle_hint(pid, root, managed_results)
            if hint:
                entry["action_needed"] = hint
            providers[pid] = entry

        # Prune stale providers (no longer enabled).
        stale = [pid for pid in all_ids if pid not in enabled_set]
        for pid in stale:
            result, managed_results = _run_recipe(pid, root, backend, "prune")
            entry = _combine_summary(None, result, "prune", "pruned-stale")
            hint = _lifecycle_hint(pid, root, managed_results)
            if hint:
                entry["action_needed"] = hint
            providers[pid] = entry

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
            status = _map_mcp_status(result, pid=provider_id, root=root)
        else:
            # No supported family — guidance only.
            status = {"status": "not_registered", "action_needed": None}

        providers[provider_id] = status

    return {"configured": True, "providers": providers}


def _map_hook_status(result: ManagedHooksResult) -> dict[str, Any]:
    """Map ManagedHooksResult to common status shape."""
    hint = getattr(result, "action_needed", None)
    if not result.ok:
        return {"status": "inactive", "action_needed": hint or result.error_code}
    return {"status": "active", "action_needed": hint}


def _map_mcp_status(
    result: ManagedMcpResult, pid: str = "", root: Path | None = None
) -> dict[str, Any]:
    """Map ManagedMcpResult to common status shape with lifecycle hints (DE03)."""
    parts: list[str] = []

    # Restart-required hint.
    if result.changed:
        if not result.auto_refreshed and root is not None:
            mode = _mcp_refresh_mode(pid, root)
            if mode == "restart-required":
                parts.append("restart the harness for the change to take effect")

    # Collision hint — surface even on ok.
    if result.collision_ids:
        parts.append(f"unmanaged entries collide: {', '.join(result.collision_ids)}")

    # Action needed from family result.
    if result.action_needed:
        parts.append(result.action_needed)

    # Deprecation hint.
    if pid:
        from audiagentic.components.providers.descriptors.registry import get_descriptor

        desc = get_descriptor(pid)
        if desc is not None and getattr(desc, "deprecated", False):
            parts.append("Provider is deprecated — check annotations for migration guidance.")

    hint = ", ".join(parts) or None
    if result.ok:
        return {"status": "active", "action_needed": hint}
    return {"status": "inactive", "action_needed": hint or result.error_code}
