"""Provider-owned implementation behind the public one-shot execution seam."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.provider_execution import (
    ProviderAcpLaunchResult,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    ProviderIsolationTier,
)
from audiagentic.components.providers.contracts.session_surface import SurfaceHint
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_surface import (
    PreparedSessionTransport,
    SessionSurfaceRef,
    SurfaceValidationState,
)


def get_provider_execution_isolation_tier(provider_id: str) -> ProviderIsolationTier:
    """Return the descriptor-backed provider-wide execution isolation fact."""
    from audiagentic.components.providers.descriptors.registry import get_descriptor

    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        raise AudiaGenticError(
            code="RES-PEXE-001",
            kind="providers",
            message="provider descriptor is required for execution",
            details={"provider-id": provider_id},
        )
    return descriptor.execution_isolation_tier


def get_provider_runtime_config_state(
    project_root: Path,
    provider_id: str,
) -> dict[str, Any]:
    """Return the provider-owned state that affects one provider runtime.

    This query is intentionally provider-scoped: gateway fingerprinting does
    not need unrelated provider configuration and must not read provider
    internals directly.
    """
    from ..config.provider_config import (
        is_provider_enabled,
        load_provider_config,
    )

    document = load_provider_config(project_root)
    configured = (document.get("providers") or {}).get(provider_id, {})
    return {
        "provider-id": provider_id,
        "enabled": is_provider_enabled(project_root, provider_id),
        "config": dict(configured) if isinstance(configured, dict) else configured,
    }


def execute_provider_turn(request: ProviderExecutionRequest) -> ProviderExecutionResult:
    """Resolve and execute one provider turn inside its assigned worker."""
    from ..catalog.models import resolve_model_selection
    from .execution import execute_provider

    runtime = get_provider_runtime_config_state(request.project_root, request.provider_id)
    if not runtime["enabled"]:
        raise AudiaGenticError(
            code="CFG-PEXE-001",
            kind="providers",
            message="provider is disabled for execution",
            details={"provider-id": request.provider_id},
        )

    declared_tier = get_provider_execution_isolation_tier(request.provider_id)
    if declared_tier != request.provider_isolation_tier:
        raise AudiaGenticError(
            code="CON-PEXE-001",
            kind="providers",
            message="provider execution isolation tier does not match descriptor",
            details={
                "provider-id": request.provider_id,
                "requested": request.provider_isolation_tier,
                "declared": declared_tier,
            },
        )

    provider_config = runtime["config"]
    if not isinstance(provider_config, dict):
        provider_config = {}
    model = resolve_model_selection(
        provider_id=request.provider_id,
        provider_config=provider_config,
        job_request={
            "model-id": request.model_id,
            "model-alias": request.model_alias,
        },
    )
    model_id = str(model["model-id"])
    packet_data = dict(request.packet_data)
    packet_data.update(
        {
            "working-root": str(request.project_root),
            "provider-id": request.provider_id,
            "model-id": model_id,
            "model-alias": request.model_alias,
        }
    )
    result = execute_provider(
        provider_id=request.provider_id,
        packet_ctx=packet_data,
        provider_cfg=provider_config,
    )
    return ProviderExecutionResult(
        provider_id=request.provider_id,
        model_id=str(result.get("model") or model_id),
        worker_id=request.worker_id,
        attempt_epoch=request.attempt_epoch,
        result_data=result,
    )


def prepare_provider_execution_environment(
    request: ProviderExecutionRequest,
) -> dict[str, str]:
    """Materialize transient provider-owned environment before HOME isolation."""
    import os

    from ..catalog.models import resolve_model_selection
    from .execution import (
        load_execution_environment_builder,
    )

    runtime = get_provider_runtime_config_state(request.project_root, request.provider_id)
    provider_config = runtime["config"] if isinstance(runtime["config"], dict) else {}
    model = resolve_model_selection(
        provider_id=request.provider_id,
        provider_config=provider_config,
        job_request={"model-id": request.model_id, "model-alias": request.model_alias},
    )
    builder = load_execution_environment_builder(request.provider_id)
    if builder is None:
        return {}

    # Ensure the builder reads from the project-level config that contains
    # custom providers applied by model_source_add/apply_model_sources, not
    # the global ~/.config/opencode/opencode.json which lacks them.
    # Also clear any pre-existing OPENCODE_CONFIG_CONTENT so the builder
    # doesn't short-circuit on a stale inline document.
    project_config = request.project_root / ".opencode" / "opencode.json"
    prev_open_code_config = os.environ.get("OPENCODE_CONFIG")
    prev_open_code_content = os.environ.get("OPENCODE_CONFIG_CONTENT")
    if project_config.is_file():
        os.environ["OPENCODE_CONFIG"] = str(project_config)
        os.environ.pop("OPENCODE_CONFIG_CONTENT", None)
    try:
        result = builder(model_id=str(model["model-id"]))
    finally:
        if prev_open_code_config is not None:
            os.environ["OPENCODE_CONFIG"] = prev_open_code_config
        elif "OPENCODE_CONFIG" in os.environ:
            del os.environ["OPENCODE_CONFIG"]
        if prev_open_code_content is not None:
            os.environ["OPENCODE_CONFIG_CONTENT"] = prev_open_code_content

    if not isinstance(result, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in result.items()
    ):
        raise AudiaGenticError(
            code="INT-PEXE-003",
            kind="providers",
            message="provider execution environment builder returned an invalid mapping",
        )
    return result


def prepare_provider_acp_launch(
    project_root: Path,
    *,
    provider_id: str,
    model_id: str | None,
    model_alias: str | None,
    request_runtime_root: Path | None = None,
    mcp_entries=None,
    require_isolated_mcp: bool = False,
) -> ProviderAcpLaunchResult:
    """Resolve one provider-owned ACP launch without exposing adapter internals."""
    from ..catalog.models import resolve_model_selection
    from .execution import load_acp_launch_builder

    runtime = get_provider_runtime_config_state(project_root, provider_id)
    if not runtime["enabled"]:
        raise AudiaGenticError(
            code="CFG-PEXE-001",
            kind="providers",
            message="provider is disabled for execution",
            details={"provider-id": provider_id},
        )
    builder = load_acp_launch_builder(provider_id)
    if builder is None:
        raise AudiaGenticError(
            code="UNS-PEXE-002",
            kind="providers",
            message="provider does not support ACP live sessions",
            details={"provider-id": provider_id},
        )
    provider_config = runtime["config"]
    if not isinstance(provider_config, dict):
        provider_config = {}
    model = resolve_model_selection(
        provider_id=provider_id,
        provider_config=provider_config,
        job_request={"model-id": model_id, "model-alias": model_alias},
    )
    resolved_model_id = str(model.get("model-id") or model.get("resolved") or "")
    if not resolved_model_id:
        raise AudiaGenticError(
            code="INT-PEXE-001",
            kind="providers",
            message="provider ACP launch did not resolve a model identifier",
            details={"provider-id": provider_id},
        )
    launch_kwargs = {"model_id": resolved_model_id}
    if request_runtime_root is not None:
        launch_kwargs["request_runtime_root"] = request_runtime_root
    if mcp_entries is not None:
        surface = prepare_provider_mcp_surface(
            project_root,
            provider_id=provider_id,
            entries=tuple(mcp_entries),
            runtime_root=request_runtime_root,
            require_exact_isolation=require_isolated_mcp,
        )
        launch_kwargs["mcp_surface"] = surface
    return ProviderAcpLaunchResult(
        provider_id=provider_id,
        model_id=resolved_model_id,
        launch=builder(project_root, **launch_kwargs),
    )


def prepare_interactive_provider_launch(
    project_root: Path,
    *,
    provider_id: str,
    provider: str,
    model: str,
    agent_runtime: Path,
    mcp_surface=None,
    runner_params=None,
    smoke: bool = False,
):
    """Resolve one provider-owned interactive (TUI) launch.

    Unlike ACP/one-shot execution, the caller (runtime harness bootstrap)
    already resolved provider/model from AUDiaGentic's own embedded rig
    config before calling this -- there is no model-selection step here.
    """
    from .execution import (
        load_interactive_launch_builder,
    )

    builder = load_interactive_launch_builder(provider_id)
    if builder is None:
        raise AudiaGenticError(
            code="UNS-PEXE-005",
            kind="providers",
            message="provider does not support interactive CLI launch",
            details={"provider-id": provider_id},
        )
    return builder(
        project_root,
        provider=provider,
        model=model,
        agent_runtime=agent_runtime,
        mcp_surface=mcp_surface,
        runner_params=runner_params,
        smoke=smoke,
    )


def translate_interactive_runner_args(provider_id: str, runner_params: object) -> list[str]:
    """Translate generic runner parameters through one provider's launch API."""
    from .execution import _adapter_hook

    translator = _adapter_hook(provider_id, "interactive", "translate_runner_args")
    if translator is not None:
        return list(translator(runner_params))
    from audiagentic.components.providers.adapters.recipe_launch import (
        translate_recipe_runner_args,
    )

    return translate_recipe_runner_args(provider_id, runner_params)


