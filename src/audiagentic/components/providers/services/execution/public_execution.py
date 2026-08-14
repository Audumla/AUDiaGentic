"""Provider-owned implementation behind the public one-shot execution seam."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.mcp_launch_surface import (
    McpLaunchIsolationTier,
)
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
)

logger = logging.getLogger(__name__)

#: Preparation failed with an exception that was not a classified
#: :class:`AudiaGenticError` — the builder raised something unmodelled.
_UNCLASSIFIED_BUILDER_FAILURE = "EXT-PROVEXEC-901"

#: The builder returned a non-``AcpLaunch`` value, violating its own contract.
_BUILDER_CONTRACT_VIOLATION = "EXT-PROVEXEC-902"


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


def get_provider_mcp_launch_isolation_tier(provider_id: str) -> McpLaunchIsolationTier:
    """Return the descriptor-backed provider-wide MCP launch isolation fact.

    An inherent harness fact (what MCP servers a launch can be scoped to see),
    not mutable feature state — mirrors get_provider_execution_isolation_tier
    exactly, so a caller can discover the tier without going through
    prepare_provider_mcp_surface's full launch-preparation path.
    """
    from audiagentic.components.providers.descriptors.registry import get_descriptor

    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        raise AudiaGenticError(
            code="RES-PEXE-001",
            kind="providers",
            message="provider descriptor is required for execution",
            details={"provider-id": provider_id},
        )
    return descriptor.mcp_launch_isolation_tier


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
        isinstance(name, str) and isinstance(value, str) for name, value in result.items()
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
    import inspect

    if "provider_config" in inspect.signature(builder).parameters:
        launch_kwargs["provider_config"] = provider_config
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
    runtime = get_provider_runtime_config_state(project_root, provider_id)
    provider_config = runtime["config"] if isinstance(runtime["config"], dict) else {}
    import inspect

    builder_kwargs = {
        "provider": provider,
        "model": model,
        "agent_runtime": agent_runtime,
        "mcp_surface": mcp_surface,
        "runner_params": runner_params,
        "smoke": smoke,
    }
    if "provider_config" in inspect.signature(builder).parameters:
        builder_kwargs["provider_config"] = provider_config
    return builder(
        project_root,
        **builder_kwargs,
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
    declared_isolation = (
        descriptor.mcp_launch_isolation_tier if descriptor is not None else "unsupported"
    )
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


def _observability_hook_factories() -> dict[str, Any]:
    """AS41: provider_id -> zero-arg PreSpawnHook factory, for providers with
    a real, concrete observability-enrichment implementation. Deliberately a
    plain dict, not a plugin registry — one entry today (Pi's RPC tap); add
    entries only when a provider has a real implementation, never placeholders.
    Called lazily (from inside prepare_provider_session_transport, never at
    module import time) so this generic module never unconditionally imports
    a specific provider adapter.
    """
    from audiagentic.components.providers.adapters.pi.rpc_tap_evidence import (
        PiRpcTapPreSpawnHook,
    )

    return {"pi": PiRpcTapPreSpawnHook}


def _runtime_preserve_relpaths_registry() -> dict[str, tuple[str, ...]]:
    """provider_id -> runtime-root-relative paths holding the provider's own
    durable session state, for providers that write local, resumable state
    into the per-request isolated runtime root. Deliberately a plain dict
    (same shape as _observability_hook_factories), not a plugin registry --
    add entries only once a provider's actual on-disk layout is confirmed
    (see pi/acp.py's _request_environment for pi's isolation layout).
    Empty/absent means "nothing to preserve", not "no resume support" --
    e.g. gpt-auto's session lives in the browser, never on local disk, so it
    has no entry here despite supporting resume-by-ref.
    """
    return {"pi": ("pi/agent/sessions",)}


def _build_transport_from_launch(
    project_root: Path,
    launch: Any,
    *,
    ag_session_id: str,
    resume_provider_ref: str | None = None,
    pre_spawn_hook: Any = None,
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
        resume_provider_ref: AS49 — when set, the transport's ``open()`` loads
            this exact existing provider session (ACP ``session/load``)
            instead of opening a new one. Callers are responsible for having
            already verified the resolved surface declares
            ``resume-by-ref: supported`` before setting this.
        pre_spawn_hook: AS41 — when set, forwarded unchanged to the transport
            (see ``foundation.transports.acp.PreSpawnHook``).

    Returns:
        An :class:`AcpAgentSessionTransport` (implements ``AgentSessionTransport``).
    """
    from audiagentic.foundation.transports.acp import AcpAgentSessionTransport

    return AcpAgentSessionTransport(
        launch,
        cwd=project_root,
        ag_session_id=ag_session_id,
        resume_provider_ref=resume_provider_ref,
        pre_spawn_hook=pre_spawn_hook,
    )


def prepare_provider_session_transport(
    project_root: Path,
    *,
    provider_id: str,
    ag_session_id: str,
    binding_sink: Any,
    surface_hint: SurfaceHint,
    model_id: str | None = None,
    model_alias: str | None = None,
    request_runtime_root: Path | None = None,
    mcp_entries=None,
    require_isolated_mcp: bool = False,
    resume_provider_ref: str | None = None,
    enable_observability_tap: bool = False,
    resume_provider_metadata: dict[str, Any] | None = None,
    checkpoint_sink: Any | None = None,
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
        resume_provider_ref: AS49 — when set, forwarded to the built
            transport so ``open()`` resumes this exact provider session
            (ACP ``session/load``) instead of opening a new one. The caller
            must independently verify the resolved surface declares
            ``resume-by-ref: supported`` — this function does not check it.
        enable_observability_tap: AS41 — when set (and the resolved
            provider's builder declares ``enable_rpc_tap``, currently Pi
            only), attaches a provider-local enrichment hook to the built
            transport. Best-effort: if the provider has no such capability,
            this is silently a no-op — never a supported-vs-unsupported
            distinction, since observability enrichment is never load-bearing.

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
    if not surface.validation.evidence.validated:
        return PreparedSessionTransport(
            transport=None,
            surface=surface,
            effective_provider_ref=effective_ref,
        )

    # ── Supported CDP surface (gpt-auto): build the CDP transport ─────
    # gpt-auto has no ACP launch builder. Its thin transport resolves a shared
    # provider runtime plus one PersistentChat through the same neutral
    # AgentSessionTransport seam — no browser type crosses this boundary.
    if provider_id == "gpt-auto" and surface_hint.surface_id == "gpt-auto-cdp":
        from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
            build_gpt_auto_session_transport,
        )

        runtime = get_provider_runtime_config_state(project_root, provider_id)
        provider_config = runtime["config"]
        if not isinstance(provider_config, dict):
            provider_config = {}
        transport = build_gpt_auto_session_transport(
            project_root,
            config=provider_config,
            ag_session_id=ag_session_id,
            binding_sink=binding_sink,
            resume_provider_ref=resume_provider_ref,
            resume_metadata_hint=resume_provider_metadata,
            checkpoint_sink=checkpoint_sink,
        )
        return PreparedSessionTransport(
            transport=transport,
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
    import inspect

    if "provider_config" in inspect.signature(builder).parameters:
        launch_kwargs["provider_config"] = provider_config
    if request_runtime_root is not None:
        launch_kwargs["request_runtime_root"] = request_runtime_root
    # AS41: only Pi's build_acp_launch declares enable_rpc_tap today — no
    # generalized per-provider observability-hook registry exists yet, so
    # this checks the concrete builder's own signature rather than assuming
    # every ACP provider understands the kwarg (most don't). Also requires
    # request_runtime_root, matching build_acp_launch's own precondition.
    if enable_observability_tap and request_runtime_root is not None:
        import inspect

        if "enable_rpc_tap" in inspect.signature(builder).parameters:
            launch_kwargs["enable_rpc_tap"] = True
    if mcp_entries is not None:
        mcp_launch_surface = prepare_provider_mcp_surface(
            project_root,
            provider_id=provider_id,
            entries=tuple(mcp_entries),
            runtime_root=request_runtime_root,
            require_exact_isolation=require_isolated_mcp,
        )
        launch_kwargs["mcp_surface"] = mcp_launch_surface
    try:
        acp_launch = builder(project_root, **launch_kwargs)
    except AudiaGenticError as exc:
        # Classified failure — the builder already said exactly what is wrong.
        # Carry the classification to the caller and log the structured
        # details, which may contain paths and so must not ride on the
        # snapshot.
        logger.warning(
            "provider %s session-transport preparation failed: %s (%s) details=%s",
            provider_id,
            exc.message,
            exc.code,
            exc.details,
        )
        return PreparedSessionTransport(
            transport=None,
            surface=surface,
            effective_provider_ref=effective_ref,
            unavailable_code=exc.code,
            unavailable_message=exc.message,
        )
    except Exception as exc:
        # Unclassified factory error — still degraded state, but nobody
        # modelled this one. Log with a traceback so it can be classified.
        logger.warning(
            "provider %s session-transport preparation raised an unclassified error",
            provider_id,
            exc_info=True,
        )
        return PreparedSessionTransport(
            transport=None,
            surface=surface,
            effective_provider_ref=effective_ref,
            unavailable_code=_UNCLASSIFIED_BUILDER_FAILURE,
            unavailable_message=f"{type(exc).__name__}: {exc}",
        )

    if not isinstance(acp_launch, AcpLaunch):
        # Neutral protocol violation — the factory must return an AcpLaunch.
        logger.warning(
            "provider %s launch builder returned %s, expected AcpLaunch",
            provider_id,
            type(acp_launch).__name__,
        )
        return PreparedSessionTransport(
            transport=None,
            surface=surface,
            effective_provider_ref=effective_ref,
            unavailable_code=_BUILDER_CONTRACT_VIOLATION,
            unavailable_message=(
                f"launch builder returned {type(acp_launch).__name__}, expected AcpLaunch"
            ),
        )

    # AS41: attach a provider-local observability enrichment hook, only when
    # both the caller asked for one AND the builder actually declared
    # enable_rpc_tap above (so this dict only ever needs an entry for
    # providers with a real hook implementation — no placeholder entries).
    pre_spawn_hook = None
    if "enable_rpc_tap" in launch_kwargs:
        hook_factory = _observability_hook_factories().get(provider_id)
        if hook_factory is not None:
            pre_spawn_hook = hook_factory()

    # Wrap in private AcpAgentSessionTransport (AS28 slice 2 adapter).
    transport = _build_transport_from_launch(
        project_root, acp_launch,
        ag_session_id=ag_session_id,
        resume_provider_ref=resume_provider_ref,
        pre_spawn_hook=pre_spawn_hook,
    )

    return PreparedSessionTransport(
        transport=transport,
        surface=surface,
        effective_provider_ref=effective_ref,
        runtime_preserve_relpaths=(
            _runtime_preserve_relpaths_registry().get(provider_id, ())
            if request_runtime_root is not None
            else ()
        ),
    )


__all__ = [
    "execute_provider_turn",
    "get_provider_execution_isolation_tier",
    "get_provider_runtime_config_state",
    "prepare_provider_execution_environment",
    "prepare_provider_acp_launch",
    "prepare_provider_session_transport",
]
