"""Generic gateway-management implementation selection and config (SH11 Slice C).

Mirrors ``components.planning.planning_api``'s generic get/set/select
pattern exactly (RV736 M2: no gateway-specific option store, second
registry, or custom validation -- these are thin wrappers over the shared
``foundation.features.*`` machinery, the same machinery `planning`,
`coding-lsp`, `memory`, and `providers` already use).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

_COMPONENT_ID = "agents"
_RESTART_POLL_SECONDS = 0.25


def _restart_wait_seconds() -> float:
    from audiagentic.components.agents.gateway.settings import gateway_setting

    return float(gateway_setting("restart_wait_seconds", 60))


def active_implementation_id(project_root: Path) -> str:
    """Return the enabled gateway implementation ID, or the descriptor default."""
    from audiagentic.foundation.features.registry import resolve_active_implementation

    return resolve_active_implementation(project_root, _COMPONENT_ID) or ""


def gateway_status(project_root: Path) -> dict[str, Any]:
    """Active gateway implementation and whether it was explicitly selected."""
    from audiagentic.foundation.features.registry import (
        get_implementation,
        is_default_implementation,
    )
    from audiagentic.foundation.features.state import get_implementation_state

    target_impl = active_implementation_id(project_root)
    if not target_impl:
        return {"implementation": None, "enabled": False, "is_default": False}

    desc = get_implementation(_COMPONENT_ID, target_impl)
    impl_state = get_implementation_state(project_root, _COMPONENT_ID, target_impl)
    return {
        "implementation": target_impl,
        "enabled": impl_state.enabled,
        "is_default": bool(desc and is_default_implementation(desc)),
    }


def gateway_health(project_root: Path) -> dict[str, Any]:
    """Return a read-only health projection for the shared gateway service."""
    from audiagentic.components.agents.gateway.service.bootstrap import start_or_attach_gateway

    client = start_or_attach_gateway()
    try:
        service = client.service_status(project_root)
        overview = client.gateway_overview(project_root)
    finally:
        client.close()
    diagnostics = overview.get("diagnostics") or {}
    healthy = (
        service.get("state") == "running"
        and int(diagnostics.get("skipped_count", 0)) == 0
        and int(service.get("quiescence", {}).get("running-requests", 0)) >= 0
    )
    return {
        "healthy": healthy,
        "state": service.get("state"),
        "owner-epoch": service.get("owner-epoch"),
        "process-instance-id": overview.get("runtime-fingerprint", {}).get("process-instance-id"),
        "providers-loaded": diagnostics.get("providers_loaded", 0),
        "providers-skipped": diagnostics.get("skipped_count", 0),
        "quiescence": service.get("quiescence", {}),
    }


def gateway_list_implementations(project_root: Path) -> dict[str, Any]:
    from audiagentic.foundation.features.registry import (
        get_implementations,
        is_default_implementation,
    )

    active = active_implementation_id(project_root)
    impls = get_implementations(_COMPONENT_ID)
    return {
        "active": active,
        "implementations": {
            impl_id: {
                "display_name": desc.display_name,
                "description": desc.description,
                "is_default": is_default_implementation(desc),
            }
            for impl_id, desc in impls.items()
        },
    }


def gateway_select_implementation(project_root: Path, implementation_id: str) -> dict[str, Any]:
    from audiagentic.foundation.features.lifecycle import enable_implementation

    return enable_implementation(project_root, _COMPONENT_ID, implementation_id)


def gateway_get_config(project_root: Path, implementation_id: str | None = None) -> dict[str, Any]:
    """Return resolved config and settable-option schema for a gateway implementation.

    ``schema`` lets a caller discover every option an implementation accepts
    (type, description, required, default, allowed values) generically, then
    set any of them via ``gateway_set_config`` -- no implementation-specific
    tools (e.g. a hardcoded "set automatic startup timeout" tool) exist on
    this surface, per CREATING_A_COMPONENT.md's implementation-backed
    component rule.
    """
    from audiagentic.foundation.features.options import option_schema_to_dict
    from audiagentic.foundation.features.registry import (
        get_implementation,
        is_default_implementation,
    )
    from audiagentic.foundation.features.state import get_implementation_state

    target_impl = implementation_id or active_implementation_id(project_root)
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


def gateway_set_config(
    project_root: Path,
    implementation_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Validate and persist config updates for a gateway implementation."""
    from audiagentic.foundation.features.base import ImplementationState
    from audiagentic.foundation.features.registry import get_implementation
    from audiagentic.foundation.features.state import (
        get_implementation_state,
        set_implementation_state,
    )

    desc = get_implementation(_COMPONENT_ID, implementation_id)
    if desc is None:
        raise AudiaGenticError(
            code="VAL-AGSV-027",
            kind="validation",
            message=f"unknown gateway implementation: {implementation_id!r}",
        )

    # An implementation that declares no options accepts none.
    for key, value in updates.items():
        option_schema = (desc.options_schema or {}).get(key)
        if option_schema is None:
            if not any(s.allow_unknown for s in (desc.options_schema or {}).values()):
                raise AudiaGenticError(
                    code="VAL-AGSV-028",
                    kind="validation",
                    message=f"unknown option: {key!r} for gateway implementation {implementation_id!r}",
                    details={"valid_options": list((desc.options_schema or {}).keys())},
                )
        else:
            from audiagentic.foundation.features.options import validate_option
            try:
                validate_option(key, value, option_schema)
            except (AudiaGenticError, ValueError) as exc:
                raise AudiaGenticError(
                    code="VAL-AGSV-029",
                    kind="validation",
                    message=f"invalid value for option {key!r}: {exc}",
                ) from exc

    impl_state = get_implementation_state(project_root, _COMPONENT_ID, implementation_id)
    options = dict(impl_state.options)
    options.update(updates)

    new_state = ImplementationState(enabled=impl_state.enabled, options=options)
    set_implementation_state(project_root, _COMPONENT_ID, implementation_id, new_state)

    return {
        "implementation": implementation_id,
        "config": options,
        "updated_keys": list(updates.keys()),
    }