def prepare_provider_mcp_surface(
    project_root: Path,
    *,
    provider_id: str,
    entries,
    runtime_root: Path | None = None,
    require_exact_isolation: bool = False,
):
    """Ask one provider to build an AUDiaGentic-curated MCP launch surface.

    Soft-fails rather than raising when the provider has no launch-surface
    mechanism (``McpLaunchSurfaceResult(supported=False)``) — the caller
    decides whether to proceed additively or fall back to a different
    provider, matching ``ManagedMcpResult``'s ``supported`` convention rather
    than ``prepare_provider_acp_launch``'s hard failure.
    """
    from audiagentic.components.providers.contracts.mcp_launch_surface import (
        McpLaunchSurfaceRequest,
        McpLaunchSurfaceResult,
    )
    from audiagentic.components.providers.descriptors.registry import get_descriptor

    from .execution import load_mcp_surface_builder

    descriptor = get_descriptor(provider_id)
    declared_isolation = descriptor.mcp_launch_isolation_tier if descriptor is not None else "unsupported"
    if require_exact_isolation and declared_isolation != "exact":
        raise AudiaGenticError(
            code="UNS-PEXE-004",
            kind="providers",
            message="provider does not declare exact MCP launch isolation",
            details={"provider-id": provider_id, "declared-isolation": declared_isolation},
        )
    builder = load_mcp_surface_builder(provider_id)
    if builder is None:
        return McpLaunchSurfaceResult(ok=True, supported=False)
    request = McpLaunchSurfaceRequest(
        project_root=str(project_root),
        runtime_root=str(runtime_root) if runtime_root is not None else None,
        entries=tuple(entries),
    )
    result = builder(request)
    if require_exact_isolation and (
        not result.ok or not result.supported or result.applied_isolation != "exact"
    ):
        raise AudiaGenticError(
            code="UNS-PEXE-004",
            kind="providers",
            message="provider cannot guarantee the required isolated MCP launch surface",
            details={
                "provider-id": provider_id,
                "supported": result.supported,
                "declared-isolation": declared_isolation,
                "applied-isolation": result.applied_isolation,
                "mechanism": result.mechanism,
            },
        )
    return result


