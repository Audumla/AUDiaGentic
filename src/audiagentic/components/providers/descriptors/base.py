from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .session_surface_declarations import SessionSurfaceDeclaration

from audiagentic.foundation.steps import CallableStep, SequenceStep, ShellStep
from audiagentic.foundation.toolchains.config.managed_config import ManagedConfigSpec

from ..contracts.mcp_launch_surface import McpLaunchIsolationTier
from ..contracts.provider_execution import ProviderIsolationTier as IsolationTier
from .automation_capabilities import ProviderAutomationCapability

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

    kind: str  # catalogue key, e.g. 'mcp', 'host-extensions'
    mechanism: Any  # shaped by catalogue's mechanism_schema for this kind
    modes: tuple[str, ...] = ()  # provisioned only; must match family's supported_modes
    evidence: CapabilityEvidence | None = None


@dataclass(frozen=True)
class HostCapability:
    host: str
    capability_id: str
    display_name: str


@dataclass(frozen=True)
class ObsTransportNote:
    """Mechanism for the `obs-transport-observability` evidence-only kind.

    ``transport`` names a generic session-transport concept (e.g.
    ``acp-stdio``, ``cli-session``) — never a provider-specific tag. Distinct
    transports for one provider are separate list entries under the same
    kind, disambiguated by this field rather than by kind naming.
    """

    transport: str


@dataclass(frozen=True)
class ModelsSpec:
    """Compound mechanism for the unified `models` capability.

    Folds the model-endpoint story into one record: the managed store
    (curation), the adapter-owned entry renderer, the catalog-refresh
    callable, the connector shapes this provider's config can render, and
    per-vendor credential references. Credential values are plain
    ``secrets.py`` reference strings (e.g. ``"env:OPENAI_API_KEY"``),
    resolved only at the narrow consuming boundary via
    ``resolve_secret_ref``/``has_ambient_value`` — never stored resolved.
    """

    store: ManagedConfigSpec | None = None
    entry_renderer: Callable[[Any], tuple[str, Any]] | None = None
    refresh: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None
    connectors: tuple[str, ...] = ()
    credentials: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LaunchSpec:
    """Compound mechanism for the unified `launch` capability (HA04).

    ``intents`` declares, per launch intent (execute/interactive/agent), the
    harness's queryable channel surface: ``interaction`` (how it's driven —
    native tty/stdin, acp, ...) and ``observability`` (how we introspect it —
    pipe = none, rpc, acp events, hooks, ...). The caller picks an intent; the
    harness assembles its richest surface — the caller never selects
    transports/channels directly. An undeclared intent means unsupported.

    ``recipes`` are declarative launch recipes keyed by profile/submodule name
    (``execution``, ``interactive``, ``acp``, or any future launch kind — open
    ended, not a closed enum). A hand-written ``adapters/<id>/<kind>.py``
    builder always wins over the recipe of the same key.
    """

    intents: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    recipes: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class LspSelfSupportSpec:
    """Compound mechanism for the `lsp-self-support` capability.

    ``on_enabled`` is the mutating hook run when the coding-lsp component is
    enabled (installs the provider's own LSP support). ``probe`` is its
    optional non-mutating companion for status queries — never runs
    ``on_enabled``'s side effect just to check state.

    NOTE: this stays a separate kind from `lsp-config` (PC07 step 4 finding)
    — they dispatch through two genuinely separate, already-wired automation
    handlers (self_provided_lsp_handler.py vs language_server_family.py, two
    distinct family_ids). Folding them into one descriptor-level kind without
    also merging that dispatch code would silently break provisioning; that's
    a separate, larger change than this pass, not assumed here.
    """

    on_enabled: Callable[[Path | None], dict[str, Any]] | None = None
    probe: Callable[[Path | None], dict[str, Any]] | None = None


@dataclass(frozen=True)
class ACPFeatureNote:
    """Mechanism for one entry of the `acp` evidence-only list kind.

    ``feature`` names a generic ACP protocol feature concept (e.g.
    ``stdio-transport``, ``live-session``, ``session-resume``,
    ``shared-live-session``) — never a provider-specific tag. One list entry
    per feature per provider, each with its own evidence, since verification
    status (verified / planned / blocked) genuinely differs per feature.
    """

    feature: str


