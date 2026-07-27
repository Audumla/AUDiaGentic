"""Provider config materialization — public service.

Dispatches to the adapter-owned install module for each provider, routing
through providers_api (HA11). The runtime should not need a bespoke module per
harness type when the provider already knows its own config shapes.
"""

from __future__ import annotations

from pathlib import Path


def materialize_provider_config(
    project_root: Path,
    provider_id: str,
    harness_cfg: dict,
    *,
    agent_runtime: Path | None = None,
) -> None:
    """Route config materialization to the correct provider adapter."""
    if provider_id == "pi":
        from audiagentic.components.providers.adapters.pi.install import (
            materialize_provider_config as _materialize_pi,
        )

        _materialize_pi(
            project_root,
            harness_cfg,
            agent_runtime=agent_runtime,
        )
    elif provider_id == "opencode":
        from audiagentic.components.providers.adapters.opencode.install import (
            materialize_provider_config as _materialize_opencode,
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
