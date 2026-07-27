from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .session_surface_declarations import SessionSurfaceDeclaration

from audiagentic.foundation.steps import CallableStep, SequenceStep, ShellStep
from audiagentic.foundation.toolchains.config.managed_config import ManagedConfigSpec

from ..contracts.mcp_launch_surface import McpLaunchIsolationTier
from .automation_capabilities import ProviderAutomationCapability

IsolationTier = Literal["full-isolation", "partial-isolation", "no-isolation"]
CapabilityAuthority = Literal["automation", "operational", "evidence-only"]

# ── Unified capability record ────────────────────────────────────────────
# Replaces the four separate descriptor blocks (automation_capabilities,
# capability_facts, host_capabilities/permissions + config-spec fields) with
# one catalogue-driven map: kind → mechanism [+ modes + evidence].


@dataclass(frozen=True)
class Capability:
    """One provider capability entry in the unified map.

    ``kind`` is a catalogue key (from _capabilities.yaml). Authority,
    family, cardinality, and mechanism_schema come from the catalogue —
    the YAML only declares the kind name, mechanism data, optional modes,
    and optional evidence. The loader validates the kind against the
    catalogue and shapes the mechanism value accordingly.
    """

    kind: str  # catalogue key, e.g. 'mcp-config', 'host-extension'
    mechanism: Any  # shaped by catalogue's mechanism_schema for this kind
    modes: tuple[str, ...] = ()  # automation only; must match family's supported_modes
    evidence: CapabilityEvidence | None = None


@dataclass(frozen=True)
class HostCapability:
    host: str
    capability_id: str
    display_name: str


@dataclass(frozen=True)
class CapabilityEvidence:
    """Evidence supporting one provider capability fact."""

    evidence_tier: str = "unverified"
    tool_version: str | None = None
    fact_anchor: str | None = None
    review_state: str = "pending-review"


@dataclass(frozen=True)
class ProviderCapabilityFact:
    """Provider-owned capability knowledge; never execution authority."""

    capability_id: str
    subject: str
    mechanism: str | None = None
    constraints: tuple[str, ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)
    support_assessment: str | None = None
    action_needed: str | None = None
    evidence: CapabilityEvidence = field(default_factory=CapabilityEvidence)


@dataclass(frozen=True)
class AgentFile:
    """A project file owned or written by a provider surface."""
    rel_path: str           # relative to project root
    managed: bool = True    # AUDiaGentic generates/updates this file
    description: str = ""


@dataclass(frozen=True)
class ProviderPermissions:
    """Inherent capability model of a provider (what it *can* do, not policy)."""
    can_write_files: bool = False
    can_execute_shell: bool = False
    can_browse_web: bool = False
    can_read_env: bool = False
    notes: str = ""


@dataclass(frozen=True)
class CliInstallRecipe:
    """How AUDiaGentic can provision a provider CLI.

    Use cli_recipe() for standard toolchain installs (npm, uv, brew, vscode).
    Custom provisioners (e.g. pi-harness, raw shell scripts) pass steps directly.

    probe_fn is kept as a callable returning a structured availability dict
    because its semantics differ from install/uninstall (read-only, typed result).
    """
    package_manager: str        # metadata/display only
    package_name: str           # metadata/display only
    executable: str
    install: ShellStep | SequenceStep | CallableStep
    uninstall: ShellStep | SequenceStep | CallableStep
    uninstall_name: str | None = None
    probe_fn: Callable[[Any], dict[str, Any] | None] | None = None


