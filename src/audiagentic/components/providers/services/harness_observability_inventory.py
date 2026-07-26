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

Error codes:
    VAL-HINV-001  — unsupported lifecycle source claimed as transport-observation publisher
    VAL-HINV-002  — non-validated surface claims effective level >= O1 for transport observation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.transports.session_surface import (
    EffectiveObservationLevel,
    LifecycleSource,
    SurfaceValidationState,
)

# ---------------------------------------------------------------------------
# Inventory value types
# ---------------------------------------------------------------------------

class CapabilityFactValidationState(StrEnum):
    """Validation state for a harness observability capability fact."""
    PROBE_REQUIRED = "probe-required"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    VALIDATED = "validated"


@dataclass(frozen=True)
class HarnessSurfaceCapabilityFact:
    """A single harness-surface capability fact for the AS27 inventory.

    Records declared capability, validation state, and effective production
    level independently — three axes never collapsed into one O-level.
    """

    # Provider + surface identity
    provider_id: str
    surface_id: str

    # Declared capability (evidence-planning metadata)
    declared_capability: EffectiveObservationLevel = EffectiveObservationLevel.O0

    # Candidate source — what documentation or prior evidence points to
    candidate_source: str | None = None

    # Validation state (probe-required / blocked / unsupported / validated)
    validation_state: CapabilityFactValidationState = CapabilityFactValidationState.PROBE_REQUIRED

    # Effective production level — the ONLY value consumed by runtime resolution
    effective_production_level: EffectiveObservationLevel = EffectiveObservationLevel.O0

    # Recipe classification (A/B/C/D per AS27 spec)
    recipe: str = "D"  # A=transport-observation, B=managed-hook, C=structured-output, D=unresolved/external

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
# The AS27 inventory — every known harness surface
# ---------------------------------------------------------------------------