def gateway_validate_role_config(role: str, config_path: Path) -> None:
    """Validate one shared-gateway role document offline through its owning loader.

    ``role`` is ``server``, ``node`` or ``connector``. Nothing is started, no network
    is touched and credentials are checked for mode and identity but never read.
    Raises ``AudiaGenticError`` on any invalid document.
    """
    from audiagentic.foundation.contracts.errors import make_error_factory

    from .service import shared_config

    loaders = {
        "server": shared_config.load_shared_server_config,
        "node": shared_config.load_shared_node_config,
        "connector": shared_config.load_shared_connector_config,
    }
    if role not in loaders:
        raise make_error_factory("VAL", "AGSV", "gateway-service")(
            6, "gateway role must be server, node or connector", role=role)
    loaders[role](Path(config_path).resolve())


def gateway_validate_deployment(role: str, config_path: Path, project: Path | None = None) -> dict[str, Any]:
    """Validate a role document in its deployment context, offline.

    ``server``: the loader also resolves the served roots (the omitted-roots default is the
    ``project`` or the working-directory project), each root's declared project.id, duplicate
    roots/ids and every principal grant. ``connector``: a shared connector also needs the
    ``project`` (or working-directory project) to declare a project.id. ``node`` is the loader.
    Reachability, TLS, proxies and live authentication are out of scope. Returns what was resolved.
    """
    from audiagentic.foundation.config.settings import discover_project_root

    from .service import shared_config
    from .settings import declared_project_id

    path = Path(config_path).resolve()
    root = discover_project_root(project, cwd=Path.cwd())
    if role == "server":
        server = shared_config.load_shared_server_config(path, default_root=root)
        return {"role": role, "projects": {key: str(value) for key, value in server.projects.items()},
                "principals": [principal.principal_id for principal in server.principals]}
    if role == "connector":
        connector = shared_config.load_shared_connector_config(path)
        if connector.mode == "shared" and declared_project_id(root) is None:
            from audiagentic.foundation.contracts.errors import make_error_factory

            raise make_error_factory("CFG", "AGSV", "gateway-service")(
                3, "a shared gateway connection needs a declared project.id in the project's settings")
        return {"role": role, "mode": connector.mode, "project-id": declared_project_id(root)}
    gateway_validate_role_config(role, path)
    return {"role": role}


