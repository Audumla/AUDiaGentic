"""AS27: harness observability inventory, capability-facts, and conformance.

Inventory/conformance slice — no new hooks or adapters.

This module defines the authoritative per-harness surface inventory:
declared capability, validation state, and effective production level for every
known agent-surface. OpenCode ACP (opencode-acp) is the only currently eligible
transport-observation publisher; all other surfaces are inventory-only with
probe-required / blocked / unsupported validation_state and O0 effective level.

Conformance rule: a lifecycle observation declaration may not claim
transport-observation publishability unless the surface is validated,
effective_level >= O1, and present in the Recipe-A eligible set.

CC53: the inventory data itself lives in each provider's own descriptor
(``config/providers/<id>.yaml``'s ``harness_observability:`` block), not a
central cross-provider Python dict or a central cross-provider config file
— per ARCHITECTURE_STANDARDS.md Section 2 ("Entity declarations belong in
configuration, not central Python lists" / "config and code for a provider
is isolated within its own folder"). ``descriptors/loader.py``'s
``_build_harness_observability`` validates each provider's own YAML shape;
this module aggregates across all loaded provider descriptors and owns the
domain conversion (evidence dict -> ValidationEvidence, lifecycle_source
string -> enum) plus the conformance/eligibility logic. Adding a new
provider surface is a config edit inside that provider's own file, not a
code change and not an edit to any other provider's file.

Error codes:
    VAL-HINV-001  — unsupported lifecycle source claimed as transport-observation publisher
    VAL-HINV-002  — non-validated surface claims effective level >= O1 for transport observation
    VAL-HINV-004  — a provider's harness_observability entry has an invalid 'evidence' field
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.transports.session_surface import (
    LifecycleSource,
    ValidationEvidence,
)

# ---------------------------------------------------------------------------
# Inventory value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HarnessSurfaceCapabilityFact:
    """A single harness-surface capability fact for the AS27 inventory.

    ``evidence`` replaces the former three-field triple
    (declared_capability, validation_state, effective_production_level) with
    a single ValidationEvidence(validated, reference).
    """

    # Provider + surface identity
    provider_id: str
    surface_id: str

    # Candidate source — what documentation or prior evidence points to
    candidate_source: str | None = None

    # Validation evidence — replaces the three-field triple (AS67)
    evidence: ValidationEvidence = field(default_factory=ValidationEvidence)

    # Recipe classification (A/B/C/D per AS27 spec)
    recipe: str = (
        "D"  # A=transport-observation, B=managed-hook, C=structured-output, D=unresolved/external
    )

    # Transport observation mechanism — only transport-observation is eligible
    # for AS19 publishing; others are inventory-only
    lifecycle_source: LifecycleSource = LifecycleSource.NONE

    # Supported canonical status enum values (only non-empty after validation)
    supported_statuses: frozenset[str] = field(default_factory=frozenset)

    # Named probe target — the test or Docker probe that must pass before promotion
    probe_anchor: str | None = None

    # Platform evidence summary (empty unless validated)
    platform_evidence: tuple[str, ...] = ()

    # Limitations / constraints
    limitations: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# The AS27 inventory — aggregated from each provider's own descriptor (CC53)
# ---------------------------------------------------------------------------


def _parse_entry(provider_id: str, entry: dict[str, Any]) -> HarnessSurfaceCapabilityFact:
    """Convert one already-shape-validated harness_observability entry
    (see descriptors/loader.py::_build_harness_observability) into a
    HarnessSurfaceCapabilityFact. ``surface_id``/``recipe``/status and
    evidence tuples are already validated/normalized by the loader; this
    function owns the domain conversion the loader deliberately leaves to
    this layer: evidence dict -> ValidationEvidence, lifecycle_source
    string -> enum."""
    surface_id = str(entry["surface_id"])

    evidence_raw = entry.get("evidence") or {}
    if not isinstance(evidence_raw, dict):
        raise make_error(
            prefix="VAL", component="HINV", number=4,
            kind="harness-observability-inventory-entry",
            message=f"inventory entry {provider_id}/{surface_id} has a non-mapping 'evidence' field",
            details={"provider_id": provider_id, "surface_id": surface_id},
        )
    evidence = ValidationEvidence(
        validated=bool(evidence_raw.get("validated", False)),
        reference=str(evidence_raw.get("reference", "") or ""),
    )

    return HarnessSurfaceCapabilityFact(
        provider_id=provider_id,
        surface_id=surface_id,
        candidate_source=entry.get("candidate_source"),
        evidence=evidence,
        recipe=str(entry.get("recipe", "D")),
        lifecycle_source=LifecycleSource(entry.get("lifecycle_source", LifecycleSource.NONE.value)),
        supported_statuses=frozenset(entry.get("supported_statuses") or ()),
        probe_anchor=entry.get("probe_anchor"),
        platform_evidence=tuple(entry.get("platform_evidence") or ()),
        limitations=tuple(entry.get("limitations") or ()),
    )


def _build_inventory() -> dict[tuple[str, str], HarnessSurfaceCapabilityFact]:
    """Aggregate the authoritative harness observability inventory across
    every provider's own descriptor.

    OpenCode ACP (opencode-acp) is the only validated transport-observation
    publisher. All other surfaces are inventory-only: probe-required/blocked/
    unsupported with O0 effective level.
    """
    from audiagentic.components.providers.descriptors.loader import (
        get_providers_config_dir,
        load_providers_from_directory,
    )

    providers = load_providers_from_directory(get_providers_config_dir())

    facts: dict[tuple[str, str], HarnessSurfaceCapabilityFact] = {}
    for provider_id, descriptor in providers.items():
        for entry in descriptor.harness_observability:
            fact = _parse_entry(provider_id, entry)
            # No cross-provider key collision is possible: surface_id
            # uniqueness within a provider is already enforced by
            # _build_harness_observability, and provider_id differs by
            # definition across descriptors.
            facts[(provider_id, fact.surface_id)] = fact
    return facts


# ---------------------------------------------------------------------------
# Public inventory API
# ---------------------------------------------------------------------------


def get_harness_surface_capability_fact(
    provider_id: str,
    surface_id: str,
) -> HarnessSurfaceCapabilityFact | None:
    """Look up a single harness surface capability fact from the inventory.

    Returns None when the (provider_id, surface_id) pair is not in the
    authoritative inventory — callers must treat unknown pairs as unsupported.
    """
    return _build_inventory().get((provider_id, surface_id))


def get_all_harness_surface_facts() -> dict[tuple[str, str], HarnessSurfaceCapabilityFact]:
    """Return the full inventory mapping."""
    return _build_inventory()


def is_eligible_transport_observation_publisher(
    provider_id: str,
    surface_id: str,
    *,
    platform: str | None = None,
) -> bool:
    """Check if a harness surface is eligible for transport-observation publishing.

    Only validated surfaces with evidence.validated=True and
    lifecycle_source == transport-observation are eligible. Additionally,
    if the surface records ``platform_evidence``, the current/requested
    platform must appear in that list — an empty ``platform_evidence``
    tuple means no platform restriction.

    Args:
        provider_id: Provider identifier.
        surface_id: Surface identifier.
        platform: Target platform triple (e.g. "linux-amd64"). Defaults to
            auto-detected platform. Inject for deterministic tests.

    Returns:
        True only if the surface passes the validation gate AND its
        platform_evidence includes the target platform (or is empty).
    """
    if platform is None:
        from audiagentic.runtime.system.platform import release_platform_name

        platform = release_platform_name()

    fact = get_harness_surface_capability_fact(provider_id, surface_id)
    if fact is None:
        return False
    # Gate 1: validation + lifecycle source (AS67 — no O0-O4 ladder)
    base_eligible = fact.evidence.validated and fact.lifecycle_source == LifecycleSource.TRANSPORT
    if not base_eligible:
        return False
    # Gate 2: platform must be in validated evidence (empty = no platform restriction)
    if fact.platform_evidence and platform not in fact.platform_evidence:
        return False
    return True


def list_eligible_transport_observation_surfaces(
    *,
    platform: str | None = None,
) -> list[tuple[str, str]]:
    """List all surfaces eligible for transport-observation publishing.

    Only validated surfaces with effective_production_level >= O1 and
    lifecycle_source == transport-observation on the target platform are
    included. An empty ``platform_evidence`` means no platform restriction;
    a non-empty list restricts eligibility to those platforms.

    Args:
        platform: Target platform triple (e.g. "linux-amd64"). Defaults to
            auto-detected platform. Inject for deterministic tests.

    Currently opencode-acp satisfies this gate on all its validated platforms
    (windows-amd64, darwin-arm64, darwin-amd64, linux-amd64); pi-community-acp
    satisfies it only on linux-amd64 — the sole platform with a real, proven
    prompt turn (the Windows real-binary proof only covers the session/new
    handshake, never a real prompt).
    """
    return [
        (fid, sid)
        for (fid, sid), fact in _build_inventory().items()
        if is_eligible_transport_observation_publisher(fid, sid, platform=platform)
    ]


# ---------------------------------------------------------------------------
# Conformance enforcement
# ---------------------------------------------------------------------------


def validate_harness_observability_conformance(
    provider_id: str,
    surface_id: str,
    lifecycle_source: LifecycleSource,
    *,
    validated: bool = False,
) -> None:
    """Enforce AS27 conformance for a harness observability declaration.

    A lifecycle observation declaration may NOT claim transport-observation
    publishability unless the surface is validated (evidence.validated=True)
    and present in the Recipe-A eligible set.

    Raises:
        AudiaGenticError (VAL-HINV-001): unsupported lifecycle source claimed
            as transport-observation publisher
        AudiaGenticError (VAL-HINV-002): non-validated surface claims
            transport observation publishing
        AudiaGenticError (VAL-HINV-003): no lifecycle source but evidence.validated
    """
    fact = get_harness_surface_capability_fact(provider_id, surface_id)

    # Unknown surface is always unsupported — no conformance violation,
    # it just cannot publish.
    if fact is None:
        return

    # Rule 1: only transport-observation lifecycle source may be a publisher
    if lifecycle_source == LifecycleSource.TRANSPORT and not fact.evidence.validated:
        raise make_error(
            prefix="VAL",
            component="HINV",
            number=1,
            kind="harness-observability-conformance",
            message=(
                f"unsupported lifecycle source '{lifecycle_source.value}' "
                f"claimed as transport-observation publisher for "
                f"{provider_id}/{surface_id}"
            ),
            details={
                "provider_id": provider_id,
                "surface_id": surface_id,
                "validated": fact.evidence.validated,
            },
        )

    # Rule 2: non-validated surfaces cannot claim transport observation publishing
    if lifecycle_source == LifecycleSource.TRANSPORT and not validated:
        raise make_error(
            prefix="VAL",
            component="HINV",
            number=2,
            kind="harness-observability-conformance",
            message=(
                f"non-validated surface {provider_id}/{surface_id} claims "
                f"transport observation publishing"
            ),
            details={
                "provider_id": provider_id,
                "surface_id": surface_id,
                "validated": validated,
            },
        )

    # Rule 3: no lifecycle source but evidence.validated=True is inconsistent
    if lifecycle_source == LifecycleSource.NONE and validated:
        raise make_error(
            prefix="VAL",
            component="HINV",
            number=3,
            kind="harness-observability-conformance",
            message=(
                f"surface {provider_id}/{surface_id} with no lifecycle source has validated=True"
            ),
            details={
                "provider_id": provider_id,
                "surface_id": surface_id,
            },
        )


# ---------------------------------------------------------------------------
# Inventory serialization (for reference docs and diagnostics)
# ---------------------------------------------------------------------------


def render_harness_inventory_markdown() -> str:
    """Render the AS27 inventory as a deterministic markdown table."""
    facts = _build_inventory()
    headers = [
        "Provider",
        "Surface",
        "Recipe",
        "Validated",
        "Reference",
        "Lifecycle Source",
        "Probe Anchor",
    ]
    lines: list[str] = [
        "# AS27 Harness Observability Inventory",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]

    for (provider_id, surface_id), fact in sorted(facts.items()):
        row = [
            provider_id,
            surface_id,
            fact.recipe,
            str(fact.evidence.validated),
            fact.evidence.reference or "",
            fact.lifecycle_source.value,
            fact.probe_anchor or "",
        ]
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines) + "\n"