@dataclass(frozen=True)
class CapabilityEvidence:
    """A plain provenance trail for one capability — not a review record.

    Deep provenance (probe validation, platform evidence) lives in the owning
    subsystem (AS27/AS54/MI08/MO); this is just a note plus an optional
    pointer to where it came from.
    """

    note: str | None = None
    source: str | None = None


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
    because its semantics differ from install/uninstall (read-only, typed
    result); probe_fn wins when both are declared. probe is the plain
    shell-command fallback (e.g. ["aider", "--version"]) used when no probe_fn
    is set — both concern the same "is this CLI really there" question, so
    both live on the one capability that already owns install/uninstall.
    """
    package_manager: str        # metadata/display only
    package_name: str           # metadata/display only
    executable: str
    install: ShellStep | SequenceStep | CallableStep
    uninstall: ShellStep | SequenceStep | CallableStep
    # Explicit package-manager reconciliation.  None means an upgrade is not
    # safely declared for this provider; callers must report not applicable.
    upgrade: ShellStep | SequenceStep | CallableStep | None = None
    uninstall_name: str | None = None
    probe: list[str] | None = None
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
        upgrade=(build_step(toolchain, "upgrade", package, *extra)
                 if has_action(toolchain, "upgrade") else None),
        **kwargs,
    )


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    description: str = ""
    url: str = ""
    prompt_aliases: tuple[str, ...] = field(default_factory=tuple)
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
    # Controls whether this provider receives the ag-lsp MCP server from the
    # coding-lsp component. When True (default), the provider gets the MCP server
    # regardless of whether it has its own LSP implementation. Set to False to
    # opt-out of receiving the ag-lsp MCP.
    receive_lsp_mcp: bool = True
    # launches/execution/interactive/acp fold into the `launch` capability
    # (LaunchSpec, below) — see the launches/execution/interactive/acp
    # @property accessors for the per-field docs, unchanged in shape/type.
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

    # CC53: AS27 harness-observability inventory facts, owned by this
    # provider's own descriptor (not a central cross-provider Python list —
    # ARCHITECTURE_STANDARDS.md Section 2). Each entry is a validated raw
    # dict; the domain conversion (str -> LifecycleSource enum, etc.) is the
    # services/session layer's concern, not the descriptor loader's — this
    # layer only proves the YAML shape is structurally valid. Empty by
    # default; most providers declare zero or one entry, a few (opencode,
    # codex, claude, gemini, pi, continue) declare two surface variants.
    harness_observability: tuple[dict[str, Any], ...] = field(default_factory=tuple)

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
    def cli_probe(self) -> list[str] | None:
        recipe = self._mechanism("cli-install")
        return recipe.probe if recipe else None

    @property
    def mcp_config(self) -> ManagedConfigSpec | None:
        return self._mechanism("mcp")

    def _models_spec(self) -> ModelsSpec:
        return self._mechanism("models") or ModelsSpec()

    @property
    def model_config(self) -> ManagedConfigSpec | None:
        return self._models_spec().store

    @property
    def model_entry_renderer(self) -> Callable[[Any], tuple[str, Any]] | None:
        return self._models_spec().entry_renderer

    @property
    def fetch_catalog_fn(self) -> Callable[[dict[str, Any]], list[dict[str, Any]]] | None:
        return self._models_spec().refresh

    @property
    def supported_connectors(self) -> tuple[str, ...]:
        return self._models_spec().connectors

    @property
    def vendor_key_injection(self) -> dict[str, str]:
        """Per-vendor credential reference (secrets.py scheme:locator strings)."""
        return self._models_spec().credentials

    def _launch_spec(self) -> LaunchSpec:
        return self._mechanism("launch") or LaunchSpec()

    @property
    def launches(self) -> dict[str, dict[str, tuple[str, ...]]]:
        return self._launch_spec().intents

    @property
    def execution(self) -> dict[str, Any] | None:
        return self._launch_spec().recipes.get("execution")

    @property
    def interactive(self) -> dict[str, Any] | None:
        return self._launch_spec().recipes.get("interactive")

    @property
    def acp(self) -> dict[str, Any] | None:
        return self._launch_spec().recipes.get("acp")

    @property
    def plugin_config(self) -> ManagedConfigSpec | None:
        return self._mechanism("plugins")

    @property
    def hooks_config(self) -> ManagedConfigSpec | None:
        return self._mechanism("hooks")

    @property
    def language_servers_config(self) -> ManagedConfigSpec | None:
        return self._mechanism("lsp-config")

    @property
    def on_lsp_enabled(self) -> Callable[[Path | None], dict[str, Any]] | None:
        spec = self._mechanism("lsp-self-support")
        return spec.on_enabled if spec else None

    @property
    def lsp_support_probe(self) -> Callable[[Path | None], dict[str, Any]] | None:
        spec = self._mechanism("lsp-self-support")
        return spec.probe if spec else None

    @property
    def skill_surface_path(self) -> str | None:
        return self._mechanism("surface-skill")

    @property
    def instruction_file(self) -> str | None:
        return self._mechanism("surface-instruction")

    @property
    def surfaces(self) -> dict[str, Any] | None:
        return self._mechanism("surfaces")

    @property
    def permissions(self) -> ProviderPermissions:
        return self._mechanism("permissions") or ProviderPermissions()

    @property
    def host_capabilities(self) -> tuple[HostCapability, ...]:
        return self._mechanisms("host-extensions")

    @property
    def agent_files(self) -> tuple[AgentFile, ...]:
        return self._mechanisms("agent-files")

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
            # `models` is a compound mechanism (store/entry_renderer/refresh/
            # connectors/credentials); only `store` is an actual reconcile-able
            # resource. A provider declaring only refresh/connectors/credentials
            # (e.g. claude, local-openai) must NOT register model-projection
            # dispatch eligibility — there is nothing to reconcile against.
            if cap.kind == "models" and not getattr(cap.mechanism, "store", None):
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