def collect_management_mcp_launch_entries(project_root: Path):
    """Translate the management projection into the provider launch contract.

    Projection policy remains foundation-owned.  This provider service owns the
    one shared translation into :class:`McpLaunchServerEntry`, preventing every
    runtime/product consumer from rebuilding the same boundary mapping.
    """
    from audiagentic.components.providers.contracts.mcp_launch_surface import (
        McpLaunchServerEntry,
    )
    from audiagentic.foundation.mcp.projection import (
        collect_component_mcp_entries,
    )

    collected = collect_component_mcp_entries(
        project_root,
        propagation_target="audiagentic",
        require_enabled=False,
    )
    return tuple(
        McpLaunchServerEntry(
            name=name,
            command=entry.command,
            args=entry.args,
            env=tuple(sorted(entry.env.items())),
        )
        for name, entry in collected.items()
        if entry.command
    )


def prepare_projected_provider_mcp_surface(
    project_root: Path,
    *,
    provider_id: str,
    runtime_root: Path | None,
    require_exact_isolation: bool = False,
):
    """Collect and prepare the standard component projection for one launch."""
    return prepare_provider_mcp_surface(
        project_root,
        provider_id=provider_id,
        entries=collect_management_mcp_launch_entries(project_root),
        runtime_root=runtime_root,
        require_exact_isolation=require_exact_isolation,
    )


