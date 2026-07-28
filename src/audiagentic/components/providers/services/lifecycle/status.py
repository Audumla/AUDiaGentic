"""Provider status inspection helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

from ...descriptors import interrogate as _interrogate
from ...descriptors.registry import (
    all_descriptors,
    get_descriptor,
)
from ..catalog.models import model_ownership_registry, resolve_model_selection
from ..config.provider_catalog import (
    catalog_is_stale,
    read_model_catalog,
    runtime_catalog_path,
)
from ..config.provider_config import (
    apply_feature_enabled_state,
    load_provider_config,
)
from .health import health_check
from .lifecycle import probe_provider_cli


def _model_config_status(provider_id: str, descriptor, project_root: Path) -> dict[str, Any]:
    """Model-config status fields (MO02 step 7 + RV265).

    Reports BOTH managed-model-count (AG-materialized, from the ownership
    registry) and availability-count (the runtime catalog where one exists) so
    materialized-vs-observed drift per MO01 step 7b is visible.
    """
    spec = getattr(descriptor, "model_config", None) if descriptor else None
    status: dict[str, Any] = {
        "supported": spec is not None,
        "config-path": None,
        "format": spec.format if spec else None,
        "refresh-mode": spec.refresh_mode if spec else None,
        "managed-model-count": 0,
        "managed-ids": [],
    }
    if spec is not None:
        from audiagentic.foundation.toolchains.config.managed_config import (
            resolve_managed_config_path,
        )

        try:
            status["config-path"] = str(resolve_managed_config_path(spec, project_root))
        except AudiaGenticError:
            status["config-path"] = None
        if spec.refresh_mode == "restart-required":
            status["action-needed"] = (
                f"restart {getattr(descriptor, 'display_name', provider_id)} "
                "to apply model config changes"
            )
    try:
        owned = model_ownership_registry(project_root).load().get(provider_id, {})
    except AudiaGenticError as exc:
        status["registry-error"] = exc.code
        return status
    status["managed-model-count"] = len(owned)
    status["managed-ids"] = sorted(owned)
    return status


def _provider_entry(
    *,
    provider_id: str,
    provider_cfg: dict[str, Any],
    project_root: Path,
    include_probes: bool,
    now_fn=None,
) -> dict[str, Any]:
    health = health_check(provider_id, {"provider-id": provider_id}, provider_cfg, now_fn=now_fn)
    entry: dict[str, Any] = {
        "provider-id": provider_id,
        "provider_id": provider_id,
        "enabled": provider_cfg.get("enabled", False),
        "install-mode": provider_cfg.get("install-mode"),
        "access-mode": provider_cfg.get("access-mode"),
        "configured": health.get("configured", False),
        "status": health.get("status"),
        "error": health.get("error"),
        "checked-at": health.get("checked-at"),
        "default-model": provider_cfg.get("default-model"),
        "model-aliases": provider_cfg.get("model-aliases", {}),
    }

    prompt_surface = provider_cfg.get("prompt-surface")
    if isinstance(prompt_surface, dict):
        entry["prompt-surface"] = {
            "enabled": prompt_surface.get("enabled", False),
            "tag-syntax": prompt_surface.get("tag-syntax"),
            "first-line-policy": prompt_surface.get("first-line-policy"),
            "cli-mode": prompt_surface.get("cli-mode"),
            "vscode-mode": prompt_surface.get("vscode-mode"),
            "settings-profile": prompt_surface.get("settings-profile"),
            "supported-modes": [
                mode
                for mode in (
                    prompt_surface.get("cli-mode"),
                    prompt_surface.get("vscode-mode"),
                )
                if mode and mode != "unsupported"
            ],
        }

    catalog_path = runtime_catalog_path(project_root, provider_id)
    entry["catalog-path"] = str(catalog_path)
    entry["catalog-present"] = catalog_path.exists()
    entry["catalog-stale"] = None
    entry["catalog-model-count"] = None
    entry["catalog-source"] = None

    descriptor = get_descriptor(provider_id)
    entry["model-config"] = _model_config_status(provider_id, descriptor, project_root)
    cli_probe = descriptor.cli_probe if descriptor and descriptor.cli_probe else None
    entry["cli-check"] = probe_provider_cli(descriptor) if descriptor and include_probes else None

    from ..host.host_adapter import all_host_adapters

    interrogation = (
        _interrogate(provider_id, project_root)
        if include_probes
        else {
            "provider_id": provider_id,
            "display_name": descriptor.display_name if descriptor else provider_id,
            "registered": descriptor is not None,
            "cli": None,
            "host_capabilities": [],
            "hosts": {
                host_id: {"workspace": adapter.detect_workspace(project_root)}
                for host_id, adapter in all_host_adapters().items()
            },
            "permissions": {
                "can_write_files": descriptor.permissions.can_write_files if descriptor else False,
                "can_execute_shell": descriptor.permissions.can_execute_shell
                if descriptor
                else False,
                "can_browse_web": descriptor.permissions.can_browse_web if descriptor else False,
                "can_read_env": descriptor.permissions.can_read_env if descriptor else False,
                "notes": descriptor.permissions.notes if descriptor else "",
            },
            "agent_files": [],
        }
    )
    entry["interrogation"] = interrogation
    host_capabilities = interrogation.get("host_capabilities", [])
    hosts: dict[str, dict[str, Any]] = interrogation.get("hosts", {})

    host_extensions: dict[str, dict[str, Any]] = {}
    for host_id, host_info in hosts.items():
        extensions = [e for e in host_capabilities if e.get("host") == host_id]
        workspace = bool(host_info.get("workspace"))
        applicable = bool(workspace and extensions)
        installed = (
            True
            if applicable and all(e.get("installed") is True for e in extensions)
            else False
            if applicable and any(e.get("installed") is False for e in extensions)
            else None
        )
        host_extensions[host_id] = {
            "workspace": workspace,
            "applicable": applicable,
            "installed": installed,
            "extensions": extensions,
        }

    entry["installation"] = {
        "cli": {
            "applicable": cli_probe is not None,
            "installed": entry["cli-check"].get("available") if entry["cli-check"] else None,
            "probe": entry["cli-check"],
        },
        "host-extensions": host_extensions,
        "host-capabilities": host_capabilities,
    }
    entry["cli-installed"] = entry["installation"]["cli"]["installed"]
    entry["host-extension-installed"] = {
        host_id: info["installed"] for host_id, info in host_extensions.items()
    }

    if entry["catalog-present"]:
        try:
            catalog = read_model_catalog(project_root, provider_id)
        except AudiaGenticError as exc:
            entry["catalog-error"] = {
                "code": exc.code,
                "kind": exc.kind,
                "message": exc.message,
                "details": dict(exc.details or {}),
            }
        else:
            entry["catalog-source"] = catalog.get("source")
            entry["catalog-model-count"] = len(catalog.get("models", []))
            # RV265/MO01 step 7b: where a runtime catalog exists it is
            # authoritative for availability; a managed entry missing from it
            # is a reconcile discrepancy — surfaced, never silent success.
            model_config_status = entry.get("model-config") or {}
            model_config_status["availability-count"] = entry["catalog-model-count"]
            managed_names = set(
                model_ownership_registry(project_root).load().get(provider_id, {}).values()
            )
            if managed_names:
                catalog_ids = {model.get("model-id") for model in catalog.get("models", [])}
                missing = sorted(managed_names - catalog_ids)
                if missing:
                    model_config_status["availability-drift"] = missing
                    model_config_status["action-needed"] = (
                        "managed model entries are not visible in the provider's "
                        f"runtime catalog: {', '.join(missing)} — re-run model sync "
                        "or refresh the catalog"
                    )
            refresh = provider_cfg.get("catalog-refresh", {})
            max_age = refresh.get("max-age-hours")
            if isinstance(max_age, int) and max_age > 0:
                entry["catalog-stale"] = catalog_is_stale(
                    catalog, max_age_hours=max_age, now_fn=now_fn
                )
            try:
                resolved = resolve_model_selection(
                    provider_id=provider_id,
                    provider_config=provider_cfg,
                    job_request={},
                    catalog=catalog,
                    now_fn=now_fn,
                )
            except AudiaGenticError as exc:
                entry["model-selection-error"] = {
                    "code": exc.code,
                    "kind": exc.kind,
                    "message": exc.message,
                    "details": dict(exc.details or {}),
                }
            else:
                entry["resolved-model"] = resolved.get("model-id")
                entry["resolved-from"] = resolved.get("resolved-from")
                if "catalog-warning" in resolved:
                    entry["catalog-warning"] = resolved["catalog-warning"]

    if (
        include_probes
        and provider_cfg.get("access-mode") == "cli"
        and entry.get("cli-check", {}).get("available")
    ):
        entry["status"] = "healthy" if entry["configured"] else "unhealthy"
        if (
            entry.get("catalog-present")
            and entry.get("catalog-error") is None
            and entry.get("model-selection-error") is None
        ):
            entry["status"] = "healthy"
    return entry


def build_provider_status(
    project_root: Path, provider_id: str | None = None, *, include_probes: bool = True, now_fn=None
) -> dict[str, Any]:
    provider_config = load_provider_config(project_root)
    providers = provider_config.get("providers", {})
    descriptors = all_descriptors()
    if provider_id is not None:
        if provider_id not in providers and provider_id not in descriptors:
            raise AudiaGenticError(
                code="VAL-STATUS-001",
                kind="providers",
                message="unknown provider-id in provider config",
                details={"provider-id": provider_id},
            )
        provider_ids = [provider_id]
    else:
        provider_ids = sorted(set(providers) | set(descriptors))
    return {
        "contract-version": "v1",
        "ok": True,
        "project-root": str(project_root),
        "providers": [
            _provider_entry(
                provider_id=item,
                provider_cfg=apply_feature_enabled_state(
                    project_root,
                    item,
                    providers.get(item, {"enabled": False, "access-mode": "none"}),
                ),
                project_root=project_root,
                include_probes=include_probes,
                now_fn=now_fn,
            )
            for item in provider_ids
        ],
    }
