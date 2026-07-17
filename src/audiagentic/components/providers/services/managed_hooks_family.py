"""Descriptor-backed managed-hooks automation family."""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.contracts.managed_hooks import (
    ManagedHooksMode,
    ManagedHooksRequest,
    ManagedHooksResult,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.components.providers.services.recipe_definitions import FamilyPin
from audiagentic.foundation.toolchains.managed_config import (
    ManagedFragmentRegistry,
    resolve_managed_config_path,
    sync_managed_config,
)

PIN = FamilyPin(
    family_id="managed-hooks",
    payload_contract="provider-managed-hooks-payload/v1",
    result_contract="provider-managed-hooks-result/v1",
    supported_modes=("apply", "prune", "status"),
    ownership_scope_required=True,
)


def _hooks_ownership_registry(project_root: Path) -> ManagedFragmentRegistry:
    return ManagedFragmentRegistry(
        project_root,
        "managed-hooks.json",
        top_level_key="providers",
    )


def manage_hook_entries(
    project_root: Path,
    provider_id: str,
    *,
    mode: ManagedHooksMode,
    request: ManagedHooksRequest,
) -> ManagedHooksResult:
    """Reconcile typed caller-owned hook entries using descriptor capabilities."""
    descriptor = get_descriptor(provider_id)
    if (
        descriptor is None
        or descriptor.hooks_config is None
        or descriptor.automation_capability("managed-hooks") is None
    ):
        return ManagedHooksResult(
            ok=False, supported=False, provider_id=provider_id, error_code="RES-PHKS-001"
        )
    if mode not in PIN.supported_modes:
        return ManagedHooksResult(
            ok=False, provider_id=provider_id, error_code="CON-PREC-002"
        )

    spec = descriptor.hooks_config
    config_path = resolve_managed_config_path(spec, project_root)
    registry = _hooks_ownership_registry(project_root)
    scope_key = f"{provider_id}/{request.ownership_scope}"

    if mode == "status":
        try:
            spec.reader(config_path)
        except Exception:
            return ManagedHooksResult(
                ok=False, provider_id=provider_id, error_code="CON-PHKS-001"
            )
        owned_registry = registry.load().get(scope_key, {})
        managed_ids = tuple(sorted(owned_registry))
        return ManagedHooksResult(
            ok=True,
            provider_id=provider_id,
            managed_ids=managed_ids,
        )

    # Build desired entries dict: {managed_id: (name, value)}
    if mode == "prune":
        desired_entries = {}
    else:  # apply
        desired_entries = {
            entry.managed_id: (entry.command, {"event": entry.event, "timeout": entry.timeout})
            for entry in request.entries
        }

    result = sync_managed_config(
        spec,
        project_root,
        scope_key,
        desired_entries,
        registry=registry,
    )

    before = registry.load().get(scope_key, {})
    after = registry.load().get(scope_key, {})
    changed = bool(result.updated) or bool(result.removed)
    return ManagedHooksResult(
        ok=True,
        provider_id=provider_id,
        changed=changed,
        managed_ids=tuple(sorted(after)),
        removed_ids=tuple(sorted(set(before) - set(after))),
        collision_ids=tuple(sorted({
            str(row.get("managed_id") or row.get("managed-id") or "")
            for row in (result.collisions or [])
        } - {""})),
    )


__all__ = ["manage_hook_entries"]