def cli_recipe(
    toolchain: str,
    package: str,
    *extra: str,
    executable: str,
    uninstall_package: str | None = None,
    **kwargs: Any,
) -> CliInstallRecipe:
    """Build a CliInstallRecipe from a toolchain name and package, without importing toolchains."""
    from audiagentic.foundation.toolchains.loader import build_step, has_action
    un_pkg = uninstall_package or package
    un_action = "uninstall" if has_action(toolchain, "uninstall") else "remove"
    return CliInstallRecipe(
        package_manager=toolchain,
        package_name=package,
        executable=executable,
        install=build_step(toolchain, "install", package, *extra),
        uninstall=build_step(toolchain, un_action, un_pkg),
        **kwargs,
    )


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    description: str = ""
    url: str = ""
    prompt_aliases: tuple[str, ...] = field(default_factory=tuple)
    cli_probe: list[str] | None = None
    # The provider-level execution configuration isolation fact.  It is not an
    # automation-family property: gateway admission and worker materialization
    # need one provider-wide declaration, independently of supported families.
    execution_isolation_tier: IsolationTier = "no-isolation"
    # Provider-wide MCP launch capability.  This is an inherent harness fact,
    # not mutable feature state and not a per-launch configuration choice.
    mcp_launch_isolation_tier: McpLaunchIsolationTier = "unsupported"
    # ── Unified capability map (PC02) ────────────────────────────────────
    # Replaces the four separate descriptor blocks:
    #   automation_capabilities, capability_facts, host_capabilities,
    #   permissions, + config-spec fields (mcp_config, model_config, ...)
    # Populated from the new ``capabilities:`` YAML block.
    # When reading legacy shape, derived from flat fields in loader.
    capabilities: tuple[Capability, ...] = field(default_factory=tuple)

    # access-mode written to providers.yaml when this provider is first enabled.
    # "cli"  — invoked as a subprocess CLI tool
    # "env"  — accessed via environment / API key (no local binary)
    # "none" — passthrough bridge, no direct provider access
    access_mode: str = "cli"
    # Adapter-owned entry renderer: converts one provider-NEUTRAL
    # MaterializedModelEntry into (visible_name, native_payload) — the payload
    # model_config.writer accepts. Declared as a YAML dotted ref and resolved
    # at load, exactly like reader/writer/remover — a plain callable on the
    # descriptor, not a runtime string-keyed lookup. Provider-native
    # vocabulary (Pi's baseUrl/compat, Codex's model_providers table) lives
    # exclusively in these adapter functions (RV271).
    model_entry_renderer: Callable[[Any], tuple[str, Any]] | None = None
    # Model-source connector capability declarations (MO01 step 4). Empty by
    # default: an undeclared (provider, connector)/(provider, vendor) pair
    # projects nothing — values are populated only from MO09-verified evidence,
    # never guessed. Config-over-code (arch-standards §2): provider YAML is the
    # sole declaration surface, never a provider-id branch in service code.
    #
    # vendor_key_injection: (vendor-id) -> {"mechanism": "env"|"config", "key": <env-var-name-or-config-path>}
    # for the native-key-injection projection path (RV332/RV337 standalone-first
    # ranking: config-mechanism entries prefer the tool's own env-indirection
    # syntax over resolved literals where the tool supports it).
    vendor_key_injection: dict[str, dict[str, str]] = field(default_factory=dict)
    # Optional non-mutating companion to on_lsp_enabled. Reports whether the
    # provider's self-provided LSP support is already present, without
    # provisioning it. The self-provided-lsp family uses this for status mode so
    # a query never triggers the install side effect of on_lsp_enabled. When a
    # provider declares on_lsp_enabled but no probe, status reports evidence-only
    # "unknown" rather than executing the hook.
    lsp_support_probe: Callable[[Path | None], dict[str, Any]] | None = None
    # Controls whether this provider receives the ag-lsp MCP server from the
    # coding-lsp component. When True (default), the provider gets the MCP server
    # regardless of whether it has its own LSP implementation. Set to False to
    # opt-out of receiving the ag-lsp MCP.
    receive_lsp_mcp: bool = True
    # Declarative execution pipeline (AR12). When present and no hand-written
    # adapter.py exists, adapters/base_runner.py builds the runner from this
    # block (mode: cli | stub | ok-stub | unsupported; see base_runner docstring
    # for the full schema). Custom adapter modules always win.
    # Declared launch capability (HA04). Callers pick an INTENT; the harness
    # adapter assembles its richest surface to fulfill it — the caller never
    # selects transports/channels. Intents:
    #   execute      run one turn, capture a result (gateway task)
    #   interactive  a live session for a human at a terminal
    #   agent        a live programmatic agent session
    # The value is the harness's queryable channel surface for that intent, by
    # role: ``interaction`` (how it's driven: native tty/stdin, acp, ...) and
    # ``observability`` (how we introspect it: pipe = none, rpc, acp events,
    # hooks, ...). The harness uses all it can; a caller may query this to
    # request a constrained subset. resolve_launch_builder gates on the intent
    # keys; an empty map means undeclared (dispatch probes, migration default).
    launches: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    execution: dict[str, Any] | None = None
    # Declarative launch recipes for the ACP and interactive-TUI launch kinds
    # (HA04). When present and no hand-written adapters/<id>/{acp,interactive}.py
    # exists, recipe_launch builds a ProviderLaunch from this block via
    # build_launch_spec. The block is both the recipe (executable/args/
    # environment) and its own config (tools/lockdown/... for the flag
    # primitives). Hand-written builders always win.
    interactive: dict[str, Any] | None = None
    acp: dict[str, Any] | None = None
    # Whether this provider is deprecated (superseded by another tool or EOL).
    # Drives structured behavior: filtering from active listings, warnings on
    # dispatch, migration prompts. Distinct from annotations — do not store
    # logic-driving state in the free-form annotations dict.
    deprecated: bool = False
    # Free-form key/value for informational metadata an agent or user can read.
    # Not consumed by execution logic — use structured fields (deprecated, etc.)
    # for anything that drives code behavior. Example keys: migration_guide,
    # deprecation_notes, beta_status_links.
    annotations: dict[str, Any] = field(default_factory=dict)
    # AS29 stage 2: descriptor-local session-surface declarations. Each
    # :class:`~session_surface_declarations.SessionSurfaceDeclaration` carries
    # an ``adapter_ref`` (dotted path string, unresolved) that must NOT appear
    # in the foundation :class:`ResolvedSessionSurface`. Empty by default for
    # backward compatibility.
    session_surfaces: tuple[SessionSurfaceDeclaration, ...] = field(default_factory=tuple)

    # ── Capability lookup (PC02 unified accessors) ───────────────────────

    def get_capability(self, kind_id: str) -> Capability | None:
        """Return the capability entry for a given catalogue kind id."""
        return next((c for c in self.capabilities if c.kind == kind_id), None)

    # ── Flat accessors: project the unified capabilities into the historical
    #    attribute names so consumers read one value without knowing the map. ──

    def _mechanism(self, kind_id: str) -> Any:
        cap = self.get_capability(kind_id)
        return cap.mechanism if cap else None

    def _mechanisms(self, kind_id: str) -> tuple[Any, ...]:
        return tuple(c.mechanism for c in self.capabilities if c.kind == kind_id)

    @property
    def cli_install(self) -> CliInstallRecipe | None:
        return self._mechanism("cli-install")

    @property
    def mcp_config(self) -> ManagedConfigSpec | None:
        return self._mechanism("mcp-config")

    @property
    def model_config(self) -> ManagedConfigSpec | None:
        return self._mechanism("model-config")

    @property
    def plugin_config(self) -> ManagedConfigSpec | None:
        return self._mechanism("plugin-config")

    @property
    def hooks_config(self) -> ManagedConfigSpec | None:
        return self._mechanism("hook-config")

    @property
    def language_servers_config(self) -> ManagedConfigSpec | None:
        return self._mechanism("lsp-config")

    @property
    def fetch_catalog_fn(self) -> Callable[[dict[str, Any]], list[dict[str, Any]]] | None:
        return self._mechanism("model-catalog-refresh")

    @property
    def on_lsp_enabled(self) -> Callable[[Path | None], dict[str, Any]] | None:
        return self._mechanism("lsp-self-support")

    @property
    def skill_surface_path(self) -> str | None:
        return self._mechanism("surface-skill")

    @property
    def instruction_file(self) -> str | None:
        return self._mechanism("surface-instruction")

    @property
    def surfaces(self) -> dict[str, Any] | None:
        return self._mechanism("surface-render")

    @property
    def permissions(self) -> ProviderPermissions:
        return self._mechanism("perm-declaration") or ProviderPermissions()

    @property
    def host_capabilities(self) -> tuple[HostCapability, ...]:
        return self._mechanisms("host-extension")

    @property
    def agent_files(self) -> tuple[AgentFile, ...]:
        return self._mechanisms("file-agent")

    @property
    def supported_connectors(self) -> tuple[str, ...]:
        return self._mechanism("model-connectors") or ()

    @property
    def capability_facts(self) -> tuple[ProviderCapabilityFact, ...]:
        return ()

    @property
    def automation_capabilities(self) -> tuple[ProviderAutomationCapability, ...]:
        """Synthesize automation declarations from the provisioned capabilities."""
        from .capability_catalogue import get_catalogue

        cat = get_catalogue()
        out: list[ProviderAutomationCapability] = []
        seen: set[str] = set()
        for cap in self.capabilities:
            kind = cat.kinds_by_id.get(cap.kind)
            if kind is None or kind.authority != "provisioned" or not kind.family_id:
                continue
            if kind.family_id in seen:
                continue
            fam = cat.families.get(kind.family_id)
            if fam is None:
                continue
            seen.add(kind.family_id)
            out.append(
                ProviderAutomationCapability(
                    family_id=kind.family_id,
                    supported_modes=cap.modes or fam.supported_modes,
                    payload_contract=fam.payload_contract,
                    result_contract=fam.result_contract,
                    ownership_scope_required=fam.ownership_scope_required,
                )
            )
        # generated-surfaces is universal: every provider renders surfaces
        # (via a surfaces: block, skill/instruction paths, or a custom surface.py
        # adapter), so the renderer family registers for all providers.
        if "generated-surfaces" not in seen:
            fam = cat.families.get("generated-surfaces")
            if fam is not None:
                out.append(
                    ProviderAutomationCapability(
                        family_id="generated-surfaces",
                        supported_modes=fam.supported_modes,
                        payload_contract=fam.payload_contract,
                        result_contract=fam.result_contract,
                        ownership_scope_required=fam.ownership_scope_required,
                    )
                )
        return tuple(out)

    def automation_capability(
        self, family_id: str
    ) -> ProviderAutomationCapability | None:
        """Return one explicitly declared automation family, if supported."""
        return next(
            (c for c in self.automation_capabilities if c.family_id == family_id),
            None,
        )

    def host_extensions(self, host_id: str) -> tuple[HostCapability, ...]:
        """Capabilities declared for one editor host."""
        return tuple(c for c in self.host_capabilities if c.host == host_id)

    @property
    def install_mode(self) -> str:
        return "external-configured" if self.cli_install is not None else "unmanaged"
