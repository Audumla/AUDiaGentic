"""AS19 Stage-2 Slice A: transport-observation-only status observer resolver.

Recipe A path (declared transport-observation, e.g. OpenCode ACP): pure in-process
wiring with no network, no config writes, no Docker. AS28 already delivers neutral
TransportObservation values in-process, and the generic normalizer
(normalize_harness_status_observation) already exists in providers/contracts/harness_status_observer.py.

This slice does NOT add: HTTP ingress server, managed-hook/plugin entries, lifecycle
reconciler, or a harness-status-observers.json registry — those belong to future slices.
"""

from __future__ import annotations

import secrets

from audiagentic.components.providers.contracts.harness_status_observer import (
    normalize_harness_status_observation,
)
from audiagentic.foundation.transports.harness_status_observer import (
    StatusObserverLease,
    StatusObserverRequest,
    StatusObserverResult,
    StatusObserverState,
)

# Slice A: the only currently-declared Recipe-A surface. Do not pre-populate
# future surfaces here — each addition requires its own probe per AS27.
# Conformance: use the AS27 inventory to derive the eligible set.
from audiagentic.components.providers.services.harness_observability_inventory import (
    get_harness_surface_capability_fact,
)

# No static eligible-surface set — platform eligibility is checked at
# resolution time. A surface whose platform_evidence lists specific platforms
# is eligible only on those platforms, so the check requires runtime platform
# context. use is_eligible_transport_observation_publisher with platform
# parameter instead.


def resolve_transport_observation_lease(
    request: StatusObserverRequest,
    *,
    agents_enabled: bool,
    provider_enabled: bool,
    platform: str | None = None,
) -> StatusObserverResult:
    """Resolve a transport-observation (Recipe A) status observer lease.

    Validates that the agents component is enabled, the provider is enabled and
    registered, and the requested surface_id matches a known Recipe-A surface
    **on the target platform**. A surface whose platform_evidence lists specific
    platforms returns UNSUPPORTED on platforms not listed. Any mismatch returns
    UNSUPPORTED — never guesses a similarly named surface.

    Args:
        request: The observer request with project/provider/surface/session context.
        agents_enabled: Whether the agents component is enabled.
        provider_enabled: Whether the target provider is enabled.
        platform: Target platform triple (e.g. "linux-amd64"). Defaults to
            auto-detected platform. Inject for deterministic tests.

    Returns:
        A StatusObserverResult with a ready lease on success, or an UNSUPPORTED
        result on validation failure.
    """
    # Validate prerequisites: both agents and provider must be enabled.
    if not agents_enabled or not provider_enabled:
        return StatusObserverResult(
            ok=False,
            supported=False,
            state=StatusObserverState.UNSUPPORTED,
            error_code="UNS-PROV-OBS-001",
        )

    # Validate surface + platform: the surface must be eligible on this
    # platform. A surface with non-empty platform_evidence is NOT eligible
    # on platforms not listed; empty platform_evidence means no restriction.
    from audiagentic.components.providers.services.harness_observability_inventory import (
        is_eligible_transport_observation_publisher,
    )

    if not is_eligible_transport_observation_publisher(
        request.provider_id, request.surface_id, platform=platform,
    ):
        return StatusObserverResult(
            ok=False,
            supported=False,
            state=StatusObserverState.UNSUPPORTED,
            error_code="UNS-PROV-OBS-002",
        )

    # Build binding ID using the existing pattern (obsbnd_<hex>) used by
    # agents_harness_status_observer_ingress._generate_binding_id.
    binding_id = f"obsbnd_{secrets.token_hex(12)}"

    # Closure for observe_transport: delegates to the generic normalizer.
    # The lease is captured at call time (not definition time), so this
    # forward reference is safe in Python.
    def _observe(observation):
        return normalize_harness_status_observation(lease, observation)

    lease = StatusObserverLease(
        binding_id=binding_id,
        observe_transport=_observe,
    )

    return StatusObserverResult(
        ok=True,
        supported=True,
        state=StatusObserverState.READY,
        binding_id=binding_id,
        launch_environment={},
        managed_ids=[],
    )
