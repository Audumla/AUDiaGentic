"""Load and register ComponentDescriptors from YAML config files."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import (
    AudiaGenticError,
    make_error_factory,
)
from audiagentic.foundation.io import load_yaml_file

_component_error: Any = make_error_factory("VAL", "COMP", "components")

from .base import (
    SCOPE_HARNESS,
    SCOPE_PROJECT,
    ComponentDescriptor,
    ComponentFile,
    ExternalMcpServerDeclaration,
    HarnessInstruction,
    McpServerDeclaration,
)
from .hooks import initialize_lifecycle_hook_dispatch
from .registry import register

logger = logging.getLogger(__name__)

# Resolve relative to the installed package — works in both editable installs and wheels.
_PACKAGE_DIR = Path(__file__).resolve().parents[2]  # audiagentic/
_COMPONENTS_CONFIG_DIR = _PACKAGE_DIR / "config" / "components"
_ALL_COMPONENT_CONFIG_DIRS = [_COMPONENTS_CONFIG_DIR]

_registration_cache: dict[frozenset[str], list[ComponentDescriptor]] = {}

# CP05: Track which profile was active on first registration to prevent mid-process switches.
_active_profile_on_first_register: str | None = None


def _reset_registration_cache() -> None:
    """Invalidate the register_all_components cache guard and reset profile tracking.

    Called by test fixtures that clear registry state, and by profile switching code (CP05).
    Without this, a fixture that clears the underlying registries would have the cache
    short-circuit and leave them empty on subsequent lazy bootstrap calls.
    Also resets _active_profile_on_first_register so tests can re-register with a
    different profile after explicit cache clearing.
    """
    _registration_cache.clear()
    global _active_profile_on_first_register
    _active_profile_on_first_register = None


def _get_component_config_dirs() -> list[Path]:
    """Resolve component config directories from override sources.

    Delegates to the shared resolver in foundation/paths/names.py
    (AUDIAGENTIC_COMPONENT_CONFIG_DIRS env var, then package defaults) so
    descriptor discovery and error-resolution loading share one source.
    """
    from audiagentic.foundation.paths.names import get_component_config_dirs

    return get_component_config_dirs()


def _build_files_tuple(raw_files: list[dict]) -> tuple[ComponentFile, ...]:
    """Build ComponentFile tuple from raw YAML file entries."""
    return tuple(
        ComponentFile(
            rel_path=f["path"],
            lifecycle=f["lifecycle"],
            recursive=bool(f.get("recursive", False)),
            description=f.get("description", ""),
        )
        for f in (raw_files or [])
    )


def component_yaml_path(component_id: str) -> Path:
    """Return the config YAML path for a component in the unified components dir."""
    for base in _ALL_COMPONENT_CONFIG_DIRS:
        candidate = base / f"{component_id}.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no component config found for '{component_id}'")


def _require_propagate(ms: dict, path: Path) -> str:
    if "propagate" not in ms:
        logger.warning(
            "MCP server %r in %s missing required 'propagate' field — defaulting to 'audiagentic'",
            ms.get("name", "<unknown>"),
            path.name,
        )
        return "audiagentic"
    return ms["propagate"]


def register_from_yaml(path: Path) -> ComponentDescriptor:
    """Parse a single component config YAML and register the descriptor."""
    data = load_yaml_file(path)
    if data.get("type") != "component":
        raise _component_error(
            1,
            f"{path.name}: expected type=component, got {data.get('type')}",
            path=str(path),
            expected="component",
            actual=data.get("type"),
        )
    component_id = data.get("id")
    if not isinstance(component_id, str) or not component_id:
        raise _component_error(2, f"{path.name}: missing or empty id", path=str(path), field="id")
    files = _build_files_tuple(data.get("files") or [])

    # Default detection-marker from id when not explicitly declared
    raw_scope = data.get("scope", SCOPE_PROJECT)
    if not data.get("detection-marker"):
        if raw_scope == SCOPE_HARNESS:
            data["detection-marker"] = f"components/{component_id}.yaml"
        else:
            data["detection-marker"] = f".audiagentic/components/{component_id}.yaml"

    # Synthesize marker ComponentFile when no file entry matches the detection-marker
    detected_marker = data["detection-marker"]
    if not any(f.get("path") == detected_marker for f in (data.get("files") or [])):
        marker_file = {
            "path": detected_marker,
            "lifecycle": "create-if-missing",
            "description": "Installation marker",
        }
        data.setdefault("files", []).insert(0, marker_file)
        files = _build_files_tuple(data["files"])
    mcp_servers = tuple(
        McpServerDeclaration(
            name=ms["name"],
            module=ms["module"],
            managed_id=ms.get("managed-id"),
            args=tuple(ms.get("args") or []),
            direct_tools=ms.get("direct-tools") or [],
            description=ms.get("description", ""),
            instructions=ms.get("instructions", ""),
            tool_descriptions=ms.get("tool-descriptions") or {},
            propagate=_require_propagate(ms, path),
        )
        for ms in (data.get("mcp-servers") or [])
    )

    external_mcp_servers = tuple(
        ExternalMcpServerDeclaration(
            name=ms["name"],
            command=ms["command"],
            managed_id=ms.get("managed-id"),
            args=tuple(ms.get("args") or []),
            env=dict(ms.get("env") or {}),
            description=ms.get("description", ""),
            instructions=ms.get("instructions", ""),
            requires=tuple(ms.get("requires") or []),
            probe=tuple(ms.get("probe") or []),
            propagate=_require_propagate(ms, path),
        )
        for ms in (data.get("external-mcp-servers") or [])
    )

    raw_harness_instructions = data.get("harness-instructions") or []
    if raw_harness_instructions:
        harness_instructions = tuple(
            HarnessInstruction(
                section=hi["section"],
                content=hi["content"],
                description=hi.get("description", ""),
                propagate=hi.get("propagate", "audiagentic"),
            )
            for hi in raw_harness_instructions
        )
    else:
        # No derived tool catalog. Per-tool definitions are component-owned and
        # advertised over MCP via `tool-descriptions`; the system prompt does not
        # carry a consolidated catalog. Components inject doctrine only by
        # supplying an explicit `harness-instructions` section.
        harness_instructions = ()

    # Core flag is determined solely by the YAML descriptor's core field
    is_core = bool(data.get("core", False))

    descriptor = ComponentDescriptor(
        type=data["type"],
        component_id=component_id,
        display_name=data.get("display-name", component_id),
        description=data.get("description", ""),
        detection_marker=data.get("detection-marker", ""),
        aliases=tuple(data.get("aliases") or []),
        files=files,
        depends_on=tuple(data.get("depends-on") or []),
        yaml_path=path,
        scope=data.get("scope", SCOPE_PROJECT),
        mcp_servers=mcp_servers,
        external_mcp_servers=external_mcp_servers,
        harness_instructions=harness_instructions,
        core=is_core,
        post_install=data.get("post-install") or None,
        lifecycle_observer=data.get("lifecycle-observer") or None,
        lifecycle_hook=data.get("lifecycle-hook") or None,
        status_hook=data.get("status-hook") or None,
        context_hook=data.get("context-hook") or None,
        context_namespace=data.get("context-namespace") or None,
        implementation_cardinality=data.get("implementation-cardinality") or None,
    )
    register(descriptor, replace=True)
    return descriptor


def register_all_components(config_dirs: list[Path] | None = None) -> list[ComponentDescriptor]:
    """Load and register every *.yaml file across all component config dirs.

    Defaults to the resolved override directories or config/components/ (top-level YAMLs only).
    Idempotent and internally cached on unchanged inputs.

    After loading descriptors, imports any declared lifecycle-observer modules so
    they self-register their event bus subscriptions.

    Profile-aware layering: when a component profile is active, the profile's
    component config directory is added alongside base directories with the
    profile layer scanned last so its descriptors overwrite base ones (last wins).
    One profile per process; switching profiles mid-process raises an error (CP05).
    """
    global _active_profile_on_first_register
    from audiagentic.foundation.components import registry as component_registry

    # CP05: Guard against cross-profile pollution
    from audiagentic.foundation.paths.names import get_active_profile

    current_profile = get_active_profile()

    if _active_profile_on_first_register is None:
        _active_profile_on_first_register = current_profile
    elif _active_profile_on_first_register != current_profile:
        raise AudiaGenticError(
            code="VAL-COMP-010",
            kind="components",
            message=(
                f"Cannot switch component profile mid-process: "
                f"first registration used {_active_profile_on_first_register!r}, "
                f"now requested {current_profile!r}. "
                f"One profile per process; restart to switch."
            ),
        )

    targets = config_dirs or _get_component_config_dirs()

    # CP04: Layer base + profile config dirs
    # When profile is active, add both profile dir AND base dirs.
    # Profile dir scanned last so its descriptors overwrite base ones (last wins).
    if current_profile and not config_dirs:
        from audiagentic.foundation.paths.names import (
            resolve_profile_component_config_dir,
        )
        from audiagentic.foundation.paths.project import find_project_root

        # Profiles are project-scoped (.audiagentic/<profile>/components/), so
        # they need the real project root — walk up from cwd to the marker
        # directory, matching how the rest of the app locates the project.
        # Resolved CP13: launcher propagates AUDIAGENTIC_REPO_ROOT when --project
        # is given, so find_project_root() returns the correct root. If the env var
        # is not set (direct invocation outside launcher), falls back to cwd walk-up.
        project_root = find_project_root() or Path.cwd()
        profile_dir = resolve_profile_component_config_dir(
            project_root.resolve(), current_profile
        )
        targets = list(targets) + [profile_dir]

    cache_key = frozenset(str(p.resolve()) for p in targets)

    if cache_key in _registration_cache:
        return _registration_cache[cache_key]
    descriptors = []
    # CP04: Track source layer (config dir) for each descriptor to distinguish
    # same-layer vs cross-layer duplicates.
    descriptor_layers: list[tuple[ComponentDescriptor, str]] = []
    feature_descriptor_types = {"feature", "implementation", "binding"}
    component_registry._set_default_loading(True)
    try:
        for target in targets:
            resolved_target = str(target.resolve())
            for path in sorted(target.resolve().glob("*.yaml")):
                data = load_yaml_file(path)
                if data.get("type") in feature_descriptor_types:
                    from audiagentic.foundation.features.loader import (
                        register_from_yaml as register_feature_from_yaml,
                    )

                    register_feature_from_yaml(path)
                    continue
                desc = register_from_yaml(path)
                descriptors.append(desc)
                descriptor_layers.append((desc, resolved_target))

            for path in sorted(target.resolve().glob("**/*.yaml")):
                if path.parent == target.resolve():
                    continue
                data = load_yaml_file(path)
                if data.get("type") in feature_descriptor_types:
                    from audiagentic.foundation.features.loader import (
                        register_from_yaml as register_feature_from_yaml,
                    )

                    register_feature_from_yaml(path)
    finally:
        component_registry._set_default_loading(False)

    # Validate data-driven constraints (duplicates, deps) before observers import.
    _validate_descriptors_data(descriptor_layers)

    # Import lifecycle observers so they self-register their event bus subscriptions.
    for descriptor in descriptors:
        if descriptor.lifecycle_observer:
            try:
                __import__(descriptor.lifecycle_observer)
            except Exception:
                logger.warning("Failed to import lifecycle observer for %s", descriptor.component_id, exc_info=True)

    _validate_descriptors_contributions(descriptors)
    initialize_lifecycle_hook_dispatch()

    from audiagentic.foundation.contracts.error_resolutions import (
        load_all_error_resolutions,
    )

    load_all_error_resolutions(targets)

    # Initialize I18n translation catalogs after error resolutions
    try:
        from audiagentic.foundation.i18n import initialize as _i18n_init

        _i18n_init(targets)
    except ImportError:
        logger.warning("I18n module not available — translation lookups will return keys")

    _registration_cache[cache_key] = descriptors
    return descriptors


def _validate_descriptors_data(
    descriptor_layers: list[tuple[ComponentDescriptor, str]],
) -> None:
    """Validate data-driven constraints (duplicates, depends-on references).

    Runs after ALL descriptors are loaded so depends-on references can be
    checked against the full set rather than an incrementally built partial set.

    Cross-layer duplicate handling (CP04): only raises hard errors for same-layer
    duplicate IDs. Cross-layer duplicates (e.g., profile overriding base) use
    "last wins" semantics — the later layer's descriptor overwrites the earlier one
    via the registry, so validation allows them silently.
    """
    # Track (component_id -> source_layer) for same-layer duplicate detection
    seen: dict[str, str] = {}
    same_layer_duplicates: set[str] = set()
    descriptors = [desc for desc, _ in descriptor_layers]

    for descriptor, layer in descriptor_layers:
        cid = descriptor.component_id
        if cid in seen:
            if seen[cid] == layer:
                # Same-layer duplicate — hard error
                same_layer_duplicates.add(cid)
            # else: cross-layer duplicate — allowed (last wins via registry overwrite)
        seen[cid] = layer

    if same_layer_duplicates:
        raise _component_error(
            3,
            f"duplicate component ids loaded: {', '.join(sorted(same_layer_duplicates))}",
            duplicate_ids=sorted(same_layer_duplicates),
        )

    loaded_ids = {d.component_id for d in descriptors}

    for descriptor in descriptors:
        for dep in descriptor.depends_on:
            if dep not in loaded_ids:
                raise _component_error(
                    4,
                    f"component '{descriptor.component_id}' depends on unknown component '{dep}'",
                    component=descriptor.component_id,
                    dependency=dep,
                )


def _validate_config_reference(config_path: str, component_id: str) -> str | None:
    """Validate that a config reference resolves to an existing file.

    Returns None if valid, or a warning message if the file does not exist.
    Config references are relative to the package config directory.
    """
    # Config references are relative to the package config dir (parent of components/)
    from audiagentic.foundation.paths.names import get_package_config_dir

    config_base = get_package_config_dir()
    candidate = config_base / config_path
    if not candidate.exists():
        return (
            f"Component {component_id!r}: config reference {config_path!r} "
            f"does not exist (resolved to {candidate})"
        )
    return None


def _validate_descriptors_contributions(descriptors: list[ComponentDescriptor]) -> None:
    """Validate contribution config references.

    Runs after descriptors are loaded. Config-reference validation now runs
    for every component's descriptor regardless of whether the providers
    component is installed (previous capability-gated path silently skipped
    validation when providers was absent).
    """
    for descriptor in descriptors:
        if not descriptor.yaml_path or not descriptor.yaml_path.exists():
            continue
        data = load_yaml_file(descriptor.yaml_path)
        raw_list = data.get("contributions") or data.get("surface-contributions") or []
        for raw in raw_list:
            if not isinstance(raw, dict):
                continue
            config_ref = raw.get("config")
            if isinstance(config_ref, str):
                warning = _validate_config_reference(config_ref, descriptor.component_id)
                if warning:
                    logger.warning(warning)
