"""Provider-owned native preflight and guarded apply; requester policy is opaque."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.toolchains.config.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.config.fragments import FragmentStore, reconcile_fragments
from audiagentic.foundation.toolchains.config.managed_config import (
    reload_managed_config,
    resolve_managed_config_path,
)

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


def _authority_hash(document: dict) -> str:
    """Only owners and raw proofs grant authority; prepared metadata never does."""
    return digest([document["providers"], document.get("proofs", {})])


def _prepared_state(root: Path, registry, document: dict) -> tuple[dict, str | None]:
    """Read-only interpretation of a prepared native transition.

    An exact pre-image means the native mutation has not happened. An exact
    post-image allows *virtual* ownership solely for preflight, never a write.
    A different native byte sequence is always treated as foreign evidence.
    """
    prepared = document.get("prepared", {})
    if not prepared:
        return document, None
    scope, record = next(iter(prepared.items()))
    spec, path = _context(root, record["provider_id"])
    if scope != record["scope"] or str(path) != record["target"]:
        raise conflict("Prepared MCP target identity changed")
    if _authority_hash(document) != record["before_hash"]:
        raise conflict("Prepared MCP ownership authority changed")
    actual_hash = revision(path)
    if actual_hash == record["pre_hash"]:
        return document, "pre"
    if actual_hash != record["post_hash"]:
        raise conflict("Native MCP file differs from both prepared recovery images")
    post = deepcopy(document)
    post["providers"] = deepcopy(record["owners_after"])
    post["proofs"] = deepcopy(record["proofs_after"])
    # A full-file hash alone is not permission to claim arbitrary entry names.
    raw = spec.raw_reader(path)
    for mid, name in post["providers"].get(scope, {}).items():
        expected = post["proofs"].get(scope, {}).get("entries", {}).get(mid)
        if name not in raw or expected is None or digest(raw[name]) != expected:
            raise conflict("Prepared MCP raw-entry proof does not match native state")
    return post, "post"


def _recover_prepared(root: Path, registry) -> dict | None:
    """Apply-only recovery, called under the native fence.

    The single v2 commit includes owners, proofs and removal of prepared.
    A prepared pre-image only clears the record; it never claims an entry.
    """
    original = registry.document()
    if not original.get("prepared"):
        return None
    scope, record = next(iter(original["prepared"].items()))
    _, state = _prepared_state(root, registry, original)
    updated = deepcopy(original)
    if state == "post":
        updated["providers"] = deepcopy(record["owners_after"])
        updated["proofs"] = deepcopy(record["proofs_after"])
    updated.pop("prepared", None)
    updated["contract-version"] = "v2"
    registry.write_document(updated)
    if state == "post":
        return {
            "scope": scope,
            "created": record["pre_hash"] == "absent",
            "removed": sorted(
                set(original["providers"].get(scope, {})) - set(updated["providers"].get(scope, {}))
            ),
        }
    return None


def _stage(
    spec, path: Path, scope: str, desired: dict, normalized: dict, managed_ids, target_scopes
) -> tuple[bytes | None, dict, dict, object]:
    """Use native adapters and the neutral fragment engine on a private copy."""
    owners = deepcopy(normalized["providers"])
    with TemporaryDirectory(prefix=".ag-mcp-stage-", dir=path.parent) as directory:
        staged = Path(directory) / path.name
        if path.exists():
            shutil.copy2(path, staged)

        def load_owners():
            return deepcopy(owners)

        def save_owners(value):
            owners.clear()
            owners.update(deepcopy(value))

        result = reconcile_fragments(
            FragmentStore(read=spec.reader, write=spec.writer, remove=spec.remover),
            staged,
            scope,
            desired,
            registry_load=load_owners,
            registry_save=save_owners,
            managed_ids=set(managed_ids) if managed_ids is not None else None,
            target_scopes=target_scopes,
        )
        if not result.ok:
            raise conflict("Staged native MCP reconciliation encountered foreign ownership")
        content = staged.read_bytes() if staged.exists() else None
        proofs = deepcopy(normalized.get("proofs", {}))
        raw = spec.raw_reader(staged)
        rows = owners.get(scope, {})
        if any(name not in raw for name in rows.values()):
            raise conflict("Staged native MCP entry is absent")
        proofs[scope] = {
            "target": str(path),
            "entries": {mid: digest(raw[name]) for mid, name in rows.items()},
        }
        # Copy the staged bytes out; the private staging directory is removed.
        return content, owners, proofs, result


def _atomic_native_replace(path: Path, content: bytes) -> None:
    """Atomic publication, staged in the same native directory/filesystem."""
    with TemporaryDirectory(prefix=".ag-mcp-publish-", dir=path.parent) as directory:
        staged = Path(directory) / path.name
        with staged.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(staged, stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600)
        os.replace(staged, path)
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)


def preflight(
    root: Path, provider_id: str, request: ManagedMcpRequest, adopt_entries: tuple = ()
) -> dict:
    from ..capabilities.managed_mcp_family import _desired

    spec, path = _context(root, provider_id)
    registry = mcp_ownership_registry(root)
    original_document = registry.document()
    document, prepared_state = _prepared_state(root, registry, original_document)
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
    for mid, name in owned.items():
        if mid not in affected:
            expected = proof.get("entries", {}).get(mid)
            if name not in raw or expected is None or digest(raw[name]) != expected:
                raise conflict(
                    "Untouched owned MCP evidence changed; reconcile before a subset update"
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
    # Expose work already published before a crash as recovery work, not
    # unattempted/no-op changes in the Project operation receipt.
    if prepared_state == "post" and scope in original_document.get("prepared", {}):
        before_rows = original_document["providers"].get(scope, {})
        after_rows = document["providers"].get(scope, {})
        before_hashes = original_document.get("proofs", {}).get(scope, {}).get("entries", {})
        after_hashes = document.get("proofs", {}).get(scope, {}).get("entries", {})
        for mid in sorted(set(before_rows) | set(after_rows)):
            if mid not in after_rows:
                recovered_action = {"managed_id": mid, "action": "remove"}
            elif before_rows.get(mid) != after_rows[mid] or before_hashes.get(
                mid
            ) != after_hashes.get(mid):
                recovered_action = {
                    "managed_id": mid,
                    "action": "configure",
                    "updates_existing": mid in before_rows,
                }
            else:
                continue
            if not any(change["managed_id"] == mid for change in actions):
                actions.append(recovered_action)
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
    """Publish a staged native file and commit ownership/proofs atomically.

    All native and registry writers cooperate on one provider fence. No reload
    or lifecycle callback runs while that fence is held.
    """
    from ..capabilities.managed_mcp_family import _desired

    registry = mcp_ownership_registry(root)
    changed = False
    native_created = False
    with native_mcp_fence(root):
        plan = preflight(root, provider_id, request, adopt_entries)
        if plan["revision"] != expected_revision:
            raise conflict("Native configuration or ownership changed after preflight")

        # May commit a proven post-image or discard a proven pre-image.
        # Read-only preflight intentionally never performs this transition.
        recovered = _recover_prepared(root, registry)
        spec, path = _context(root, provider_id)
        scope = f"{provider_id}/{request.ownership_scope}"
        original = registry.document()
        normalized = (
            _adopt(original, provider_id, scope, spec, path, adopt_entries)
            if adopt_entries
            else deepcopy(original)
        )
        owned_before = dict(normalized["providers"].get(scope, {}))
        desired = _desired(request)
        pre_image = revision(path)
        # Retest after recovery/adoption, before staging anything.
        current_plan = preflight(root, provider_id, request, adopt_entries)
        path.parent.mkdir(parents=True, exist_ok=True)
        target_scopes = {scope}
        for other_scope in normalized["providers"]:
            other_provider = other_scope.split("/")[0]
            try:
                _, other_path = _context(root, other_provider)
            except AudiaGenticError:
                continue
            if other_path == path:
                target_scopes.add(other_scope)
        content, owners_after, proofs_after, staged_result = _stage(
            spec, path, scope, desired, normalized, request.managed_ids, target_scopes
        )
        post_image = hashlib.sha256(content).hexdigest() if content is not None else "absent"
        changed = pre_image != post_image
        native_created = pre_image == "absent" and changed
        final = deepcopy(original)
        final["contract-version"] = "v2"
        final["providers"] = owners_after
        final["proofs"] = proofs_after

        if changed:
            if content is None:
                raise conflict("Native staging unexpectedly removed the configuration file")
            prepared = {
                "target": str(path),
                "scope": scope,
                "provider_id": provider_id,
                "pre_hash": pre_image,
                "post_hash": post_image,
                "before_hash": _authority_hash(original),
                "owners_after": owners_after,
                "proofs_after": proofs_after,
            }
            transition = deepcopy(original)
            transition["contract-version"] = "v2"
            transition["prepared"] = {scope: prepared}
            registry.write_document(transition)
            # External, non-cooperating edits are fenced by a final byte CAS.
            if revision(path) != pre_image:
                raise conflict("Native MCP file changed immediately before publication")
            _atomic_native_replace(path, content)
            # Includes ownership, proofs and prepared removal in ONE v2 update.
            registry.write_document(final)
        else:
            registry.write_document(final)

        owned_after = owners_after.get(scope, {})
        recovered_here = recovered is not None and recovered["scope"] == scope
        removed_ids = sorted(
            (set(owned_before) - set(owned_after))
            | (set(recovered["removed"]) if recovered_here else set())
        )
        result = {
            "ok": True,
            "supported": True,
            "provider_id": provider_id,
            "changed": changed or recovered_here,
            "managed_ids": sorted(owned_after),
            "removed_ids": removed_ids,
            "collision_ids": [],
            "auto_refreshed": not changed,
            "restart_required": current_plan["restart_required"],
        }

    # No arbitrary lifecycle callbacks or native reloads under the fence.
    if native_created or (recovered_here and recovered["created"]):
        ArtifactRegistry(root).register(
            f"managed-config/{scope}/{spec.format}", files=[path.relative_to(root)]
        )
    if changed:
        refresh = reload_managed_config(spec, root, display_name=scope)
        result["auto_refreshed"] = bool(refresh.get("auto_refreshed", False))
        if current_plan["restart_required"]:
            result["action_needed"] = f"Restart {provider_id} to load native MCP configuration."
    return result