def get_pi_coding_agent_package_dir() -> Path | None:
    """The system-installed pi-coding-agent package dir, or None.

    Narrow, single-consumer seam: pi's runtime-orchestration install path
    reads bundled theme assets from the same system install the CLI resolves
    to. Provider-owned (pi's own system-resolution knowledge) so runtime
    orchestration never re-implements or reaches into the adapter directly.
    """
    from audiagentic.components.providers.adapters.pi.system import (
        resolve_system_pi_coding_agent,
    )

    return resolve_system_pi_coding_agent()


def _build_transport_from_launch(
    project_root: Path,
    launch: Any,
) -> Any:
    """Wrap an AcpLaunch in the private AcpAgentSessionTransport adapter.

    Returns a neutral :class:`AcpAgentSessionTransport` instance — no process is
    launched at this stage. The caller must call ``open()`` to start the child.

    This is provider-side factory composition: it uses the private
    :class:`AcpAgentSessionTransport` wrapper that maps ACP frames to bounded
    :class:`TransportObservation` values.

    Args:
        project_root: Working directory for the agent child process.
        launch: An :class:`AcpLaunch` instance from the provider adapter's
            ``build_acp_launch`` function.

    Returns:
        An :class:`AcpAgentSessionTransport` (implements ``AgentSessionTransport``).
    """
    from audiagentic.foundation.transports.acp import AcpAgentSessionTransport

    return AcpAgentSessionTransport(
        launch,
        cwd=project_root,
    )


