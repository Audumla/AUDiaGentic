"""Provider config materialization — public service.

Aligns with capability families where they exist (model-projection,
generated-surfaces) and delegates to adapter install modules for
provider-specific files that have no family yet (HA11).

Model config routes through the model-projection family (managed, MO06).
Surface rendering uses generated-surfaces family (already in adapter install).
Provider-specific files (settings.json, APPEND_SYSTEM.md) delegate directly.
"""

from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.contracts.model_projection import (
    ModelProjectionRequest,
)

# Import MaterializedModelEntry from its actual location
from audiagentic.components.providers.services.catalog.models import (
    MaterializedModelEntry,
)


def _build_rig_model_entry(
    harness_cfg: dict,
) -> MaterializedModelEntry:
    """Build a MaterializedModelEntry for the local embedded rig.

    Constructs the entry from harness_cfg.rig.* config so it can be
    applied via the model-projection capability family.
    """
    from audiagentic.runtime.harness.config import (
        require_harness_rig_port,
    )

    rig_section = harness_cfg.get("rig", {})
    model_name = rig_section.get("model") or "qwen3.5-0.8b"
    port = require_harness_rig_port(harness_cfg)

    return MaterializedModelEntry(
        source_id="ag-rig",
        model_id=model_name,
        visible_name="AUDiaGentic local planner",
        connector="openai-compatible",
        managed_id=f"ag-rig-{model_name}",
        endpoint={
            "base-url": f"http://127.0.0.1:{port}/v1",
            "single-model": True,
        },
    )


def materialize_provider_config(
    project_root: Path,
    provider_id: str,
    harness_cfg: dict,
    *,
    agent_runtime: Path | None = None,
) -> None:
    """Route config materialization through capability families.

    Model config goes through the model-projection family (managed).
    Surface rendering uses generated-surfaces family (already in adapter
    install modules). Provider-specific files delegate to adapter
    install modules directly.
    """
    from audiagentic.components.providers import providers_api
    from audiagentic.foundation.cli_io import print_message

    rig_entry = _build_rig_model_entry(harness_cfg)
    request = ModelProjectionRequest(
        managed_ids=(rig_entry.managed_id,),
        entries=(rig_entry,),
    )

    # Model config via model-projection family (managed)
    try:
        result = providers_api.manage_model_projection(
            project_root,
            provider_id,
            mode="apply",
            request=request,
        )
        if not result.ok:
            print_message(
                f"Warning: model-projection apply failed for {provider_id}: {result.error_code}",
            )
    except Exception:  # noqa: BLE001 — materialize is best-effort
        import logging

        logging.getLogger(__name__).warning(
            f"model-projection apply failed for {provider_id}",
            exc_info=True,
        )

    # Surface rendering + provider-specific files via adapter install modules
    if provider_id == "pi":
        from audiagentic.components.providers.adapters.pi.install import (
            materialize_provider_specific as _materialize_pi,
        )

        _materialize_pi(
            project_root,
            harness_cfg,
            agent_runtime=agent_runtime,
        )
    elif provider_id == "opencode":
        from audiagentic.components.providers.adapters.opencode.install import (
            materialize_provider_specific as _materialize_opencode,
        )

        _materialize_opencode(project_root, harness_cfg)
    else:
        from audiagentic.foundation.contracts.errors import make_error

        raise make_error(
            prefix="CFG",
            component="HRN",
            number=9,
            kind="harness-config",
            message=f"No materialize handler for provider {provider_id!r}.",
            details={"provider_id": provider_id},
        )
