"""Hindsight provisioning entrypoint — family-preference orchestration over providers_api.

Memory orchestrates by querying each provider's automation capabilities and selecting
the first supported family in fixed order (managed-hooks > managed-mcp > plugin-entry).
No matrix, no factory dispatch, no recipe registry. Calls only providers_api family
functions and writes Hindsight-owned artifacts directly.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.codex_pi_desired import (
    CodexHindsightDesired,
    HookCommand,
)
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
from audiagentic.foundation.io import atomic_write_text
from audiagentic.foundation.logging.redaction import redact_text

_HINDSIGHT_OWNERSHIP = "hindsight"
_RAW_BASE = "https://raw.githubusercontent.com/vectorize-io/hindsight/main/hindsight-integrations/codex"

_SCRIPT_FILES = (
    "scripts/session_start.py",
    "scripts/recall.py",
    "scripts/retain.py",
    "scripts/lib/__init__.py",
    "scripts/lib/bank.py",
    "scripts/lib/client.py",
    "scripts/lib/config.py",
    "scripts/lib/content.py",
    "scripts/lib/daemon.py",
    "scripts/lib/llm.py",
    "scripts/lib/state.py",
)

_HOOK_EVENTS = (
    ("session_start.py", "SessionStart", 5),
    ("recall.py", "UserPromptSubmit", 12),
    ("retain.py", "Stop", 30),
)


def _quote_command_part(value: Path | str) -> str:
    text = str(value)
    return '"' + text.replace('"', '\\"') + '"'


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

def _build_codex_desired(backend: HindsightBackendConfig) -> CodexHindsightDesired:
    """Build CodexHindsightDesired from backend config."""
    import sys
    interpreter_path = Path(sys.executable)
    script_dir = Path.home() / ".hindsight" / "codex" / "scripts"
    hook_commands = tuple(
        HookCommand(
            event=event,
            command=f"{_quote_command_part(interpreter_path)} {_quote_command_part(script_dir / script_name)}",
            timeout=timeout,
        )
        for script_name, event, timeout in _HOOK_EVENTS
    )
    return CodexHindsightDesired(
        base_url=backend.base_url,
        bank_id=backend.bank_id or "codex",
        api_key=backend.api_key,
        interpreter_path=interpreter_path,
        script_dir=script_dir,
        hook_commands=hook_commands,
    )


def _build_codex_managed_entries(desired: CodexHindsightDesired) -> tuple[ManagedHooksEntry, ...]:
    """Convert HookCommand entries to ManagedHooksEntry for providers_api."""
    return tuple(
        ManagedHooksEntry(
            managed_id=f"hindsight/{hc.event.lower()}",
            event=hc.event,
            command=hc.command,
            timeout=hc.timeout,
        )
        for hc in desired.hook_commands
    )


def _write_codex_user_config(desired: CodexHindsightDesired) -> None:
    """Write ~/.hindsight/codex.json (Hindsight-owned artifact)."""
    import json

    from audiagentic.foundation.steps import WriteFileStep

    config: dict[str, Any] = {
        "hindsightApiUrl": desired.base_url,
        "bankId": desired.bank_id,
    }
    if desired.api_key:
        config["hindsightApiToken"] = desired.api_key

    step = WriteFileStep(
        id="codex-user-config-write",
        path=str(Path.home() / ".hindsight" / "codex.json"),
        content=json.dumps(config, indent=2) + "\n",
        create_parents=True,
        recipe_id="hindsight-codex",
    )
    step.run({})


def _download_codex_scripts() -> None:
    """Download Codex hook scripts to ~/.hindsight/codex/scripts/ (Hindsight-owned)."""
    for rel in _SCRIPT_FILES:
        dest = Path.home() / ".hindsight" / "codex" / rel
        with urllib.request.urlopen(f"{_RAW_BASE}/{rel}", timeout=30) as response:  # noqa: S310
            atomic_write_text(dest, response.read().decode("utf-8"))

    settings = Path.home() / ".hindsight" / "codex" / "settings.json"
    if not settings.exists():
        with urllib.request.urlopen(f"{_RAW_BASE}/settings.json", timeout=30) as response:  # noqa: S310
            atomic_write_text(settings, response.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Family-specific apply/prune/status — typed, no Any result
# ---------------------------------------------------------------------------

def _apply_hooks(provider_id: str, project_root: Path, backend: HindsightBackendConfig) -> ManagedHooksResult:
    """Apply managed-hooks integration for a provider."""
    desired = _build_codex_desired(backend)
    managed_entries = _build_codex_managed_entries(desired)

    try:
        _download_codex_scripts()
    except Exception as exc:
        return ManagedHooksResult(
            ok=False,
            error_code="CON-PHKS-002",
            action_needed=redact_text(str(exc)),
        )

    try:
        _write_codex_user_config(desired)
    except Exception as exc:
        return ManagedHooksResult(
            ok=False,
            error_code="CON-PHKS-002",
            action_needed=redact_text(str(exc)),
        )

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
    """Apply managed-mcp integration for a provider."""
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
    """Prune managed-mcp integration for a provider."""
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
# Result mapping — family results to common summary shape (no universal type)
# ---------------------------------------------------------------------------

def _map_result_to_summary(result: Any, operation: str) -> dict[str, Any]:
    """Map a family-specific result to the common summary entry.

    Each family result has ok, action_needed, error_code. We map these locally
    without creating a universal result type.
    """
    ok = getattr(result, "ok", False)
    error_code = getattr(result, "error_code", None)
    action_needed = getattr(result, "action_needed", None)

    if operation == "install" and ok:
        state = "VERIFIED"
    elif ok:
        state = "ABSENT"
    else:
        state = "FAILED"

    entry: dict[str, Any] = {
        "success": ok,
        "state": state,
        "role": operation,
    }
    if not ok:
        entry["error"] = error_code or action_needed or "unknown failure"
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
            if family_id == "managed-hooks":
                result = _prune_hooks(pid, root)
            elif family_id == "managed-mcp":
                result = _prune_mcp(pid, root, placeholder)
            else:
                result = None

            if result is not None:
                providers[pid] = _map_result_to_summary(result, "uninstall")
            else:
                providers[pid] = {"success": True, "state": "ABSENT", "role": "uninstalled"}
    else:
        action = "applied"
        enabled_set = set(ids)

        # Apply to enabled providers.
        for pid in ids:
            family_id = _resolve_family(pid, capability_map)
            if family_id == "managed-hooks":
                result = _apply_hooks(pid, root, backend)
            elif family_id == "managed-mcp":
                result = _apply_mcp(pid, root, backend)
            elif family_id == "plugin-entry":
                result = _apply_plugin(pid, root, backend)
            else:
                # No supported family — guidance only.
                providers[pid] = {
                    "success": True,
                    "state": "ABSENT",
                    "role": "guidance-only",
                }
                continue

            providers[pid] = _map_result_to_summary(result, "install")

        # Prune stale providers (no longer enabled).
        stale = [pid for pid in all_ids if pid not in enabled_set]
        for pid in stale:
            family_id = _resolve_family(pid, capability_map)
            if family_id == "managed-hooks":
                result = _prune_hooks(pid, root)
            elif family_id == "managed-mcp":
                result = _prune_mcp(pid, root, backend)
            else:
                result = None

            if result is not None:
                providers[pid] = _map_result_to_summary(result, "prune")
            else:
                providers[pid] = {"success": True, "state": "ABSENT", "role": "pruned-stale"}

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
