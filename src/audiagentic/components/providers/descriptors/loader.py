"""Provider descriptor YAML loader.

Builds ``ProviderDescriptor`` instances from YAML files under
``config/providers/``. Uses the DescriptorSpec mechanism from ``spec.py``:
    load YAML → resolve dotpath hooks → build step tree → construct typed descriptor

The PROVIDER_SPEC declares the field map for ProviderDescriptor.
Requester-specific fields are NOT part of this spec; they belong to their
own owning components.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.config.refs import resolve_ref
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths.names import get_package_providers_config_dir
from audiagentic.foundation.toolchains.config.managed_config import (
    REMOTE_CAPABILITY,
    ManagedConfigSpec,
)
from audiagentic.foundation.transports.session_surface import (
    ContentChannelCapability,
    ControlSupport,
    PlatformEvidence,
    SessionControlAction,
    SessionIdentityOperation,
    SessionMappingFacts,
)
from audiagentic.foundation.workflow.invocation.from_spec import build_step_from_spec

from .automation_capabilities import ProviderAutomationCapability, validate_automation_capabilities
from .base import (
    AgentFile,
    Capability,
    CapabilityEvidence,
    CliInstallRecipe,
    HostCapability,
    ProviderCapabilityFact,
    ProviderDescriptor,
    ProviderPermissions,
)
from .capability_facts import validate_provider_capability_facts
from .session_surface_declarations import (
    _CONTENT_CHANNEL_MAP,
    _CONTENT_CHANNEL_VALUES,
    _CONTROL_ACTION_MAP,
    _CONTROL_ACTION_VALUES,
    _CONTROL_SUPPORT_MAP,
    _CONTROL_SUPPORT_VALUES,
    _EFFECTIVE_LEVEL_MAP,
    _EFFECTIVE_LEVEL_VALUES,
    _LIFECYCLE_INSTALLATION_MAP,
    _LIFECYCLE_INSTALLATION_VALUES,
    _LIFECYCLE_SOURCE_MAP,
    _LIFECYCLE_SOURCE_VALUES,
    _OWNERSHIP_MODE_MAP,
    _OWNERSHIP_MODE_VALUES,
    _SURFACE_IDENTITY_OP_MAP,
    _SURFACE_IDENTITY_OP_VALUES,
    _VALIDATION_STATE_MAP,
    _VALIDATION_STATE_VALUES,
    SessionSurfaceDeclaration,
    _parse_enum,
    _validate_declarations,
)
from .spec import DescriptorSpec, iter_descriptor_files, load_descriptor


def _list_to_tuple(value: Any) -> tuple:
    """Convert list values from YAML to tuples."""
    if isinstance(value, list):
        return tuple(value)
    return value or tuple()


def _build_permissions(data: dict[str, Any]) -> ProviderPermissions:
    """Build ProviderPermissions from YAML dict."""
    return ProviderPermissions(
        can_write_files=data.get("can_write_files", False),
        can_execute_shell=data.get("can_execute_shell", False),
        can_browse_web=data.get("can_browse_web", False),
        can_read_env=data.get("can_read_env", False),
        notes=data.get("notes", ""),
    )


def _build_host_capabilities(data: list[dict[str, Any]]) -> tuple[HostCapability, ...]:
    """Build HostCapability tuple from YAML list."""
    return tuple(
        HostCapability(
            host=item["host"],
            capability_id=item["capability_id"],
            display_name=item["display_name"],
        )
        for item in data
    )


def _build_managed_config_spec(data: dict[str, Any]) -> ManagedConfigSpec:
    """Generic ManagedConfigSpec projector for managed-reconcile kinds.

    Serves every managed-config-spec kind (mcp, models, plugins, hooks,
    language-servers). The ``remote`` modifier is opt-in (mcp only).
    """
    return ManagedConfigSpec(
        config_path=data["config_path"],
        reader=resolve_ref(data["reader"]),
        writer=resolve_ref(data["writer"]),
        remover=resolve_ref(data["remover"]),
        format=data.get("format", ""),
        refresh_mode=data.get("refresh_mode", "none"),
        reload_fn=resolve_ref(data["reload_fn"]) if "reload_fn" in data else None,
        capabilities=frozenset({REMOTE_CAPABILITY}) if data.get("remote") else frozenset(),
    )


def _project_mechanism(mechanism_schema: str, raw: Any) -> Any:
    """Shape a capability's declared mechanism into its typed form per the
    catalogue's mechanism_schema. Primitive/unknown schemas keep the raw value.
    """
    if raw is None:
        return None
    if mechanism_schema == "managed-config-spec":
        return _build_managed_config_spec(raw)
    if mechanism_schema == "cli-install-recipe":
        return _build_cli_install(raw)
    if mechanism_schema == "permissions-struct":
        return _build_permissions(raw)
    if mechanism_schema == "host-capability":
        return HostCapability(**raw)
    if mechanism_schema == "agent-file":
        return AgentFile(
            rel_path=raw["rel_path"],
            managed=raw.get("managed", True),
            description=raw.get("description", ""),
        )
    if mechanism_schema == "callable-ref":
        return resolve_ref(raw) if isinstance(raw, str) else raw
    # boolean-set, tier-enum, surfaces-struct, acp-caps-list, lsp-automation-spec, none
    return raw


def _build_capabilities(data: dict[str, Any]) -> tuple[Capability, ...]:
    """Build the unified capability map (PC02): kind -> {mechanism, modes?}.

    ``capabilities:`` is a mapping of catalogue kind to an entry (or a list of
    entries for list-cardinality kinds). Kinds are validated against the
    catalogue (VAL-PCAP-009); the mechanism is kept as declared.
    """
    if not isinstance(data, dict):
        raise AudiaGenticError(
            code="VAL-PCAP-009",
            kind="providers",
            message="capabilities must be a mapping of kind -> entry",
        )
    from .capability_catalogue import validate_capability_id

    out: list[Capability] = []
    for kind, entry in data.items():
        kind_obj = validate_capability_id(kind)
        if kind_obj is None:
            raise AudiaGenticError(
                code="VAL-PCAP-009",
                kind="providers",
                message=f"unknown capability kind '{kind}'",
                details={"kind": kind},
            )
        for item in (entry if isinstance(entry, list) else [entry]):
            item = item or {}
            out.append(
                Capability(
                    kind=kind,
                    mechanism=_project_mechanism(kind_obj.mechanism_schema, item.get("mechanism")),
                    modes=tuple(item.get("modes", ())),
                )
            )
    return tuple(out)


def _build_capability_facts(
    data: list[dict[str, Any]],
) -> tuple[ProviderCapabilityFact, ...]:
    """Build provider-owned capability facts from a YAML list."""
    if not isinstance(data, list):
        raise AudiaGenticError(
            code="VAL-PCAP-009",
            kind="providers",
            message="capability_facts must be a list",
        )
    fact_fields = {
        "capability_id",
        "subject",
        "mechanism",
        "constraints",
        "limitations",
        "support_assessment",
        "action_needed",
        "evidence",
    }
    evidence_fields = {
        "evidence_tier",
        "tool_version",
        "fact_anchor",
        "review_state",
    }
    facts: list[ProviderCapabilityFact] = []
    for item in data:
        if not isinstance(item, dict):
            raise AudiaGenticError(
                code="VAL-PCAP-009",
                kind="providers",
                message="each capability fact must be a mapping",
            )
        unknown_fact_fields = sorted(set(item) - fact_fields)
        if unknown_fact_fields:
            raise AudiaGenticError(
                code="VAL-PCAP-009",
                kind="providers",
                message="unknown capability fact fields",
                details={"fields": unknown_fact_fields},
            )
        if not item.get("capability_id") or not item.get("subject"):
            raise AudiaGenticError(
                code="VAL-PCAP-009",
                kind="providers",
                message="capability fact requires capability_id and subject",
            )
        evidence_data = item.get("evidence") or {}
        if not isinstance(evidence_data, dict):
            raise AudiaGenticError(
                code="VAL-PCAP-009",
                kind="providers",
                message="capability fact evidence must be a mapping",
            )
        unknown_evidence_fields = sorted(set(evidence_data) - evidence_fields)
        if unknown_evidence_fields:
            raise AudiaGenticError(
                code="VAL-PCAP-009",
                kind="providers",
                message="unknown capability evidence fields",
                details={"fields": unknown_evidence_fields},
            )
        facts.append(
            ProviderCapabilityFact(
                capability_id=item["capability_id"],
                subject=item["subject"],
                mechanism=item.get("mechanism"),
                constraints=tuple(item.get("constraints") or ()),
                limitations=tuple(item.get("limitations") or ()),
                support_assessment=item.get("support_assessment"),
                action_needed=item.get("action_needed"),
                evidence=CapabilityEvidence(
                    evidence_tier=evidence_data.get("evidence_tier", "unverified"),
                    tool_version=evidence_data.get("tool_version"),
                    fact_anchor=evidence_data.get("fact_anchor"),
                    review_state=evidence_data.get("review_state", "pending-review"),
                ),
            )
        )
    return tuple(facts)


def _build_automation_capabilities(
    data: list[dict[str, Any]],
) -> tuple[ProviderAutomationCapability, ...]:
    if not isinstance(data, list):
        raise AudiaGenticError(
            code="VAL-PCAP-010",
            kind="providers",
            message="automation_capabilities must be a list",
        )
    fields = {
        "family_id",
        "supported_modes",
        "payload_contract",
        "result_contract",
        "ownership_scope_required",
    }
    capabilities: list[ProviderAutomationCapability] = []
    for item in data:
        if not isinstance(item, dict):
            raise AudiaGenticError(
                code="VAL-PCAP-010",
                kind="providers",
                message="each automation capability must be a mapping",
            )
        unknown = sorted(set(item) - fields)
        if unknown:
            raise AudiaGenticError(
                code="VAL-PCAP-010",
                kind="providers",
                message="unknown automation capability fields",
                details={"fields": unknown},
            )
        capabilities.append(
            ProviderAutomationCapability(
                family_id=str(item.get("family_id") or ""),
                supported_modes=tuple(item.get("supported_modes") or ()),
                payload_contract=str(item.get("payload_contract") or ""),
                result_contract=str(item.get("result_contract") or ""),
                ownership_scope_required=bool(item.get("ownership_scope_required")),
            )
        )
    validate_automation_capabilities(capabilities)
    return tuple(capabilities)


def _build_agent_files(data: list[dict[str, Any]]) -> tuple[AgentFile, ...]:
    """Build AgentFile tuple from YAML list."""
    return tuple(
        AgentFile(
            rel_path=item["rel_path"],
            managed=item.get("managed", True),
            description=item.get("description", ""),
        )
        for item in data
    )


def _build_cli_install(data: dict[str, Any]) -> CliInstallRecipe:
    """Build CliInstallRecipe from YAML dict.

    Supports two forms:
    1. toolchain-based: {toolchain, package, executable} — uses toolchains loader build_step
    2. explicit steps: {package_manager, package_name, executable, install, uninstall, probe_fn}
    """
    if "toolchain" in data:
        # Toolchain-based form
        toolchain = data["toolchain"]
        package = data["package"]
        executable = data["executable"]
        extra = data.get("extra", [])
        uninstall_package = data.get("uninstall_package", package)

        from audiagentic.foundation.toolchains.loader import build_step, has_action

        un_action = "uninstall" if has_action(toolchain, "uninstall") else "remove"

        return CliInstallRecipe(
            package_manager=toolchain,
            package_name=package,
            executable=executable,
            install=build_step(toolchain, "install", package, *extra),
            uninstall=build_step(toolchain, un_action, uninstall_package),
            probe_fn=resolve_ref(data["probe_fn"]) if "probe_fn" in data else None,
        )
    else:
        # Explicit step form
        install_spec = data.get("install")
        uninstall_spec = data.get("uninstall")

        return CliInstallRecipe(
            package_manager=data["package_manager"],
            package_name=data["package_name"],
            executable=data["executable"],
            install=build_step_from_spec(install_spec) if install_spec else None,  # type: ignore[arg-type]
            uninstall=build_step_from_spec(uninstall_spec) if uninstall_spec else None,  # type: ignore[arg-type]
            probe_fn=resolve_ref(data["probe_fn"]) if "probe_fn" in data else None,
        )


def _build_mcp_config(data: dict[str, Any]) -> ManagedConfigSpec:
    """Build the MCP ManagedConfigSpec from YAML dict."""
    return ManagedConfigSpec(
        config_path=data["config_path"],
        reader=resolve_ref(data["reader"]),
        writer=resolve_ref(data["writer"]),
        remover=resolve_ref(data["remover"]),
        format=data.get("format", ""),
        refresh_mode=data["refresh_mode"],
        reload_fn=resolve_ref(data["reload_fn"]) if "reload_fn" in data else None,
        capabilities=frozenset({REMOTE_CAPABILITY}) if data.get("remote", True) else frozenset(),
    )


def _build_language_servers_config(data: dict[str, Any]) -> ManagedConfigSpec:
    """Build the language-servers ManagedConfigSpec from YAML dict."""
    return ManagedConfigSpec(
        config_path=data["config_path"],
        reader=resolve_ref(data["reader"]),
        writer=resolve_ref(data["writer"]),
        remover=resolve_ref(data["remover"]),
        format=data.get("format", ""),
    )


def _build_model_config(data: dict[str, Any]) -> ManagedConfigSpec:
    """Build the model-endpoints ManagedConfigSpec from YAML dict (MO02)."""
    return ManagedConfigSpec(
        config_path=data["config_path"],
        reader=resolve_ref(data["reader"]),
        writer=resolve_ref(data["writer"]),
        remover=resolve_ref(data["remover"]),
        format=data.get("format", ""),
        refresh_mode=data.get("refresh_mode", "none"),
        reload_fn=resolve_ref(data["reload_fn"]) if "reload_fn" in data else None,
    )


def _build_plugin_config(data: dict[str, Any]) -> ManagedConfigSpec:
    """Build the plugin-entry ManagedConfigSpec from YAML dict (MA20)."""
    return ManagedConfigSpec(
        config_path=data["config_path"],
        reader=resolve_ref(data["reader"]),
        writer=resolve_ref(data["writer"]),
        remover=resolve_ref(data["remover"]),
        format=data.get("format", ""),
        refresh_mode=data.get("refresh_mode", "none"),
    )


def _build_hooks_config(data: dict[str, Any]) -> ManagedConfigSpec:
    """Build the managed-hooks ManagedConfigSpec from YAML dict (MA26)."""
    return ManagedConfigSpec(
        config_path=data["config_path"],
        reader=resolve_ref(data["reader"]),
        writer=resolve_ref(data["writer"]),
        remover=resolve_ref(data["remover"]),
        format=data.get("format", ""),
        refresh_mode=data.get("refresh_mode", "none"),
    )


def _build_session_surfaces(
    data: list[dict[str, Any]],
) -> tuple[SessionSurfaceDeclaration, ...]:
    """Build session-surface declarations from a YAML list.

    Each entry is keyed by surface_id and version_constraint; all enum fields
    are validated against foundation enums. The adapter_ref stays as a raw
    dotted-path string (not resolved).

    Raises:
        AudiaGenticError: on structurally invalid or duplicate entries.
    """
    if not isinstance(data, list):
        raise AudiaGenticError(
            code="VAL-PCAP-011",
            kind="providers",
            message="session_surfaces must be a list",
        )

    _REQUIRED_SURFACE_FIELDS = {"surface_id", "version_constraint"}
    _ALL_SURFACE_FIELDS = {
        "surface_id",
        "version_constraint",
        "identity_operations",
        "ownership_modes",
        "mapping_facts",
        "controls",
        "lifecycle_source",
        "lifecycle_installation",
        "correlation_id_supported",
        "event_ordering_guaranteed",
        "source_idempotency",
        "content_channels",
        "validation_state",
        "effective_level",
        "platforms",
        "adapter_ref",
    }

    declarations: list[SessionSurfaceDeclaration] = []
    for item in data:
        if not isinstance(item, dict):
            raise AudiaGenticError(
                code="VAL-PCAP-011",
                kind="providers",
                message="each session-surface entry must be a mapping",
            )
        unknown_fields = sorted(set(item) - _ALL_SURFACE_FIELDS)
        if unknown_fields:
            raise AudiaGenticError(
                code="VAL-PCAP-011",
                kind="providers",
                message="unknown session-surface fields",
                details={"fields": unknown_fields},
            )
        missing = _REQUIRED_SURFACE_FIELDS - set(item.keys())
        if missing:
            raise AudiaGenticError(
                code="VAL-PCAP-011",
                kind="providers",
                message="session-surface requires surface_id and version_constraint",
                details={"missing": sorted(missing)},
            )

        # --- identity_operations (mapping of string→string → enum→enum) ---
        raw_identity_ops = item.get("identity_operations") or {}
        if not isinstance(raw_identity_ops, dict):
            raise AudiaGenticError(
                code="VAL-PCAP-011",
                kind="providers",
                message="identity_operations must be a mapping",
            )
        identity_operations: dict[SessionIdentityOperation, ControlSupport] = {}
        for k_str, v_str in raw_identity_ops.items():
            k_enum = _parse_enum(k_str, _SURFACE_IDENTITY_OP_VALUES,
                                 _SURFACE_IDENTITY_OP_MAP, "identity_operation")
            v_enum = _parse_enum(v_str, _CONTROL_SUPPORT_VALUES,
                                 _CONTROL_SUPPORT_MAP, "control_support")
            identity_operations[k_enum] = v_enum

        # --- ownership_modes ---
        raw_ownership = item.get("ownership_modes") or []
        if not isinstance(raw_ownership, list):
            raise AudiaGenticError(
                code="VAL-PCAP-011",
                kind="providers",
                message="ownership_modes must be a list",
            )
        ownership_modes = tuple(
            _parse_enum(v, _OWNERSHIP_MODE_VALUES,
                        _OWNERSHIP_MODE_MAP, "ownership_mode")
            for v in raw_ownership
        )

        # --- mapping_facts ---
        raw_mapping_facts = item.get("mapping_facts")
        if raw_mapping_facts is None:
            mapping_facts = SessionMappingFacts()
        elif isinstance(raw_mapping_facts, dict):
            mapping_facts = SessionMappingFacts(
                ref_scope=raw_mapping_facts.get("ref_scope", "unknown"),
                ref_namespace=raw_mapping_facts.get("ref_namespace", "provider-session-ref"),
                requires_same_project=raw_mapping_facts.get("requires_same_project", True),
                requires_same_execution_context=raw_mapping_facts.get(
                    "requires_same_execution_context", True),
                concurrent_attachments=raw_mapping_facts.get("concurrent_attachments", False),
                attach_while_turn_active=raw_mapping_facts.get("attach_while_turn_active", False),
                share_existing=raw_mapping_facts.get("share_existing", False),
                replace_existing=raw_mapping_facts.get("replace_existing", False),
            )
        else:
            raise AudiaGenticError(
                code="VAL-PCAP-011",
                kind="providers",
                message="mapping_facts must be a mapping or absent",
            )

        # --- controls (mapping of string→string → enum→enum) ---
        raw_controls = item.get("controls") or {}
        if not isinstance(raw_controls, dict):
            raise AudiaGenticError(
                code="VAL-PCAP-011",
                kind="providers",
                message="controls must be a mapping",
            )
        controls: dict[SessionControlAction, ControlSupport] = {}
        for k_str, v_str in raw_controls.items():
            k_enum = _parse_enum(k_str, _CONTROL_ACTION_VALUES,
                                 _CONTROL_ACTION_MAP, "control_action")
            v_enum = _parse_enum(v_str, _CONTROL_SUPPORT_VALUES,
                                 _CONTROL_SUPPORT_MAP, "control_support")
            controls[k_enum] = v_enum

        # --- lifecycle fields ---
        lifecycle_source = _parse_enum(
            item.get("lifecycle_source", "none"),
            _LIFECYCLE_SOURCE_VALUES,
            _LIFECYCLE_SOURCE_MAP, "lifecycle_source",
        )
        lifecycle_installation = _parse_enum(
            item.get("lifecycle_installation", "none"),
            _LIFECYCLE_INSTALLATION_VALUES,
            _LIFECYCLE_INSTALLATION_MAP, "lifecycle_installation",
        )

        # --- content_channels ---
        raw_channels = item.get("content_channels") or []
        if not isinstance(raw_channels, list):
            raise AudiaGenticError(
                code="VAL-PCAP-011",
                kind="providers",
                message="content_channels must be a list",
            )
        content_channels: list[ContentChannelCapability] = []
        for ch in raw_channels:
            if not isinstance(ch, dict) or "channel" not in ch:
                raise AudiaGenticError(
                    code="VAL-PCAP-011",
                    kind="providers",
                    message="content channel entry requires 'channel'",
                )
            ch_id = _parse_enum(
                ch["channel"], _CONTENT_CHANNEL_VALUES,
                _CONTENT_CHANNEL_MAP, "content_channel_id",
            )
            content_channels.append(
                ContentChannelCapability(
                    channel=ch_id,
                    max_bytes=int(ch.get("max_bytes", 0)),
                    max_events=int(ch.get("max_events", 0)),
                )
            )

        # --- validation / effective_level ---
        validation_state = _parse_enum(
            item.get("validation_state", "declared"),
            _VALIDATION_STATE_VALUES,
            _VALIDATION_STATE_MAP, "validation_state",
        )
        effective_level = _parse_enum(
            item.get("effective_level", "O0"),
            _EFFECTIVE_LEVEL_VALUES,
            _EFFECTIVE_LEVEL_MAP, "effective_level",
        )

        # --- platforms ---
        raw_platforms = item.get("platforms") or []
        if not isinstance(raw_platforms, list):
            raise AudiaGenticError(
                code="VAL-PCAP-011",
                kind="providers",
                message="platforms must be a list",
            )
        platforms: list[PlatformEvidence] = []
        for pe in raw_platforms:
            if not isinstance(pe, dict) or "platform" not in pe:
                raise AudiaGenticError(
                    code="VAL-PCAP-011",
                    kind="providers",
                    message="platform entry requires 'platform'",
                )
            pe_validation = _parse_enum(
                pe.get("validation_state", "declared"),
                _VALIDATION_STATE_VALUES,
                _VALIDATION_STATE_MAP, "platform_validation_state",
            )
            pe_effective = _parse_enum(
                pe.get("effective_level", "O0"),
                _EFFECTIVE_LEVEL_VALUES,
                _EFFECTIVE_LEVEL_MAP, "platform_effective_level",
            )
            platforms.append(
                PlatformEvidence(
                    platform=str(pe["platform"]),
                    tool_version=str(pe.get("tool_version", "")),
                    probe_artifact=str(pe.get("probe_artifact", "")),
                    validation_state=pe_validation,
                    effective_level=pe_effective,
                )
            )

        declarations.append(
            SessionSurfaceDeclaration(
                surface_id=str(item["surface_id"]),
                version_constraint=str(item["version_constraint"]),
                identity_operations=identity_operations,
                ownership_modes=ownership_modes,
                mapping_facts=mapping_facts,
                controls=controls,
                lifecycle_source=lifecycle_source,
                lifecycle_installation=lifecycle_installation,
                correlation_id_supported=bool(item.get("correlation_id_supported", False)),
                event_ordering_guaranteed=bool(item.get("event_ordering_guaranteed", False)),
                source_idempotency=bool(item.get("source_idempotency", False)),
                content_channels=tuple(content_channels),
                validation_state=validation_state,
                effective_level=effective_level,
                platforms=tuple(platforms),
                adapter_ref=str(item["adapter_ref"]).strip() if item.get("adapter_ref") else None,
            )
        )

    # Cross-entry validation
    _validate_declarations(declarations)
    return tuple(declarations)


# Flat descriptor field -> (catalogue kind id, cardinality). A data table, not a
# branch ladder: derives the unified capabilities view from the legacy flat
# fields so consumers can read descriptor.capabilities before providers migrate
# to a `capabilities:` block (PC02 transitional bridge). Mechanism values are the
# already-typed flat field objects.
_FLAT_CAPABILITY_MAP: tuple[tuple[str, str, str], ...] = (
    ("cli_install", "cli-install", "single"),
    ("mcp_config", "mcp-config", "single"),
    ("hooks_config", "hook-config", "single"),
    ("model_config", "model-config", "single"),
    ("plugin_config", "plugin-config", "single"),
    ("language_servers_config", "lsp-config", "single"),
    ("fetch_catalog_fn", "model-catalog-refresh", "single"),
    ("on_lsp_enabled", "lsp-self-support", "single"),
    ("skill_surface_path", "surface-skill", "single"),
    ("instruction_file", "surface-instruction", "single"),
    ("surfaces", "surface-render", "single"),
    ("host_capabilities", "host-extension", "list"),
    ("agent_files", "file-agent", "list"),
)


# Flat YAML keys whose parsed values are consumed into `capabilities` and NOT
# stored as descriptor fields (they no longer exist on ProviderDescriptor).
_FLAT_DESCRIPTOR_KEYS: frozenset[str] = frozenset(
    {attr for attr, _kind, _card in _FLAT_CAPABILITY_MAP}
    | {"permissions", "supported_connectors", "capability_facts", "automation_capabilities"}
)


def _capabilities_from_values(values: dict[str, Any]) -> tuple[Capability, ...]:
    """Project parsed flat block values into the unified capabilities list.

    Transitional: providers still declare flat YAML blocks; this consumes their
    parsed (typed) values into `capabilities` so the descriptor exposes one shape
    and the flat fields can be dropped. Deleted once providers author
    `capabilities:` directly.
    """
    out: list[Capability] = [
        Capability(kind="perm-declaration", mechanism=values.get("permissions") or ProviderPermissions())
    ]
    for attr, kind, card in _FLAT_CAPABILITY_MAP:
        value = values.get(attr)
        if not value:
            continue
        if card == "list":
            out.extend(Capability(kind=kind, mechanism=item) for item in value)
        else:
            out.append(Capability(kind=kind, mechanism=value))
    if values.get("supported_connectors"):
        out.append(Capability(kind="model-connectors", mechanism=values["supported_connectors"]))
    return tuple(out)


def _construct_provider_descriptor(**values: Any) -> ProviderDescriptor:
    authored = values.pop("capabilities", None)
    capabilities = tuple(authored) if authored else _capabilities_from_values(values)
    for key in _FLAT_DESCRIPTOR_KEYS:
        values.pop(key, None)
    descriptor = ProviderDescriptor(capabilities=capabilities, **values)
    if descriptor.execution_isolation_tier not in {
        "full-isolation",
        "partial-isolation",
        "no-isolation",
    }:
        raise AudiaGenticError(
            code="VAL-PCAP-010",
            kind="providers",
            message=(
                "execution_isolation_tier must be full-isolation, "
                "partial-isolation, or no-isolation"
            ),
            details={
                "provider_id": descriptor.provider_id,
                "execution_isolation_tier": descriptor.execution_isolation_tier,
            },
        )
    if descriptor.mcp_launch_isolation_tier not in {"exact", "additive", "unsupported"}:
        raise AudiaGenticError(
            code="VAL-PCAP-011",
            kind="providers",
            message="mcp_launch_isolation_tier must be exact, additive, or unsupported",
            details={
                "provider_id": descriptor.provider_id,
                "mcp_launch_isolation_tier": descriptor.mcp_launch_isolation_tier,
            },
        )
    validate_provider_capability_facts(descriptor)
    validate_automation_capabilities(descriptor.automation_capabilities)
    from .session_surface_declarations import validate_session_surface_declarations
    validate_session_surface_declarations(descriptor.session_surfaces)
    return descriptor


# Provider descriptor field specification
PROVIDER_SPEC = DescriptorSpec(constructor=_construct_provider_descriptor)

PROVIDER_SPEC.add("provider_id", yaml_key="provider_id", kind="data", required=True)
PROVIDER_SPEC.add("display_name", yaml_key="display_name", kind="data", required=True)
PROVIDER_SPEC.add("description", yaml_key="description", kind="data", default="")
PROVIDER_SPEC.add("url", yaml_key="url", kind="data", default="")
PROVIDER_SPEC.add("prompt_aliases", yaml_key="prompt_aliases", kind="data", default=tuple(), converter=_list_to_tuple)
PROVIDER_SPEC.add("cli_probe", yaml_key="cli_probe", kind="data", default=None)
PROVIDER_SPEC.add("cli_install", yaml_key="cli_install", kind="nested", builder=_build_cli_install, default=None)
PROVIDER_SPEC.add("host_capabilities", yaml_key="host_capabilities", kind="nested", builder=_build_host_capabilities, default=tuple())
PROVIDER_SPEC.add("capability_facts", yaml_key="capability_facts", kind="nested", builder=_build_capability_facts, default=tuple())
PROVIDER_SPEC.add("capabilities", yaml_key="capabilities", kind="nested", builder=_build_capabilities, default=tuple())
PROVIDER_SPEC.add("execution_isolation_tier", yaml_key="execution_isolation_tier", kind="data", required=True)
PROVIDER_SPEC.add("mcp_launch_isolation_tier", yaml_key="mcp_launch_isolation_tier", kind="data", default="unsupported")
PROVIDER_SPEC.add("automation_capabilities", yaml_key="automation_capabilities", kind="nested", builder=_build_automation_capabilities, default=tuple())
PROVIDER_SPEC.add("permissions", yaml_key="permissions", kind="nested", builder=_build_permissions, default=ProviderPermissions())
PROVIDER_SPEC.add("agent_files", yaml_key="agent_files", kind="nested", builder=_build_agent_files, default=tuple())
PROVIDER_SPEC.add("access_mode", yaml_key="access_mode", kind="data", default="cli")
PROVIDER_SPEC.add("skill_surface_path", yaml_key="skill_surface_path", kind="data", default=None)
PROVIDER_SPEC.add("instruction_file", yaml_key="instruction_file", kind="data", default=None)
PROVIDER_SPEC.add("fetch_catalog_fn", yaml_key="fetch_catalog_fn", kind="ref", default=None)
PROVIDER_SPEC.add("mcp_config", yaml_key="mcp_config", kind="nested", builder=_build_mcp_config, default=None)
PROVIDER_SPEC.add("plugin_config", yaml_key="plugin_config", kind="nested", builder=_build_plugin_config, default=None)
PROVIDER_SPEC.add("language_servers_config", yaml_key="language_servers_config", kind="nested", builder=_build_language_servers_config, default=None)
PROVIDER_SPEC.add("hooks_config", yaml_key="hooks_config", kind="nested", builder=_build_hooks_config, default=None)
PROVIDER_SPEC.add("model_config", yaml_key="model_config", kind="nested", builder=_build_model_config, default=None)
PROVIDER_SPEC.add("model_entry_renderer", yaml_key="model_entry_renderer", kind="ref", default=None)
PROVIDER_SPEC.add("supported_connectors", yaml_key="supported_connectors", kind="data", default=tuple(), converter=_list_to_tuple)
PROVIDER_SPEC.add("vendor_key_injection", yaml_key="vendor_key_injection", kind="data", default=dict())
PROVIDER_SPEC.add("on_lsp_enabled", yaml_key="on_lsp_enabled", kind="ref", default=None)
PROVIDER_SPEC.add("lsp_support_probe", yaml_key="lsp_support_probe", kind="ref", default=None)
PROVIDER_SPEC.add("receive_lsp_mcp", yaml_key="receive_lsp_mcp", kind="data", default=True)
PROVIDER_SPEC.add("surfaces", yaml_key="surfaces", kind="data", default=None)
PROVIDER_SPEC.add("launches", yaml_key="launches", kind="data", default=dict())
PROVIDER_SPEC.add("execution", yaml_key="execution", kind="data", default=None)
PROVIDER_SPEC.add("interactive", yaml_key="interactive", kind="data", default=None)
PROVIDER_SPEC.add("acp", yaml_key="acp", kind="data", default=None)
PROVIDER_SPEC.add("deprecated", yaml_key="deprecated", kind="data", default=False)
PROVIDER_SPEC.add("annotations", yaml_key="annotations", kind="data", default=dict())
PROVIDER_SPEC.add("session_surfaces", yaml_key="session_surfaces", kind="nested", builder=_build_session_surfaces, default=tuple())


def provider_factory(data: dict[str, Any]) -> ProviderDescriptor:
    """Build a ProviderDescriptor from resolved YAML data.

    This function is used by the generic loader to construct the typed
    descriptor from the resolved field values.
    """
    return PROVIDER_SPEC.build(data)


def load_provider_descriptor(path: Path) -> ProviderDescriptor:
    """Load a ProviderDescriptor from a YAML file.

    Args:
        path: Path to the provider YAML file.

    Returns:
        Constructed ProviderDescriptor instance.
    """
    return load_descriptor(path, PROVIDER_SPEC)


def load_providers_from_directory(directory: Path) -> dict[str, ProviderDescriptor]:
    """Load all provider descriptors from a YAML directory.

    Args:
        directory: Path to directory containing provider YAML files.

    Returns:
        Dict mapping provider_id to ProviderDescriptor.
    """
    providers: dict[str, ProviderDescriptor] = {}
    for path in iter_descriptor_files(directory):
        descriptor = load_descriptor(path, PROVIDER_SPEC)
        if descriptor.provider_id in providers:
            raise AudiaGenticError(
                code="VAL-PCAP-006",
                kind="providers",
                message=f"duplicate provider descriptor id: {descriptor.provider_id}",
                details={"provider-id": descriptor.provider_id},
            )
        providers[descriptor.provider_id] = descriptor
    return providers


def get_providers_config_dir() -> Path:
    """Return the path to the provider config directory.

    Returns:
        Path to src/audiagentic/config/providers/
    """
    return get_package_providers_config_dir()
