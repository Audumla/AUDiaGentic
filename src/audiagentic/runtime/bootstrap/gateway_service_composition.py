"""The gateway-service process's composition root (AS60 step 7 / RV888).

A *second*, deliberate composition root — Stage 1's own test docstring
(`test_the_launcher_is_the_only_caller_of_the_composition_root`) names this as
an anticipated case: "One process adopts the host in Stage 1; later roots are
deliberate." This root serves the standalone/automatic gateway-service process
entrypoints (`gateway/service/process.py::main()`,
`commands/gateway.py::cmd_gateway`), not the CLI/launcher process.

It exists because the shared-gateway execution-profile registry is a real
composed singleton for *that* process: `GatewayServiceHost` previously
installed/uninstalled it by hand at construction/close, which is ordinary
process lifecycle, not runtime mode-switching (RV888 corrects AS59's earlier
"runtime mode state, not a binding" verdict). Project-local resolution is not
composed here at all — it is a stateless plain function with nothing to own,
so it never appears in this graph (see AS60's "Public boundary and
composition").

This is the same facility as `runtime/bootstrap/composition.py`, not a new
mechanism: same builder, same non-negotiable rules, its own package-default
config file so it never collides with the launcher root's `composition.yaml`.
"""

from __future__ import annotations

import asyncio
import threading
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

CONFIG_NAMESPACE = "gateway-service-composition"

EXECUTION_PROFILE_REGISTRY = ServiceId("agents.execution-profile-registry")
QUEUE_MANAGER = ServiceId("agents.gateway-queue-manager")
GPT_AUTO_RUNTIME_OWNER = ServiceId("providers.gpt-auto-runtime-owner")
SESSION_RUNTIME_OWNER = ServiceId("agents.gateway-session-runtime-owner")


def build_gateway_application() -> Any:
    """Wire the gateway application to the runtime-owned context reader."""
    from audiagentic.components.agents.gateway.application import InProcessGatewayApplication
    from audiagentic.runtime.component_context import collect_component_context

    return InProcessGatewayApplication(
        component_context_reader=collect_component_context,
    )


def _pkg_default_path() -> Path:
    return (
        PACKAGE_ROOT / "config" / "provisioning" / "foundation" / "gateway-service-composition.yaml"
    )


def _build_shared_gateway_registry_factory() -> Any:
    """Return a factory for the machine-global Agents catalog registry."""

    def factory() -> Any:
        from audiagentic.components.agents.agents_paths import global_agents_config_path
        from audiagentic.components.agents.gateway import profiles as profiles_mod

        resolved_path = global_agents_config_path()
        registry = profiles_mod.load_gateway_registry_from_agents_catalog(
            resolved_path, required=True
        )
        profiles_mod.set_gateway_registry(registry)
        return registry

    return factory


def _uninstall_shared_gateway_registry(_registry: Any) -> None:
    from audiagentic.components.agents.gateway import profiles as profiles_mod

    profiles_mod.set_gateway_registry(None)


def _build_gateway_queue_manager() -> Any:
    """AS63 step 9/10: the queue manager is genuine per-process state (live
    per-profile queues, in-flight concurrency slots) — the same composition
    candidacy the profile registry already met, not an "internal helper with
    one implementation" the doctrine excludes. This process (not the CLI/
    launcher root) owns installing a fresh instance for its own lifetime,
    mirroring the registry's install/uninstall pattern exactly."""
    from audiagentic.components.agents.gateway import api as gateway_api
    from audiagentic.components.agents.gateway.queue import queue as queue_mod

    manager = queue_mod.GatewayQueueManager()
    gateway_api.set_queue_manager(manager)
    return manager


def _uninstall_gateway_queue_manager(_manager: Any) -> None:
    """Reset to a fresh manager on shutdown so no in-memory queue state
    leaks into whatever uses the module-level default next (e.g. tests
    importing gateway.api directly, outside a composed process)."""
    from audiagentic.components.agents.gateway import api as gateway_api
    from audiagentic.components.agents.gateway.queue import queue as queue_mod

    gateway_api.set_queue_manager(queue_mod.GatewayQueueManager())


def _build_gpt_auto_runtime_owner() -> object:
    """Declare the gateway process as the lifetime owner of shared GPT CDP."""
    return object()


def _shutdown_gpt_auto_runtimes(_owner: object) -> None:
    """Run async provider teardown from this synchronous composition hook."""
    from audiagentic.components.providers.adapters.gpt_auto.runtime_registry import (
        shutdown_all_runtimes,
    )

    failure: list[BaseException] = []

    def run() -> None:
        try:
            asyncio.run(shutdown_all_runtimes())
        except BaseException as exc:  # finalizer logging owns reporting
            failure.append(exc)

    thread = threading.Thread(target=run, name="gateway-gpt-auto-shutdown")
    thread.start()
    thread.join()
    if failure:
        raise failure[0]


def _build_session_runtime_owner() -> object:
    """Declare the gateway SessionRuntime as a process-owned dependency."""
    return object()


def _shutdown_session_runtime(_owner: object) -> None:
    from audiagentic.components.agents.gateway.session.sessions import (
        peek_session_runtime,
        reset_session_runtime,
    )

    runtime = peek_session_runtime()
    if runtime is not None:
        from audiagentic.components.providers.adapters.gpt_auto.runtime_registry import (
            shutdown_all_runtimes,
        )

        runtime.shutdown(before_loop_stop=shutdown_all_runtimes)
        reset_session_runtime()


def builtin_contributions() -> tuple[ServiceContribution, ...]:
    """Every implementation this process can be configured to use."""
    return (
        ServiceContribution(
            service_id=EXECUTION_PROFILE_REGISTRY,
            implementation_id=ImplementationId("agents.shared-gateway-registry"),
            factory=_build_shared_gateway_registry_factory(),
            finalizer=_uninstall_shared_gateway_registry,
        ),
        ServiceContribution(
            service_id=QUEUE_MANAGER,
            implementation_id=ImplementationId("agents.gateway-queue-manager"),
            factory=_build_gateway_queue_manager,
            finalizer=_uninstall_gateway_queue_manager,
        ),
        ServiceContribution(
            service_id=GPT_AUTO_RUNTIME_OWNER,
            implementation_id=ImplementationId("providers.shared-gpt-auto-runtime"),
            factory=_build_gpt_auto_runtime_owner,
            finalizer=_shutdown_gpt_auto_runtimes,
        ),
        ServiceContribution(
            service_id=SESSION_RUNTIME_OWNER,
            implementation_id=ImplementationId("agents.gateway-session-runtime"),
            factory=_build_session_runtime_owner,
            finalizer=_shutdown_session_runtime,
        ),
    )


def build_gateway_service_graph(
    *,
    config: CompositionConfig | None = None,
    overrides: dict[ServiceId, Any] | None = None,
) -> BuiltGraph:
    """Build the gateway-service process graph.

    `config` and `overrides` exist so tests can compose a graph without
    touching the packaged YAML or the real registry; production passes
    neither.
    """
    resolved_config = config or load_composition_config(
        pkg_default_path=_pkg_default_path(),
        namespace=CONFIG_NAMESPACE,
    )
    return build_graph(
        builtin_contributions(),
        resolved_config,
        overrides=overrides,
    )