def _build_inventory() -> dict[tuple[str, str], HarnessSurfaceCapabilityFact]:
    """Build the authoritative harness observability inventory.

    OpenCode ACP (opencode-acp) is the only validated transport-observation
    publisher. All other surfaces are inventory-only: probe-required/blocked/
    unsupported with O0 effective level.
    """
    facts: dict[tuple[str, str], HarnessSurfaceCapabilityFact] = {}

    # ── OpenCode (opencode-acp is the ONLY validated transport-observation) ──

    facts[("opencode", "opencode-acp")] = HarnessSurfaceCapabilityFact(
        provider_id="opencode",
        surface_id="opencode-acp",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="native ACP stdio transport",
        validation_state=CapabilityFactValidationState.VALIDATED,
        effective_production_level=EffectiveObservationLevel.O1,
        recipe="A",
        lifecycle_source=LifecycleSource.TRANSPORT,
        supported_statuses=frozenset({
            "model-thinking",
            "tool-calling",
            "waiting-permission",
        }),
        probe_anchor="tests/e2e/agents/test_opencode_acp_e2e.py",
        platform_evidence=("linux-amd64",),
    )

    # OpenCode CLI session — Recipe A/C candidate, not validated
    facts[("opencode", "opencode-cli-session")] = HarnessSurfaceCapabilityFact(
        provider_id="opencode",
        surface_id="opencode-cli-session",
        declared_capability=EffectiveObservationLevel.O1,
        candidate_source="CLI run --session synchronous completion / idle/status",
        validation_state=CapabilityFactValidationState.BLOCKED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A/C",
        lifecycle_source=LifecycleSource.NONE,
    )

    # ── Codex ──

    facts[("codex", "codex-acp")] = HarnessSurfaceCapabilityFact(
        provider_id="codex",
        surface_id="codex-acp",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="ACP adapter bridge",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="AS13 bridge/version proof",
    )

    facts[("codex", "codex-cli")] = HarnessSurfaceCapabilityFact(
        provider_id="codex",
        surface_id="codex-cli",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="native hooks TOML reader/writer/remover",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="B",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="installed TOML/hooks reader-writer-remover proof",
    )

    # ── Claude Code ──

    facts[("claude", "claude-acp")] = HarnessSurfaceCapabilityFact(
        provider_id="claude",
        surface_id="claude-acp",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="ACP adapter",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="verify package, launch, terminal and correlation",
    )

    facts[("claude", "claude-cli")] = HarnessSurfaceCapabilityFact(
        provider_id="claude",
        surface_id="claude-cli",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="native hooks: UserPromptSubmit/PreToolUse/PostToolUse/Stop/SessionEnd",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="B",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="project hook lifecycle and non-vetoing emitter proof",
    )

    # ── Cline ──

    facts[("cline", "cline-acp")] = HarnessSurfaceCapabilityFact(
        provider_id="cline",
        surface_id="cline-acp",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="ACP: npx @cline/cline-acp --mcp --acp",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="session/turn/tool correlation proof",
    )

    # ── Gemini ──

    facts[("gemini", "gemini-acp")] = HarnessSurfaceCapabilityFact(
        provider_id="gemini",
        surface_id="gemini-acp",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="npx @google/gemini-cli --acp",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="independent of CLI hooks — prove event fidelity",
    )

    facts[("gemini", "gemini-cli")] = HarnessSurfaceCapabilityFact(
        provider_id="gemini",
        surface_id="gemini-cli",
        declared_capability=EffectiveObservationLevel.O3,
        candidate_source="BeforeAgent/BeforeModel/AfterModel/BeforeTool/AfterTool/AfterAgent/SessionEnd",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="B",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="probe project config and environment inheritance on Gemini 0.49.0",
    )

    # ── Qwen ──

    facts[("qwen", "qwen-acp")] = HarnessSurfaceCapabilityFact(
        provider_id="qwen",
        surface_id="qwen-acp",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="npx @qwen-code/qwen-code --acp --experimental-skills",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="prove flag/event effects",
    )

    # ── Kilo ──

    facts[("kilo", "kilo-acp")] = HarnessSurfaceCapabilityFact(
        provider_id="kilo",
        surface_id="kilo-acp",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="kilo acp",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="descriptor and transport proof first; prove transport/control/observation contract",
    )

    # ── Copilot ──

    facts[("copilot", "copilot-acp")] = HarnessSurfaceCapabilityFact(
        provider_id="copilot",
        surface_id="copilot-acp",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="official ACP server: copilot --acp --stdio or loopback TCP",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="pin CLI/protocol and test stdio or loopback TCP; public-preview version/Docker probe required",
    )

    # ── Pi ──

    facts[("pi", "pi-rpc")] = HarnessSurfaceCapabilityFact(
        provider_id="pi",
        surface_id="pi-rpc",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="JSONL agent/turn/message/tool events via pi --mode rpc --no-session",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="primary Pi route; prove schema/correlation/lifecycle/close semantics",
    )

    facts[("pi", "pi-community-acp")] = HarnessSurfaceCapabilityFact(
        provider_id="pi",
        surface_id="pi-community-acp",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="community ACP adapter (optional route)",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="pinned Docker probe only; never required for Pi coverage; never primary path",
    )

    # ── Goose ──

    facts[("goose", "goose-acp")] = HarnessSurfaceCapabilityFact(
        provider_id="goose",
        surface_id="goose-acp",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="official ACP/API route",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="prove prompt terminal response and correlation",
    )

    # ── OpenHands ──

    facts[("openhands", "openhands-canvas")] = HarnessSurfaceCapabilityFact(
        provider_id="openhands",
        surface_id="openhands-canvas",
        declared_capability=EffectiveObservationLevel.O2,
        candidate_source="WebSocket event stream and conversation state (Canvas/SDK)",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="A",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="probe exact Canvas/SDK version, event terminal semantics, ordering, replay and correlation",
    )

    # ── Aider (Recipe D) ──

    facts[("aider", "aider-cli")] = HarnessSurfaceCapabilityFact(
        provider_id="aider",
        surface_id="aider-cli",
        declared_capability=EffectiveObservationLevel.O0,
        candidate_source=None,
        validation_state=CapabilityFactValidationState.UNSUPPORTED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="D",
        lifecycle_source=LifecycleSource.NONE,
    )

    # ── Continue ──

    facts[("continue", "continue-headless")] = HarnessSurfaceCapabilityFact(
        provider_id="continue",
        surface_id="continue-headless",
        declared_capability=EffectiveObservationLevel.O0,
        candidate_source="structured one-shot result",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="C",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="one-shot terminal evidence is not reusable-session O2 without explicit persistent boundary",
    )

    facts[("continue", "continue-tui")] = HarnessSurfaceCapabilityFact(
        provider_id="continue",
        surface_id="continue-tui",
        declared_capability=EffectiveObservationLevel.O0,
        candidate_source=None,
        validation_state=CapabilityFactValidationState.UNSUPPORTED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="D",
        lifecycle_source=LifecycleSource.NONE,
    )

    # ── Antigravity ──

    facts[("antigravity", "antigravity-cli")] = HarnessSurfaceCapabilityFact(
        provider_id="antigravity",
        surface_id="antigravity-cli",
        declared_capability=EffectiveObservationLevel.O0,
        candidate_source="hooks/plugins/status — candidate route not source-pinned",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="B",
        lifecycle_source=LifecycleSource.NONE,
        probe_anchor="primary-source probe required; prove non-vetoing machine event and config lifecycle; no Gemini inference",
    )

    # ── Plandex (Recipe D) ──

    facts[("plandex", "plandex-cli")] = HarnessSurfaceCapabilityFact(
        provider_id="plandex",
        surface_id="plandex-cli",
        declared_capability=EffectiveObservationLevel.O0,
        candidate_source=None,
        validation_state=CapabilityFactValidationState.UNSUPPORTED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="D",
        lifecycle_source=LifecycleSource.NONE,
    )

    # ── Roo (Recipe D) ──

    facts[("roo", "roo-cli")] = HarnessSurfaceCapabilityFact(
        provider_id="roo",
        surface_id="roo-cli",
        declared_capability=EffectiveObservationLevel.O0,
        candidate_source=None,
        validation_state=CapabilityFactValidationState.UNSUPPORTED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="D",
        lifecycle_source=LifecycleSource.NONE,
    )

    # ── Zed surfaces (Recipe D) ──

    facts[("zed", "zed-external-agent")] = HarnessSurfaceCapabilityFact(
        provider_id="zed",
        surface_id="zed-external-agent",
        declared_capability=EffectiveObservationLevel.O0,
        candidate_source="delegates to the selected external agent's ACP/native route",
        validation_state=CapabilityFactValidationState.BLOCKED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="D",
        lifecycle_source=LifecycleSource.NONE,
    )

    facts[("zed", "zed-terminal")] = HarnessSurfaceCapabilityFact(
        provider_id="zed",
        surface_id="zed-terminal",
        declared_capability=EffectiveObservationLevel.O0,
        candidate_source=None,
        validation_state=CapabilityFactValidationState.UNSUPPORTED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="D",
        lifecycle_source=LifecycleSource.NONE,
    )

    # ── Crush (Recipe D) ──

    facts[("crush", "crush-backend")] = HarnessSurfaceCapabilityFact(
        provider_id="crush",
        surface_id="crush-backend",
        declared_capability=EffectiveObservationLevel.O0,
        candidate_source="possible server/session event route — needs primary-source evidence",
        validation_state=CapabilityFactValidationState.PROBE_REQUIRED,
        effective_production_level=EffectiveObservationLevel.O0,
        recipe="D",
        lifecycle_source=LifecycleSource.NONE,
    )

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

    Only validated surfaces with effective_production_level >= O1 and
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
    # Gate 1: validation + effective level + lifecycle source
    base_eligible = (
        fact.validation_state == CapabilityFactValidationState.VALIDATED
        and fact.effective_production_level.numeric >= 1
        and fact.lifecycle_source == LifecycleSource.TRANSPORT
    )
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

    Currently only opencode-acp satisfies this gate, on all validated
    platforms (windows-amd64, darwin-arm64, darwin-amd64, linux-amd64).
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
    effective_level: EffectiveObservationLevel,
    validation_state: SurfaceValidationState | CapabilityFactValidationState,
) -> None:
    """Enforce AS27 conformance for a harness observability declaration.

    A lifecycle observation declaration may NOT claim transport-observation
    publishability unless the surface is validated, effective_level >= O1,
    and present in the Recipe-A eligible set.

    Raises:
        AudiaGenticError (VAL-HINV-001): unsupported lifecycle source claimed
            as transport-observation publisher
        AudiaGenticError (VAL-HINV-002): non-validated surface claims
            effective level >= O1 for transport observation
    """
    fact = get_harness_surface_capability_fact(provider_id, surface_id)

    # Unknown surface is always unsupported — no conformance violation,
    # it just cannot publish.
    if fact is None:
        return

    # Rule 1: only transport-observation lifecycle source may be a publisher
    if (
        lifecycle_source == LifecycleSource.TRANSPORT
        and fact.validation_state != CapabilityFactValidationState.VALIDATED
    ):
        raise make_error(
            prefix="VAL", component="HINV", number=1,
            kind="harness-observability-conformance",
            message=(
                f"unsupported lifecycle source '{lifecycle_source.value}' "
                f"claimed as transport-observation publisher for "
                f"{provider_id}/{surface_id}"
            ),
            details={
                "provider_id": provider_id,
                "surface_id": surface_id,
                "validation_state": fact.validation_state.value,
            },
        )

    # Rule 2: non-validated surfaces cannot claim effective_level >= O1 for
    # transport observation publishing
    is_not_validated = (
        isinstance(validation_state, CapabilityFactValidationState)
        and validation_state != CapabilityFactValidationState.VALIDATED
    ) or (
        isinstance(validation_state, SurfaceValidationState)
        and validation_state != SurfaceValidationState.VALIDATED
    )
    if (
        lifecycle_source == LifecycleSource.TRANSPORT
        and effective_level.numeric >= 1
        and is_not_validated
    ):
        raise make_error(
            prefix="VAL", component="HINV", number=2,
            kind="harness-observability-conformance",
            message=(
                f"non-validated surface {provider_id}/{surface_id} claims "
                f"effective level '{effective_level.value}' for transport observation"
            ),
            details={
                "provider_id": provider_id,
                "surface_id": surface_id,
                "effective_level": effective_level.value,
                "validation_state": validation_state.value,
            },
        )

    # Rule 3: unsupported lifecycle sources (none) may not carry O1+ for transport
    if lifecycle_source == LifecycleSource.NONE and effective_level.numeric >= 1:
        raise make_error(
            prefix="VAL", component="HINV", number=3,
            kind="harness-observability-conformance",
            message=(
                f"surface {provider_id}/{surface_id} with no lifecycle source "
                f"claims effective level '{effective_level.value}'"
            ),
            details={
                "provider_id": provider_id,
                "surface_id": surface_id,
                "effective_level": effective_level.value,
            },
        )


# ---------------------------------------------------------------------------
# Inventory serialization (for reference docs and diagnostics)
# ---------------------------------------------------------------------------

def render_harness_inventory_markdown() -> str:
    """Render the AS27 inventory as a deterministic markdown table."""
    facts = _build_inventory()
    headers = [
        "Provider", "Surface", "Recipe", "Declared",
        "Validation", "Effective", "Lifecycle Source", "Probe Anchor",
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
            fact.declared_capability.value,
            fact.validation_state.value,
            fact.effective_production_level.value,
            fact.lifecycle_source.value,
            fact.probe_anchor or "",
        ]
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines) + "\n"