def gateway_where(*, project: Path | None = None) -> dict[str, Any]:
    """Offline report of the gateway's configuration locations, binding and project identity."""
    from .service.where_report import gateway_where as _where

    return _where(project=project)


def gateway_init(*, directory: Path | None = None, project: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Generate the same-machine shared-gateway setup (server, connector, token) and bind this machine.

    Never overwrites or rotates existing files; the result never contains a token.
    """
    from .service.init_setup import gateway_init as _init

    return _init(directory=directory, project=project, dry_run=dry_run)


def gateway_connector_health(config_path: Path, project_root: Path | None) -> dict[str, Any]:
    """Load a connector document, handshake with its gateway and return the health answer.

    A shared connection addresses the project's declared ``project.id``; a plain one needs no
    project. The client is closed before returning; nothing is bound.
    """
    from .client import connector_client
    from .settings import declared_project_id
    from .service.shared_config import load_shared_connector_config

    connector = load_shared_connector_config(Path(config_path).resolve())
    project_id = None
    if connector.mode == "shared":
        project_id = declared_project_id(project_root)
        if project_id is None:
            from audiagentic.foundation.contracts.errors import make_error_factory

            raise make_error_factory("CFG", "AGSV", "gateway-service")(
                3, "a shared gateway connection needs a declared project.id in the project's settings")
    client = connector_client(connector, project_root, project_id)
    try:
        return client.health()
    finally:
        client.close()


def gateway_connect_config(config_path: Path) -> dict[str, Any]:
    """Bind this machine to a validated connector document.

    Writes ``gateway.connector`` and ``gateway.implementation: standalone`` to the user
    settings in one patch through the settings writer, so every project on the machine
    uses the connection. Callers complete the health handshake before requesting this
    write. Nothing about the connection is stored in settings except the document's path.
    """
    from audiagentic.foundation.config.writer import write_settings_patch

    reference = str(Path(config_path).resolve(strict=True))
    gateway_validate_role_config("connector", Path(reference))
    write_settings_patch("user", {"gateway": {"connector": reference, "implementation": "standalone"}})
    return {"implementation": "standalone", "connector": reference}


def gateway_create_operation(
    project_root: Path,
    *,
    operation_id: str,
    kind: str,
    scope: dict[str, Any],
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Create a durable operator operation through the standalone authority."""
    from audiagentic.components.agents.gateway.service.bootstrap import start_or_attach_gateway

    client = start_or_attach_gateway()
    try:
        return client.create_gateway_operation(
            project_root,
            operation_id=operation_id,
            kind=kind,
            scope=scope,
            correlation_id=correlation_id,
        )
    finally:
        client.close()


def gateway_get_operation(project_root: Path, operation_id: str) -> dict[str, Any]:
    """Read the public projection of a durable gateway operation."""
    from audiagentic.components.agents.gateway.service.bootstrap import start_or_attach_gateway

    client = start_or_attach_gateway()
    try:
        return client.get_gateway_operation(project_root, operation_id)
    finally:
        client.close()


def gateway_list_operations(project_root: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    """List redacted durable gateway operation status for safe maintenance."""
    from audiagentic.components.agents.gateway.service.bootstrap import start_or_attach_gateway

    client = start_or_attach_gateway()
    try:
        return client.list_gateway_operations(project_root, limit=limit)
    finally:
        client.close()


def gateway_get_retention_policy(project_root: Path) -> dict[str, Any]:
    """Return the redacted machine retention policy for operator inspection.

    The policy resolver is deliberately machine-scoped; this projection exposes
    only effect-relevant values and never the policy path or any project data.
    ``project_root`` is accepted for management-surface parity but is not used
    to resolve policy, preventing project configuration from weakening it.
    """
    del project_root
    from audiagentic.components.agents.gateway.operations.retention_policy import (
        load_retention_policy,
    )

    policy = load_retention_policy()
    from .journal_retention import journal_retention_days

    return {
        "available": policy.available,
        "purge-enabled": policy.enabled,
        "minimum-archive-age-seconds": policy.minimum_archive_age_seconds,
        "max-batch-size": policy.max_batch_size,
        "request-history-limit": policy.request_history_limit,
        "journal-retention-days": journal_retention_days(),
        "journal-rotation": "daily-utc-and-size",
        "journal-compression": "gzip-closed-segments",
        "timeline-max-bytes": policy.timeline_max_bytes,
        "observation-max-bytes": policy.observation_max_bytes,
        "recovery-max-bytes": policy.recovery_max_bytes,
        "console-trace-max-bytes": policy.console_trace_max_bytes,
        "policy-id": policy.policy_id,
        "policy-digest": policy.digest,
    }


def gateway_restart(project_root: Path, *, force: bool = False) -> dict[str, Any]:
    """Restart the machine-scoped gateway service through its managed lifecycle.

    The caller's project root is only the admission context; the service itself
    remains machine-scoped. The managed lifecycle performs a durable handoff
    before the replacement starts; no unrelated MCP stdio processes are touched.
    """
    from audiagentic.components.agents.gateway.service.bootstrap import (
        attach_existing_gateway,
        start_or_attach_gateway,
    )

    del force
    client = start_or_attach_gateway()
    try:
        restarting = client.dashboard_restart(project_root)
    finally:
        client.close()

    old_epoch = restarting.get("owner-epoch")
    deadline = time.monotonic() + _restart_wait_seconds()
    replacement = None
    last_error: AudiaGenticError | None = None
    while replacement is None:
        try:
            # The retiring host owns the replacement launch.  This waiter is
            # attach-only so a delayed/failed handoff cannot create a second
            # process generation behind the host's back.
            candidate = attach_existing_gateway()
            status = candidate.service_status(project_root)
            if old_epoch is not None and status.get("owner-epoch") == old_epoch:
                candidate.close()
                raise AudiaGenticError(
                    "CON-MSVC-030",
                    "agents",
                    "gateway replacement has not changed owner epoch",
                )
            replacement = candidate
        except AudiaGenticError as exc:
            # The old generation is expected to remain observable while it
            # drains and retires. Retry only those lifecycle race outcomes;
            # all configuration/auth/protocol errors remain fail-closed.
            if exc.code not in {
                "CON-MSVC-026",
                "CON-MSVC-027",
                "CON-MSVC-028",
                "CON-MSVC-030",
            }:
                raise
            last_error = exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise last_error
            time.sleep(min(_RESTART_POLL_SECONDS, remaining))
    try:
        status = replacement.service_status(project_root)
    finally:
        replacement.close()
    return {"restarting": restarting, "restarted": True, "status": status}


def _attached_call(project_root: Path, method: str, **kwargs: Any) -> dict[str, Any]:
    """Call one lifecycle method on the running service; never starts a service."""
    from audiagentic.components.agents.gateway.service.bootstrap import attach_existing_gateway

    client = attach_existing_gateway()
    try:
        return getattr(client, method)(project_root, **kwargs)
    finally:
        client.close()


def gateway_drain(project_root: Path) -> dict[str, Any]:
    """Stop the running service admitting new work; in-flight work finishes."""
    return _attached_call(project_root, "service_drain")


def gateway_resume(project_root: Path) -> dict[str, Any]:
    """Admit new work again after a drain."""
    return _attached_call(project_root, "service_resume")


def gateway_stop(project_root: Path, *, force: bool = False) -> dict[str, Any]:
    """Stop the running service; graceful stop is refused unless it is quiescent."""
    return _attached_call(project_root, "service_stop", force=force)


def gateway_recover(*, reason: str) -> dict[str, Any]:
    """Record-only recovery of a live-but-unprovable owner; never signals the pid."""
    from audiagentic.components.agents.gateway.service.lifecycle import recover_unprovable_owner

    return recover_unprovable_owner(confirm=True, reason=reason)
