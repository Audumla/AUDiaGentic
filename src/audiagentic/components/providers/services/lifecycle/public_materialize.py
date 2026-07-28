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


def _upsert_ag_rig_source(project_root: Path, harness_cfg: dict) -> None:
    """Persist the rig as the ordinary local OpenAI-compatible endpoint.

    The port/model are runtime-derived facts, but the source remains normal
    project desired state consumed by ``build_model_projection_request``.
    """
    from audiagentic.components.providers.services.config.model_source_config import (
        load_model_sources,
        write_model_sources,
    )
    from audiagentic.runtime.harness.config import (
        require_harness_rig_port,
    )

    rig_section = harness_cfg.get("rig", {})
    model_name = rig_section.get("model") or "qwen3.5-0.8b"
    port = require_harness_rig_port(harness_cfg)
    document = load_model_sources(project_root)
    sources = document.setdefault("sources", {})
    desired = {
        "source-class": "local-endpoint",
        "display-name": "AUDiaGentic Embedded Rig",
        "connector": "openai-compatible",
        "model-id": str(model_name),
        "base-url": f"http://127.0.0.1:{port}/v1",
        "provider-overrides": {"provider-id": rig_section.get("provider", "audiagentic")},
        "enabled": True,
    }
    if sources.get("ag-rig") != desired:
        sources["ag-rig"] = desired
        write_model_sources(project_root, document)


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

    _upsert_ag_rig_source(project_root, harness_cfg)
    from audiagentic.components.providers.services.catalog.models import (
        build_model_projection_request,
    )

    request = build_model_projection_request(project_root, provider_id, enabled=True)

    from audiagentic.components.providers.services.execution.execution import (
        load_materialize_builder,
        load_materialize_model_config_path_resolver,
    )
    builder = load_materialize_builder(provider_id)
    if builder is None:
        from audiagentic.foundation.contracts.errors import make_error

        raise make_error(
            prefix="CFG", component="HRN", number=9, kind="harness-config",
            message=f"Provider {provider_id!r} does not declare config materialization.",
            details={"provider_id": provider_id},
        )
    resolver = load_materialize_model_config_path_resolver(provider_id)
    if resolver is not None:
        from dataclasses import replace

        request = replace(request, config_path=str(resolver(project_root, agent_runtime)))

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

    # Surface rendering + provider-specific files are a provider adapter
    # capability.  Do not centralize provider ids here: a new provider becomes
    # materializable by supplying adapters/<id>/install.py.
    builder(project_root, harness_cfg, agent_runtime=agent_runtime)
