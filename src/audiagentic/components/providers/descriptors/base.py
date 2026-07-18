from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from audiagentic.foundation.steps import CallableStep, SequenceStep, ShellStep
from audiagentic.foundation.toolchains.managed_config import ManagedConfigSpec

from .automation_capabilities import ProviderAutomationCapability

IsolationTier = Literal["full-isolation", "partial-isolation", "no-isolation"]


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
    cli_install: CliInstallRecipe | None = None
    host_capabilities: tuple[HostCapability, ...] = field(default_factory=tuple)
    # Provider-owned knowledge/evidence. These records describe declared or
    # externally documented capabilities; they never register or execute them.
    capability_facts: tuple[ProviderCapabilityFact, ...] = field(default_factory=tuple)
    # The provider-level execution configuration isolation fact.  It is not an
    # automation-family property: gateway admission and worker materialization
    # need one provider-wide declaration, independently of supported families.
    execution_isolation_tier: IsolationTier = "no-isolation"
    # Explicitly declared automation families. These declarations are only
    # capability metadata; explicit provider+family code registration is still
    # required before an operation can execute.
    automation_capabilities: tuple[ProviderAutomationCapability, ...] = field(
        default_factory=tuple
    )
    permissions: ProviderPermissions = field(default_factory=ProviderPermissions)
    agent_files: tuple[AgentFile, ...] = field(default_factory=tuple)
    # access-mode written to providers.yaml when this provider is first enabled.
    # "cli"  — invoked as a subprocess CLI tool
    # "env"  — accessed via environment / API key (no local binary)
    # "none" — passthrough bridge, no direct provider access
    access_mode: str = "cli"
    # Path template for skill surface files, e.g. ".claude/skills/{tag}/SKILL.md".
    # None means this provider has no skill file concept (contributions go to AGENTS.md etc.).
    skill_surface_path: str | None = None
    # Relative path of the provider's managed instruction file in the project root,
    # e.g. "CLAUDE.md". None means no instruction file is rendered for this provider.
    instruction_file: str | None = None
    # Optional: fetch live model list. Receives provider config dict; returns list
    # of model dicts conforming to provider-model-catalog schema (model-id, display-name,
    # status, supports-structured-output, context-window). None = not supported.
    fetch_catalog_fn: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None
    # MCP server config spec — None means this provider has no manageable MCP config.
    # kind="mcp"; capabilities may include managed_config.REMOTE_CAPABILITY when the
    # format can express url-form (remote) entries — consulted by requesters
    # before projecting a remote entry.
    mcp_config: ManagedConfigSpec | None = None
    # Generic named plugin-entry config capability (MA20). Requesters supply an
    # entry identity/options; this descriptor owns native format/path mechanics.
    # Uses ManagedConfigSpec so sync_managed_config can reconcile entries and
    # preserve foreign plugins — same engine as mcp_config.
    plugin_config: ManagedConfigSpec | None = None
    # Language server config spec — None means this provider doesn't accept LSP config sync.
    # kind="language-servers"; refresh_mode stays at the "none" default (no reload concept).
    language_servers_config: ManagedConfigSpec | None = None
    # Native hooks config spec — None means this provider has no manageable hooks.
    # Uses ManagedConfigSpec so sync_managed_config can reconcile hook entries and
    # preserve foreign hooks — same engine as mcp_config (MA26).
    hooks_config: ManagedConfigSpec | None = None
    # Model-endpoint config spec — None means AUDiaGentic cannot write managed
    # model entries into this provider's config (kind="model-endpoints"). The
    # reader/writer/remover trio is adapter-owned, same contract as mcp_config.
    # Declared per provider YAML only after MO09 verification (MO03/MO13/MO14).
    model_config: ManagedConfigSpec | None = None
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
    # supported_connectors: connectors this provider's config format can render
    # via custom-entries projection (e.g. ("openai-compatible", "ollama")).
    supported_connectors: tuple[str, ...] = field(default_factory=tuple)
    # vendor_key_injection: (vendor-id) -> {"mechanism": "env"|"config", "key": <env-var-name-or-config-path>}
    # for the native-key-injection projection path (RV332/RV337 standalone-first
    # ranking: config-mechanism entries prefer the tool's own env-indirection
    # syntax over resolved literals where the tool supports it).
    vendor_key_injection: dict[str, dict[str, str]] = field(default_factory=dict)
    # Optional hook fired when the coding-lsp component is enabled. Lets a provider
    # provision its own LSP support (e.g. pi installs the pi-lens extension, which
    # auto-discovers language servers from PATH). When set, the provider is treated
    # as self-providing LSP and is excluded from the generic ag-lsp MCP projection.
    # Receives project_root; returns a result dict.
    on_lsp_enabled: Callable[[Path | None], dict[str, Any]] | None = None
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
    execution: dict[str, Any] | None = None
    # Declarative surface rendering (AR03). When present, a standard renderer is
    # registered for this provider from the descriptor alone — no surface.py.
    # Keys: renderer ("flat-skill" renders per-skill files + the instruction
    # file; "none" renders no skill surfaces), contribution-file (single-file
    # contribution target, e.g. "GEMINI.md" or "AGENTS.md"),
    # launch-example-template (default "@{tag}-{provider_id}").
    # Adapters with custom rendering keep a surface.py, which wins over this.
    surfaces: dict[str, Any] | None = None
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

    def host_extensions(self, host_id: str) -> tuple[HostCapability, ...]:
        """Capabilities declared for one editor host."""
        return tuple(
            capability
            for capability in self.host_capabilities
            if capability.host == host_id
        )

    def automation_capability(
        self, family_id: str
    ) -> ProviderAutomationCapability | None:
        """Return one explicitly declared automation family, if supported."""
        return next(
            (
                capability
                for capability in self.automation_capabilities
                if capability.family_id == family_id
            ),
            None,
        )

    @property
    def install_mode(self) -> str:
        return "external-configured" if self.cli_install is not None else "unmanaged"
