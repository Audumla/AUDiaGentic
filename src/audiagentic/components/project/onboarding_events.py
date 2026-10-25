"""Project-owned exposure reconciliation subscribers."""

from pathlib import Path

from audiagentic.components.providers import providers_api
from audiagentic.foundation.event import get_bus, subscribe_component_lifecycle
from audiagentic.foundation.io import atomic_write_json

from . import project_api


def _reconcile(root, payload, metadata):
    try:
        errors = project_api.reconcile_mcp_bindings(root)
    except Exception as exc:
        errors = [{"error_code": getattr(exc, "code", "VAL-MCPONB-001")}]
    if errors:
        atomic_write_json(
            root / ".audiagentic/state/mcp-onboarding/last-reconcile.json", {"errors": errors}
        )


def _provider_change(event_type, payload, metadata):
    root = payload.get("project_root")
    if isinstance(root, Path):
        _reconcile(root, payload, metadata)


_on_lifecycle = subscribe_component_lifecycle(
    None,
    on_installed=_reconcile,
    on_enabled=_reconcile,
    on_disabled=_reconcile,
    on_uninstalled=_reconcile,
    on_config_changed=_reconcile,
)
get_bus().subscribe(providers_api.PROVIDER_STATE_CHANGED, _provider_change)
