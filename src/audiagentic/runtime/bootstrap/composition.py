"""The composition root: the only module that reads bindings and builds a graph.

Contributions are an explicit built-in list. There is no package scanning and no
second plugin system — a new service is added here, in code, and selected in
`composition.yaml` by identifier.

This is the one place permitted to import across every layer (ARCHITECTURE
STANDARDS §1, "Composition root — may depend on: any layer"). Nothing here is
importable from a domain service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.composition import (
    BuiltGraph,
    CompositionConfig,
    ImplementationId,
    ServiceContribution,
    ServiceId,
    build_graph,
    load_composition_config,
)
from audiagentic.foundation.paths.package import PACKAGE_ROOT

APPLICATION_HOST = ServiceId("runtime.application-host")
INTERACTION_BACKEND = ServiceId("foundation.interaction-backend")


def _pkg_default_path() -> Path:
    return PACKAGE_ROOT / "config" / "provisioning" / "foundation" / "composition.yaml"


def _build_cli_interaction_backend() -> Any:
    from audiagentic.foundation.interaction import CliBackend

    return CliBackend()


def _build_application_host(*, interaction_backend: Any) -> Any:
    from audiagentic.runtime.bootstrap.application_host import ApplicationHost

    return ApplicationHost(interaction_backend=interaction_backend)


def builtin_contributions() -> tuple[ServiceContribution, ...]:
    """Every implementation this process can be configured to use."""
    return (
        ServiceContribution(
            service_id=INTERACTION_BACKEND,
            implementation_id=ImplementationId("foundation.cli-interaction"),
            factory=_build_cli_interaction_backend,
        ),
        ServiceContribution(
            service_id=APPLICATION_HOST,
            implementation_id=ImplementationId("runtime.default-host"),
            factory=_build_application_host,
            requires={"interaction_backend": INTERACTION_BACKEND},
            finalizer=lambda host: host.shutdown(),
        ),
    )


def build_application_graph(
    *,
    project_root: Path | None = None,
    config: CompositionConfig | None = None,
    overrides: dict[ServiceId, Any] | None = None,
) -> BuiltGraph:
    """Build the process graph.

    `config` and `overrides` exist so tests can compose a graph without touching
    the packaged YAML or the real services; production passes neither.
    """
    resolved = config or load_composition_config(
        pkg_default_path=_pkg_default_path(),
        project_root=project_root,
    )
    return build_graph(builtin_contributions(), resolved, overrides=overrides)