def prepare_provider_session_transport(
    project_root: Path,
    *,
    provider_id: str,
    surface_hint: SurfaceHint,
    model_id: str | None = None,
    model_alias: str | None = None,
    request_runtime_root: Path | None = None,
    mcp_entries=None,
    require_isolated_mcp: bool = False,
) -> PreparedSessionTransport:
    """Resolve a session-surface snapshot and build the transport factory.

    Resolves the AS29 surface exactly once, then wires provider-local factory
    composition for supported ACP surfaces. Returns a typed
    :class:`PreparedSessionTransport` carrying:

    - ``surface`` — the same frozen :class:`ResolvedSessionSurface` snapshot.
    - ``effective_provider_ref`` — the resolved :class:`SessionSurfaceRef`.
    - ``transport`` — an :class:`AcpAgentSessionTransport` (implements
      :class:`AgentSessionTransport`) for supported ACP surfaces, or ``None``
      when the surface is unsupported.

    **Unsupported-surface contract:** any failure path — disabled provider,
    missing/invalid factory, version/platform mismatch, unvalidated high-level,
    blocked declaration — returns the unsupported snapshot with
    ``transport=None``. No process is ever launched and no fallback to another
    surface occurs.

    Adapter refs are resolved provider-side only (existence check) and never
    returned in the snapshot or transport.

    Args:
        project_root: Explicit project root for provider enablement checks.
        provider_id: Canonical provider identifier.
        surface_hint: Typed request carrying surface id and optional
            version/platform hints.
        model_id: Optional model id for launch preparation.
        model_alias: Optional model alias for launch preparation.
        request_runtime_root: Optional runtime root for provider-local
            environment setup (e.g. Pi session dirs).

    Returns:
        A frozen :class:`PreparedSessionTransport` instance.
    """
    from ..session.session_surface_resolution import (
        resolve_session_surface,
    )

    # ── Resolve the surface exactly once (AS29 resolver) ──────────────
    surface = resolve_session_surface(project_root, provider_id, surface_hint)

    effective_ref = SessionSurfaceRef(
        provider_id=provider_id,
        surface_id=surface_hint.surface_id,
        resolved_version=surface.ref.resolved_version,
    )

    # ── Unsupported: return with transport=None (never launch) ─────────
    if surface.validation.state == SurfaceValidationState.UNSUPPORTED:
        return PreparedSessionTransport(
            transport=None,
            surface=surface,
            effective_provider_ref=effective_ref,
        )

    # ── Supported ACP surface: wire provider-local factory composition ──
    from audiagentic.foundation.transports.acp import AcpLaunch

    from ..catalog.models import resolve_model_selection
    from .execution import (
        load_acp_launch_builder,
    )

    builder = load_acp_launch_builder(provider_id)
    if builder is None:
        # No factory — return unsupported snapshot with transport=None.
        # The surface was declared supported but the factory is missing at
        # runtime (possible if adapter module was removed or renamed).
        unsupported_surface = surface  # reuse same snapshot
        return PreparedSessionTransport(
            transport=None,
            surface=unsupported_surface,
            effective_provider_ref=effective_ref,
        )

    # Resolve the model for launch preparation.
    runtime = get_provider_runtime_config_state(project_root, provider_id)
    provider_config = runtime["config"]
    if not isinstance(provider_config, dict):
        provider_config = {}
    model = resolve_model_selection(
        provider_id=provider_id,
        provider_config=provider_config,
        job_request={"model-id": model_id, "model-alias": model_alias},
    )
    resolved_model_id = str(model.get("model-id") or model.get("resolved") or "")
    if not resolved_model_id:
        # Could not resolve a model — return unsupported snapshot.
        return PreparedSessionTransport(
            transport=None,
            surface=surface,
            effective_provider_ref=effective_ref,
        )

    # Build the ACP launch via the provider adapter's build_acp_launch.
    launch_kwargs: dict[str, Any] = {"model_id": resolved_model_id}
    if request_runtime_root is not None:
        launch_kwargs["request_runtime_root"] = request_runtime_root
    if mcp_entries is not None:
        surface = prepare_provider_mcp_surface(
            project_root,
            provider_id=provider_id,
            entries=tuple(mcp_entries),
            runtime_root=request_runtime_root,
            require_exact_isolation=require_isolated_mcp,
        )
        launch_kwargs["mcp_surface"] = surface
    try:
        acp_launch = builder(project_root, **launch_kwargs)
    except Exception:
        # Factory error — return unsupported snapshot with transport=None.
        return PreparedSessionTransport(
            transport=None,
            surface=surface,
            effective_provider_ref=effective_ref,
        )

    if not isinstance(acp_launch, AcpLaunch):
        # Neutral protocol violation — the factory must return an AcpLaunch.
        return PreparedSessionTransport(
            transport=None,
            surface=surface,
            effective_provider_ref=effective_ref,
        )

    # Wrap in private AcpAgentSessionTransport (AS28 slice 2 adapter).
    transport = _build_transport_from_launch(project_root, acp_launch)

    return PreparedSessionTransport(
        transport=transport,
        surface=surface,
        effective_provider_ref=effective_ref,
    )


__all__ = [
    "execute_provider_turn",
    "get_provider_execution_isolation_tier",
    "get_provider_runtime_config_state",
    "prepare_provider_execution_environment",
    "prepare_provider_acp_launch",
    "prepare_provider_session_transport",
]
