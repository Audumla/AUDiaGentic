"""Provider-owned native preflight and guarded apply; requester policy is opaque."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.toolchains.config.managed_config import resolve_managed_config_path

from ...contracts.managed_mcp import ManagedMcpRequest
from ...descriptors.registry import get_descriptor
from .fence import native_mcp_fence
from .managed_mcp_registry import mcp_ownership_registry


def digest(value) -> str:
    if is_dataclass(value):
        value = asdict(value)
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "absent"


def conflict(message: str):
    return AudiaGenticError(code="CON-MCPONB-001", kind="providers", message=message)


def _context(root: Path, provider_id: str):
    if not (root / ".audiagentic/state/providers").resolve().is_relative_to(root.resolve()):
        raise conflict("MCP ownership state escapes the project")
    descriptor = get_descriptor(provider_id)
    spec = descriptor.mcp_config if descriptor else None
    if spec is None or spec.raw_reader is None:
        raise conflict("Target does not support guarded native MCP registration")
    path = resolve_managed_config_path(spec, root).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise conflict("Only project-native MCP targets are supported")
    return spec, path


def _adopt(document: dict, provider_id: str, scope: str, spec, path: Path, entries: tuple) -> dict:
    """Normalize only legacy recorded names whose declared native value matches."""
    data = deepcopy(document)
    old = data["providers"].get(provider_id, {})
    current = spec.reader(path)
    raw = spec.raw_reader(path)
    for item in entries:
        if old.get(item.managed_id) != item.name:
            continue
        from ..capabilities.managed_mcp_family import _desired

        expected = _desired(ManagedMcpRequest("component-mcp", None, (item,)))[item.managed_id][1]
        if current.get(item.name) != expected:
            raise conflict("Legacy native ownership does not match its declaration")
        rows = data["providers"].setdefault(scope, {})
        if item.managed_id in rows:
            raise conflict("Legacy and scoped ownership both claim the same MCP")
        rows[item.managed_id] = old.pop(item.managed_id)
        proof = data.setdefault("proofs", {}).setdefault(
            scope, {"target": str(path), "entries": {}}
        )
        proof["entries"][item.managed_id] = digest(raw[item.name])
    if not old:
        data["providers"].pop(provider_id, None)
    return data


def discover_bindings(root: Path, entries: tuple) -> dict[str, list[str]]:
    """Read proven component exposures, leaving independently scoped owners alone."""
    document = mcp_ownership_registry(root).document()
    known = {item.managed_id: item for item in entries}
    bindings = {mid: [] for mid in known}
    for scope, rows in document["providers"].items():
        pid = scope.split("/")[0]
        if scope not in {pid, f"{pid}/component-mcp"}:
            continue
        spec, path = _context(root, pid)
        current = spec.reader(path)
        for mid, name in rows.items():
            if mid not in known:
                continue
            from ..capabilities.managed_mcp_family import _desired

            desired = _desired(ManagedMcpRequest("component-mcp", None, (known[mid],)))[mid][1]
            if current.get(name) != desired:
                raise conflict("Existing MCP exposure requires ownership reconciliation")
            bindings[mid].append(pid)
    return bindings


def preflight(
    root: Path, provider_id: str, request: ManagedMcpRequest, adopt_entries: tuple = ()
) -> dict:
    from ..capabilities.managed_mcp_family import _desired

    spec, path = _context(root, provider_id)
    registry = mcp_ownership_registry(root)
    document = registry.document()
    scope = f"{provider_id}/{request.ownership_scope}"
    if adopt_entries:
        document = _adopt(document, provider_id, scope, spec, path, adopt_entries)
    owned = document["providers"].get(scope, {})
    desired = _desired(request)
    current = spec.reader(path)
    raw = spec.raw_reader(path)
    proof = document.get("proofs", {}).get(scope, {})
    if proof and proof.get("target") != str(path):
        raise conflict("Native target identity changed; reconcile ownership first")
    affected = (
        set(owned) | set(desired) if request.managed_ids is None else set(request.managed_ids)
    )
    claims = {}
    for other_scope, rows in document["providers"].items():
        other_provider = other_scope.split("/")[0]
        other_desc = get_descriptor(other_provider)
        if not other_desc or not other_desc.mcp_config:
            continue
        if resolve_managed_config_path(other_desc.mcp_config, root).resolve() != path:
            continue
        for mid, name in rows.items():
            if name in claims:
                raise conflict("Multiple ownership claims address the same native entry")
            claims[name] = (other_scope, mid)
    actions = []
    seen = set()
    for mid in sorted(affected):
        previous = owned.get(mid)
        previous_hash = proof.get("entries", {}).get(mid)
        if previous in raw:
            if previous_hash is not None and digest(raw[previous]) != previous_hash:
                raise conflict("A previously owned native entry was edited externally")
            if previous_hash is None:
                proposed = desired.get(mid)
                if proposed is None or current.get(previous) != proposed[1]:
                    raise conflict("Legacy ownership lacks proof for this native mutation")
        if mid not in desired:
            if previous:
                actions.append({"managed_id": mid, "action": "remove"})
            continue
        name, entry = desired[mid]
        transport = "http" if entry.is_remote else "stdio"
        if transport not in spec.transports:
            raise conflict("Native adapter does not support the declared MCP transport")
        if name in seen or (name in current and claims.get(name) != (scope, mid)):
            raise conflict("Native MCP name is foreign, unowned or conflicting")
        seen.add(name)
        if current.get(name) != entry or previous != name:
            actions.append(
                {"managed_id": mid, "action": "configure", "updates_existing": name in current}
            )
    return {
        "revision": digest(
            [revision(path), revision(registry.path), revision(registry.legacy_path)]
        ),
        "changes": actions,
        "restart_required": spec.refresh_mode == "restart-required",
    }


def apply(
    root: Path,
    provider_id: str,
    request: ManagedMcpRequest,
    expected_revision: str,
    adopt_entries: tuple = (),
) -> dict:
    from ..capabilities.managed_mcp_family import manage_mcp_entries

    registry = mcp_ownership_registry(root)
    # One lock fences all native files sharing this ownership authority.
    with native_mcp_fence(root):
        plan = preflight(root, provider_id, request, adopt_entries)
        if plan["revision"] != expected_revision:
            raise conflict("Native configuration or ownership changed after preflight")
        if adopt_entries:
            spec, path = _context(root, provider_id)
            scope = f"{provider_id}/{request.ownership_scope}"
            before = registry.document()
            normalized = _adopt(before, provider_id, scope, spec, path, adopt_entries)
            if normalized != before:
                registry.save(normalized["providers"])
                registry.save_proofs(scope, normalized["proofs"][scope])
        result = manage_mcp_entries(root, provider_id, mode="apply", request=request)
        if result.ok:
            spec, path = _context(root, provider_id)
            scope = f"{provider_id}/{request.ownership_scope}"
            rows = registry.load().get(scope, {})
            raw = spec.raw_reader(path)
            registry.save_proofs(
                scope,
                {
                    "target": str(path),
                    "entries": {
                        mid: digest(raw[name]) for mid, name in rows.items() if name in raw
                    },
                },
            )
        outcome = {**result.to_mapping(), "restart_required": plan["restart_required"]}
        if result.changed and plan["restart_required"]:
            outcome["action_needed"] = f"Restart {provider_id} to load native MCP configuration."
        return outcome
