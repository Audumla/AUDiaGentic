"""Project-owned explicit native MCP selection and recoverable installation."""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path

from jsonschema import Draft202012Validator

from audiagentic.components.providers import providers_api
from audiagentic.foundation.components.loader import (
    read_component_metadata,
    register_all_components,
)
from audiagentic.foundation.components.registry import is_enabled, is_installed
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json, load_yaml_file, save_yaml_file
from audiagentic.foundation.mcp.component_builder import (
    entry_from_external_declaration,
    entry_from_mcp_declaration,
)
from audiagentic.foundation.paths.names import get_active_profile
from audiagentic.foundation.system.advisory_lock import AdvisoryLock

from . import requirements
from .catalog import catalog, error

_installing = ContextVar("project_mcp_installing", default=False)


def _config_path(root: Path) -> Path:
    return root / ".audiagentic/config/project.yaml"


def _operations(root: Path) -> Path:
    return root / ".audiagentic/state/mcp-onboarding/operations"


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _config(root: Path) -> dict:
    package = Path(__file__).resolve().parents[3]
    path = _config_path(root)
    data = (
        load_yaml_file(path)
        if path.exists()
        else load_yaml_file(package / "config/components/project/config/project.yaml")
    )
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "contracts/project-config.schema.json").read_text(
            encoding="utf8"
        )
    )
    if list(Draft202012Validator(schema).iter_errors(data)):
        raise error("Project configuration is invalid; use the owning project schema")
    return data


def _declarations(root: Path):
    owners = {d.component_id: d for d in read_component_metadata(root)}
    result = {}
    for owner in owners.values():
        for d in (*owner.mcp_servers, *owner.external_mcp_servers):
            if "providers" not in d.propagate:
                continue
            entry = (
                entry_from_mcp_declaration(d, root)
                if hasattr(d, "module")
                else entry_from_external_declaration(d)
            )
            result[d.name] = (
                owner,
                d,
                providers_api.ManagedMcpEntry(
                    managed_id=d.managed_id or d.name,
                    name=d.name,
                    command=entry.command or None,
                    args=entry.args,
                    env=tuple(sorted(entry.env.items())),
                    url=entry.url,
                    headers=tuple(sorted(entry.headers.items())),
                    transport=entry.transport,
                ),
            )
    return owners, result


def _requests(root, bindings, declarations, include_mcp=None):
    targets = {}
    for mid, ids in bindings.items():
        if mid not in declarations:
            raise error("Selection references an unavailable canonical MCP", mcp_id=mid)
        owner, _, entry = declarations[mid]
        for pid in ids:
            targets.setdefault(pid, [])
            if providers_api.is_native_mcp_target_enabled(root, pid) and (
                mid == include_mcp
                or owner.core
                or (is_installed(owner.component_id, root) and is_enabled(owner.component_id, root))
            ):
                targets[pid].append(entry)
    return {
        pid: providers_api.ManagedMcpRequest("component-mcp", None, tuple(entries))
        for pid, entries in sorted(targets.items())
    }


