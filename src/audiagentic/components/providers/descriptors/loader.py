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

from .automation_capabilities import validate_automation_capabilities
from .base import (
    AgentFile,
    Capability,
    CapabilityEvidence,
    CliInstallRecipe,
    HostCapability,
    ModelsSpec,
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


def _build_models_spec(data: dict[str, Any]) -> ModelsSpec:
    """Build the compound `models` mechanism from YAML dict.

    ``credentials`` values are secrets.py reference strings (``scheme:locator``,
    e.g. ``"env:OPENAI_API_KEY"``) — validated against the shared grammar at
    load time so a malformed reference fails at descriptor load, not at first
    use.
    """
    from audiagentic.components.providers.services.secrets import parse_secret_ref

    credentials = data.get("credentials") or {}
    for vendor_id, ref in credentials.items():
        try:
            parse_secret_ref(ref)
        except AudiaGenticError as exc:
            raise AudiaGenticError(
                code="VAL-PCAP-009",
                kind="providers",
                message=f"models.credentials.{vendor_id}: {exc.message}",
                details={"vendor_id": vendor_id, "value": ref},
            ) from exc

    store_data = data.get("store")
    return ModelsSpec(
        store=_build_managed_config_spec(store_data) if store_data else None,
        entry_renderer=resolve_ref(data["entry_renderer"]) if "entry_renderer" in data else None,
        refresh=resolve_ref(data["refresh"]) if "refresh" in data else None,
        connectors=tuple(data.get("connectors") or ()),
        credentials=dict(credentials),
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
    if mechanism_schema == "model-spec":
        return _build_models_spec(raw)
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
            evidence_data = item.get("evidence")
            evidence = (
                CapabilityEvidence(
                    note=evidence_data.get("note"), source=evidence_data.get("source")
                )
                if evidence_data
                else None
            )
            out.append(
                Capability(
                    kind=kind,
                    mechanism=_project_mechanism(kind_obj.mechanism_schema, item.get("mechanism")),
                    modes=tuple(item.get("modes", ())),
                    evidence=evidence,
                )
            )
    return tuple(out)


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


def _construct_provider_descriptor(**values: Any) -> ProviderDescriptor:
    descriptor = ProviderDescriptor(**values)
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


# Provider descriptor field specification. Retired top-level keys (cli_install,
# mcp_config, model_config, plugin_config, hooks_config, language_servers_config,
# host_capabilities, capability_facts, automation_capabilities, permissions,
# agent_files, skill_surface_path, instruction_file, surfaces, fetch_catalog_fn,
# on_lsp_enabled, supported_connectors, model_entry_renderer, vendor_key_injection)
# are NOT registered — DescriptorSpec.load rejects any unregistered key
# (VAL-DESC-004), so a provider still declaring one fails loudly rather than
# being silently dropped. Declare them under `capabilities:` instead
# (PC01/PC03/PC04, provider-capability-model). model_entry_renderer and
# vendor_key_injection fold into the `models` capability's compound mechanism.
PROVIDER_SPEC = DescriptorSpec(constructor=_construct_provider_descriptor)

PROVIDER_SPEC.add("provider_id", yaml_key="provider_id", kind="data", required=True)
PROVIDER_SPEC.add("display_name", yaml_key="display_name", kind="data", required=True)
PROVIDER_SPEC.add("description", yaml_key="description", kind="data", default="")
PROVIDER_SPEC.add("url", yaml_key="url", kind="data", default="")
PROVIDER_SPEC.add("prompt_aliases", yaml_key="prompt_aliases", kind="data", default=tuple(), converter=_list_to_tuple)
PROVIDER_SPEC.add("cli_probe", yaml_key="cli_probe", kind="data", default=None)
PROVIDER_SPEC.add("capabilities", yaml_key="capabilities", kind="nested", builder=_build_capabilities, default=tuple())
PROVIDER_SPEC.add("execution_isolation_tier", yaml_key="execution_isolation_tier", kind="data", required=True)
PROVIDER_SPEC.add("mcp_launch_isolation_tier", yaml_key="mcp_launch_isolation_tier", kind="data", default="unsupported")
PROVIDER_SPEC.add("access_mode", yaml_key="access_mode", kind="data", default="cli")
PROVIDER_SPEC.add("lsp_support_probe", yaml_key="lsp_support_probe", kind="ref", default=None)
PROVIDER_SPEC.add("receive_lsp_mcp", yaml_key="receive_lsp_mcp", kind="data", default=True)
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