def _write_operation(root: Path, record: dict) -> None:
    atomic_write_json(_operations(root) / f"{record['operation_id']}.json", record)
    completed = sorted(
        (
            p
            for p in _operations(root).glob("*.json")
            if _read_operation(p).get("phase") == "completed"
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in completed[100:]:
        path.unlink()


def _read_operation(path: Path) -> dict:
    try:
        record = json.loads(path.read_text(encoding="utf8"))
        if not isinstance(record, dict) or not isinstance(record.get("phase"), str):
            raise ValueError("Invalid operation")
        return record
    except (OSError, ValueError):
        # Preserve damaged evidence without blocking unrelated new installations.
        return {
            "operation_id": path.stem,
            "phase": "needs_reconciliation",
            "ok": False,
            "error_code": "VAL-MCPONB-001",
            "action_needed": "Inspect the damaged operation record; its original file was preserved.",
        }


def status(root: Path, operation_id: str | None = None) -> dict:
    records = sorted(
        _operations(root).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if operation_id is not None:
        records = [p for p in records if p.stem == operation_id]
        if not records:
            raise AudiaGenticError(
                code="RES-MCPONB-001", kind="project", message="Installation operation not found"
            )
    for path in records:
        record = _read_operation(path)
        if operation_id or record["phase"] != "completed":
            return {
                key: value for key, value in record.items() if key not in {"fingerprint", "profile"}
            }
    return {"has_unresolved_operation": False}


def install(
    root: Path,
    *,
    mcp_id: str,
    harness_ids,
    dry_run=False,
    config_file=None,
    non_interactive=True,
    resume_fingerprint: str | None = None,
) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise error("Project path must be an existing directory")
    if not _config_path(root).resolve().is_relative_to(root) or not _operations(
        root
    ).resolve().is_relative_to(root):
        raise error("Project-owned configuration and recovery state must remain inside the project")
    if (
        not isinstance(harness_ids, (list, tuple))
        or not harness_ids
        or any(not isinstance(pid, str) or not pid for pid in harness_ids)
    ):
        raise error("Explicit nonempty harness IDs are required")
    selected = list(dict.fromkeys(harness_ids))
    meta = catalog(root, mcp_id)
    if not meta["provider_eligible"]:
        raise error("This MCP is internal and cannot be exposed to native clients")
    eligible = {
        t.provider_id
        for t in providers_api.list_harness_mcp_targets()
        if t.supported and t.project_scoped
    }
    if set(selected) - eligible:
        raise error("One or more targets do not support project-native MCP registration")
    owners, declarations = _declarations(root)
    owner, declaration, _ = declarations[mcp_id]
    import shutil

    if any(shutil.which(tool) is None for tool in getattr(declaration, "requires", ())):
        raise error("An explicitly declared external MCP prerequisite is unavailable")
    resolved = requirements.resolve(
        root, owner, config_file, interactive=not non_interactive and sys.stdin.isatty()
    )
    register_all_components()
    before = _config(root)
    config_revision = _hash(before)
    all_entries = tuple(row[2] for row in declarations.values())
    if "mcp-onboarding" in before:
        bindings = dict(before["mcp-onboarding"]["bindings"])
    else:
        discovered = providers_api.discover_component_mcp_bindings(root, all_entries)
        bindings = {mid: discovered.get(row[2].managed_id, []) for mid, row in declarations.items()}
    previous = bindings.get(mcp_id, [])
    bindings[mcp_id] = selected
    requests = _requests(root, bindings, declarations, include_mcp=mcp_id)
    for pid in previous:
        requests.setdefault(pid, providers_api.ManagedMcpRequest("component-mcp", None, ()))
    for pid in providers_api.list_component_mcp_targets(root):
        requests.setdefault(pid, providers_api.ManagedMcpRequest("component-mcp", None, ()))
    plans = {
        pid: providers_api.preflight_managed_mcp(
            root, pid, request=request, adopt_entries=all_entries
        )
        for pid, request in requests.items()
    }
    planned = [
        {"harness_id": pid, "managed_id": change["managed_id"], "action": change["action"]}
        for pid, plan in plans.items()
        for change in plan["changes"]
    ]
    result = {
        "mcp_id": mcp_id,
        "desired_harness_ids": selected,
        "dry_run": dry_run,
        "ok": True,
        "changed": False,
        "targets": [],
    }
    if dry_run:
        return {**result, "planned_changes": planned}

    # Run lock spans the install, intent lock never spans synchronous callbacks.
    with AdvisoryLock(_operations(root) / ".run.lock"):
        with AdvisoryLock(root / ".audiagentic/state/mcp-onboarding/intent.lock"):
            if _hash(_config(root)) != config_revision:
                raise error("Project selection changed after preflight; retry preflight")
            requirements.validate_current(root, owner.component_id, resolved)
            for pid, request in requests.items():
                fresh = providers_api.preflight_managed_mcp(
                    root, pid, request=request, adopt_entries=all_entries
                )
                if fresh["revision"] != plans[pid]["revision"]:
                    raise error("Native state changed after preflight; retry preflight")
            fingerprint = _hash(
                [
                    mcp_id,
                    selected,
                    get_active_profile(),
                    bindings,
                    resolved["values"],
                    [entry.to_mapping() for entry in all_entries],
                ]
            )
            if resume_fingerprint is not None and fingerprint != resume_fingerprint:
                raise error(
                    "Interrupted installation no longer matches current configuration; explicit reconciliation is required"
                )
            record = None
            for path in _operations(root).glob("*.json"):
                candidate = _read_operation(path)
                if (
                    candidate.get("fingerprint") == fingerprint
                    and candidate["phase"] != "completed"
                ):
                    record = candidate
                    break
            record = record or {
                **result,
                "operation_id": "mcp_" + uuid.uuid4().hex[:16],
                "fingerprint": fingerprint,
                "profile": get_active_profile(),
            }
            record.update(phase="prepared", targets=[], ok=True)
            record.setdefault("applied_changes", [])
            record.pop("error_code", None)
            record.pop("action_needed", None)
            _write_operation(root, record)
            after = {**before, "mcp-onboarding": {"contract-version": "v1", "bindings": bindings}}
            try:
                if after != before:
                    save_yaml_file(_config_path(root), after, atomic=True, sort_keys=False)
                    record["changed"] = True
                record["changed"] |= requirements.persist(root, owner.component_id, resolved)
                record["phase"] = "intent_committed"
            except Exception as exc:
                record.update(
                    ok=False,
                    phase="needs_reconciliation",
                    error_code=getattr(exc, "code", "VAL-MCPONB-001"),
                    action_needed="Resolve the intent persistence failure before repeating the installation.",
                )
                _write_operation(root, record)
                return status(root, record["operation_id"])
            _write_operation(root, record)
        active_target = None
        install_context = _installing.set(True)
        try:
            from audiagentic.foundation.lifecycle.components import (
                enable_component,
                install_component,
            )

            def ensure(component_id, trail=()):
                if component_id in trail:
                    raise error("Component dependency cycle")
                descriptor = owners[component_id]
                for dependency in descriptor.depends_on:
                    ensure(dependency, (*trail, component_id))
                if not is_installed(component_id, root):
                    outcome = install_component(component_id, root)
                    if not outcome.get("ok", False):
                        raise error("Owning component installation failed")
                elif not is_enabled(component_id, root):
                    enable_component(component_id, root)

            ensure(owner.component_id)
            record["phase"] = "applying"
            _write_operation(root, record)
            for pid, request in requests.items():
                active_target = pid
                if _hash(_config(root)) != _hash(after):
                    raise error("Project selection changed during installation; retry preflight")
                # Lifecycle callbacks can change effective provider/component state
                # after initial preflight. Never replay the pre-install exposure.
                request = _requests(root, bindings, declarations).get(
                    pid, providers_api.ManagedMcpRequest("component-mcp", None, ())
                )
                # Own previous target commits change the shared registry revision.
                fresh = providers_api.preflight_managed_mcp(
                    root, pid, request=request, adopt_entries=all_entries
                )
                receipt = providers_api.apply_managed_mcp(
                    root,
                    pid,
                    request=request,
                    expected_revision=fresh["revision"],
                    adopt_entries=all_entries,
                )
                target = {
                    "harness_id": pid,
                    "configured": bool(receipt["ok"])
                    and pid in selected
                    and providers_api.is_native_mcp_target_enabled(root, pid),
                    "changed": bool(receipt["changed"]),
                    "restart_required": receipt["restart_required"],
                    "phase": "completed" if receipt["ok"] else "needs_reconciliation",
                }
                for key in ("error_code", "action_needed"):
                    if receipt.get(key):
                        target[key] = receipt[key]
                if pid in selected and not providers_api.is_native_mcp_target_enabled(root, pid):
                    target["action_needed"] = (
                        "Enable this provider to restore its selected native MCP entries."
                    )
                record["targets"].append(target)
                if receipt["ok"]:
                    for change in fresh["changes"]:
                        public_change = {
                            "harness_id": pid,
                            "managed_id": change["managed_id"],
                            "action": change["action"],
                        }
                        if public_change not in record["applied_changes"]:
                            record["applied_changes"].append(public_change)
                    if pid not in selected and meta["managed_id"] in receipt["removed_ids"]:
                        removed = record.setdefault("removed_harness_ids", [])
                        if pid not in removed:
                            removed.append(pid)
                record["changed"] |= bool(receipt["changed"])
                record["ok"] &= bool(receipt["ok"])
                _write_operation(root, record)
            record["phase"] = "completed" if record["ok"] else "needs_reconciliation"
        except Exception as exc:
            record.update(
                ok=False,
                phase="needs_reconciliation",
                error_code=getattr(exc, "code", "VAL-MCPONB-001"),
                action_needed="Inspect installation status and resolve the owning error before repeating this request.",
            )
            seen = {row["harness_id"] for row in record["targets"]}
            for pid in requests:
                if pid not in seen:
                    row = {
                        "harness_id": pid,
                        "phase": "needs_reconciliation"
                        if pid == active_target
                        else "not_attempted",
                    }
                    if pid == active_target:
                        row["error_code"] = record["error_code"]
                    record["targets"].append(row)
        finally:
            _installing.reset(install_context)
        _write_operation(root, record)
        return status(root, record["operation_id"])


def reconcile(root: Path) -> list[dict]:
    """Converge native selections after lifecycle events, without legacy broadcast."""
    if _installing.get() or not _config_path(root).exists():
        return []
    with AdvisoryLock(_operations(root) / ".run.lock"):
        return _reconcile_locked(root)


def _reconcile_locked(root: Path) -> list[dict]:
    """Resolve desired state only after competing installers have finished."""
    pending = status(root)
    if pending.get("phase") in {"prepared", "intent_committed", "applying"}:
        return [
            {
                "error_code": "VAL-MCPONB-001",
                "action_needed": "Inspect or resume the pending installation before reconciling.",
            }
        ]
    data = _config(root)
    if "mcp-onboarding" not in data:
        return [
            {
                "error_code": "VAL-MCPONB-001",
                "action_needed": "Use an explicit install to migrate native selections.",
            }
        ]
    bindings = data["mcp-onboarding"]["bindings"]
    recorded_targets = providers_api.list_component_mcp_targets(root)
    if not any(bindings.values()) and not recorded_targets:
        return []
    _, declarations = _declarations(root)
    requests = _requests(root, bindings, declarations)
    for pid in recorded_targets:
        requests.setdefault(pid, providers_api.ManagedMcpRequest("component-mcp", None, ()))
    errors = []
    for pid, request in requests.items():
        try:
            plan = providers_api.preflight_managed_mcp(root, pid, request=request)
            if any(c.get("updates_existing") for c in plan["changes"]):
                raise error("Background native payload changes require an explicit installation")
            outcome = providers_api.apply_managed_mcp(
                root, pid, request=request, expected_revision=plan["revision"]
            )
            if not outcome["ok"]:
                errors.append(
                    {
                        "harness_id": pid,
                        "error_code": outcome.get("error_code", "VAL-MCPONB-001"),
                    }
                )
        except AudiaGenticError as exc:
            errors.append({"harness_id": pid, "error_code": exc.code})
    return errors


def resume(root: Path) -> list[dict]:
    """Startup recovery is owner-controlled; status queries never mutate."""
    pending = status(root)
    if pending.get("phase") in {"prepared", "intent_committed", "applying"}:
        # Reconstruct from safe persisted request identity and canonical owner config.
        record = json.loads(
            (_operations(root) / f"{pending['operation_id']}.json").read_text(encoding="utf8")
        )
        try:
            return [
                install(
                    root,
                    mcp_id=pending["mcp_id"],
                    harness_ids=pending["desired_harness_ids"],
                    non_interactive=True,
                    resume_fingerprint=record["fingerprint"],
                )
            ]
        except AudiaGenticError as exc:
            record.update(
                ok=False,
                phase="needs_reconciliation",
                error_code=exc.code,
                action_needed="Explicit installation is required after interrupted intent or profile changes.",
            )
            _write_operation(root, record)
            return [status(root, record["operation_id"])]
    return reconcile(root)
