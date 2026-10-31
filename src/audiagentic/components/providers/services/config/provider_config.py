"""Provider config loading and validation helpers."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from audiagentic.foundation.config.merge import merged
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.observations import (
    clear_observation,
    get_observation,
    observed_keys,
    record_observation,
)
from audiagentic.foundation.features.state import (
    ENABLED_PREFIX,
    get_component_state,
    get_implementation_state,
    set_implementation_state,
)

from ...descriptors.target import ProviderTarget, base_provider_id, provider_config_error

_COMPONENT_ID = "providers"


def validate_provider_config(payload: dict[str, Any]) -> list[str]:
    issues = validate_with_schema("provider-config", payload)
    providers = payload.get("providers", {})
    if isinstance(providers, dict):
        for provider_id, provider_cfg in providers.items():
            issues.extend(validate_prompt_surface(provider_id, provider_cfg))
    return sorted(issues)


def validate_prompt_surface(provider_id: str, provider_cfg: dict[str, Any]) -> list[str]:
    """Return human-readable prompt-surface contract issues for one provider."""
    prompt_surface = provider_cfg.get("prompt-surface")
    if prompt_surface is None:
        return []
    if not isinstance(prompt_surface, dict):
        return [f"{provider_id}: prompt-surface must be an object"]

    issues: list[str] = []
    enabled = prompt_surface.get("enabled", False)
    cli_mode = prompt_surface.get("cli-mode")
    vscode_mode = prompt_surface.get("vscode-mode")

    if enabled:
        supported_modes = [
            mode for mode in (cli_mode, vscode_mode) if mode and mode != "unsupported"
        ]
        if not supported_modes:
            issues.append(
                f"{provider_id}: prompt-surface.enabled requires at least one supported cli-mode or vscode-mode"
            )

    return issues


def provider_enabled_policy(project_root: Path, provider_id: str) -> str | bool:
    """``providers.<id>.enabled`` from settings: ``"auto"`` (default), ``True`` or ``False``."""
    if not project_root.is_dir():
        return "auto"
    from audiagentic.foundation.config.settings import resolve_settings_cached

    entry = (resolve_settings_cached(project_root).get("providers") or {}).get(base_provider_id(provider_id))
    return entry["enabled"] if isinstance(entry, dict) and "enabled" in entry else "auto"


def _persisted_enabled(project_root: Path, provider_id: str) -> bool | None:
    """Enablement written by ``set_provider_enabled``/reconciliation, or None if never set."""
    implementations = get_component_state(project_root, _COMPONENT_ID).get(
        "implementations", {}
    )
    stored = implementations.get(base_provider_id(provider_id))
    return bool(stored["enabled"]) if isinstance(stored, dict) and "enabled" in stored else None


def provider_instance_config(project_root: Path, target: ProviderTarget, config: Any) -> Any:
    """``config`` with the target's ``providers.<id>.instances.<name>`` overlay applied.

    The overlay is merge-patched (RFC 7396) over the provider's options, inside
    its ``settings`` mapping when the provider file wraps them there. A name
    that is not configured is an error that lists the configured ones.
    """
    if target.instance is None or not isinstance(config, dict):
        return config
    from audiagentic.foundation.config.settings import resolve_settings_cached

    entry = (resolve_settings_cached(project_root).get("providers") or {}).get(target.provider_id) or {}
    instances = entry.get("instances") or {}
    if target.instance not in instances:
        raise provider_config_error(
            6, "Provider instance is not configured",
            provider=target.provider_id, instance=target.instance, configured=sorted(instances),
        )
    overlay = instances[target.instance]
    if isinstance(config.get("settings"), dict):
        return {**config, "settings": merged(config["settings"], overlay)}
    return merged(config, overlay)


def is_provider_enabled(project_root: Path, provider_id: str) -> bool:
    """Whether a provider is enabled: policy, else persisted enablement.

    ``providers.<id>.enabled`` ``true``/``false`` in settings decides outright.
    Under ``auto`` the persisted implementation state applies (written by
    ``set_provider_enabled`` and reconciliation, which also own the provider's
    generated footprint). Runtime gates use ``is_provider_usable`` instead.
    """
    policy = provider_enabled_policy(project_root, provider_id)
    if isinstance(policy, bool):
        return policy
    return bool(_persisted_enabled(project_root, provider_id))


def is_provider_usable(project_root: Path, provider_id: str) -> bool:
    """Whether a provider may run here (CFG06): enabled, or ``auto`` and observed available.

    Under ``auto`` with no persisted enablement, the provider's own availability
    check decides (CLI found, browser reachable), so a clean install needs no
    enablement step. A provider with nothing checkable stays disabled until
    enabled in settings.
    """
    policy = provider_enabled_policy(project_root, provider_id)
    if isinstance(policy, bool):
        return policy
    persisted = _persisted_enabled(project_root, provider_id)
    if persisted is not None:
        return persisted
    from audiagentic.components.providers.providers_api import check_provider_availability

    return check_provider_availability(project_root, base_provider_id(provider_id))[0] is True


def is_native_mcp_target_enabled(project_root: Path, provider_id: str) -> bool:
    """Explicit native selection works without interactive provider setup.

    Once provider state exists, its canonical disabled state suppresses exposure.
    This is a read of the existing feature authority, not another enablement map.
    """
    implementations = get_component_state(project_root, _COMPONENT_ID).get(
        "implementations", {}
    )
    state = implementations.get(provider_id)
    return state is None or bool(state.get("enabled", False))


def apply_feature_enabled_state(
    project_root: Path,
    provider_id: str,
    provider_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Return provider_cfg with a derived `enabled` injected from feature state.

    `enabled` is never persisted to provider settings files; it is computed in-memory
    consumers (status, health) from the implementation feature state.
    """
    return {**provider_cfg, "enabled": is_provider_enabled(project_root, provider_id)}


def _settings_entries(project_root: Path) -> dict[str, Any]:
    from audiagentic.foundation.config.settings import resolve_settings_cached

    entries = resolve_settings_cached(project_root).get("providers") or {}
    return entries if isinstance(entries, dict) else {}


_POLICY_ONLY_KEYS = ("enabled", "instances")
_DESCRIPTOR_KEYS = ("install-mode", "access-mode")  # facts of the provider descriptor, never configured


def _provider_options(entry: Any) -> dict[str, Any]:
    """A settings entry without the enablement policy and the instance overlays."""
    if not isinstance(entry, dict):
        return {}
    return deepcopy({key: value for key, value in entry.items() if key not in _POLICY_ONLY_KEYS})


def patch_provider_config(
    project_root: Path,
    provider_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Merge-patch one provider's options in the project settings file (``null`` removes a key)."""
    from audiagentic.foundation.config.writer import write_settings_patch

    provider_id = base_provider_id(provider_id)
    patch = {key: value for key, value in patch.items() if key not in (*_POLICY_ONLY_KEYS, *_DESCRIPTOR_KEYS)}
    # GP26 write-time guard: validate the candidate BEFORE persisting, not
    # after. For gpt-auto, the effective-config resolver (three-tier: packaged
    # defaults -> machine override -> this project overlay) is the authoritative
    # compatibility verdict -- an invalid candidate must never reach disk.
    if provider_id.startswith("gpt-auto"):
        from audiagentic.components.providers.adapters.gpt_auto.config import (
            resolve_gpt_auto_config,
        )

        candidate = merged(_provider_options(_settings_entries(project_root).get(provider_id)), patch)
        try:
            resolve_gpt_auto_config(candidate, provider_id=provider_id)
        except AudiaGenticError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AudiaGenticError(
                code="VAL-PCFG-004",
                kind="providers",
                message="provider config failed effective-config validation",
                details={"provider-id": provider_id, "error": str(exc)},
            ) from exc
    write_settings_patch("project", {"providers": {provider_id: patch}}, project_root=project_root)
    return load_provider_config(project_root)


def set_provider_enabled(project_root: Path, provider_id: str, *, enabled: bool) -> None:
    """Set provider enablement in feature state (the single source of truth).

    Routes through the foundation lifecycle so component `implementation-cardinality`
    (multi for providers — no auto-deselect) is enforced. Falls back to a direct
    state write if the implementation descriptor is not registered in this process.
    """
    from audiagentic.foundation.features.lifecycle import (
        disable_implementation,
        enable_implementation,
    )

    fn = enable_implementation if enabled else disable_implementation
    previous = get_implementation_state(project_root, _COMPONENT_ID, provider_id)
    if fn(project_root, _COMPONENT_ID, provider_id).get("ok"):
        if not enabled:
            from ..lifecycle.project_purge import purge_provider_project

            purge_provider_project(project_root, provider_id)
            set_implementation_state(
                project_root,
                _COMPONENT_ID,
                provider_id,
                ImplementationState(enabled=False, options=previous.options),
            )
        from audiagentic.foundation.event import get_bus

        from ...events import PROVIDER_STATE_CHANGED

        get_bus().publish(
            PROVIDER_STATE_CHANGED,
            {"project_root": project_root, "provider_id": provider_id, "enabled": enabled},
        )
        return
    state = get_implementation_state(project_root, _COMPONENT_ID, provider_id)
    set_implementation_state(
        project_root,
        _COMPONENT_ID,
        provider_id,
        ImplementationState(enabled=enabled, options=state.options),
    )
    if not enabled:
        from ..lifecycle.project_purge import purge_provider_project

        purge_provider_project(project_root, provider_id)
        set_implementation_state(
            project_root,
            _COMPONENT_ID,
            provider_id,
            ImplementationState(enabled=False, options=previous.options),
        )
    from audiagentic.foundation.event import get_bus

    from ...events import PROVIDER_STATE_CHANGED

    get_bus().publish(
        PROVIDER_STATE_CHANGED,
        {"project_root": project_root, "provider_id": provider_id, "enabled": enabled},
    )


_VALID_RECONCILIATION_MODES = ("auto", "allowlist", "prompt")
_DEFAULT_RECONCILIATION_POLICY: dict[str, Any] = {"mode": "auto"}
_DECIDED_KEY = "reconciliation.decided"


def _reconciliation_settings(project_root: Path) -> dict[str, Any]:
    from audiagentic.foundation.config.settings import resolve_settings_cached

    section = resolve_settings_cached(project_root).get("reconciliation")
    return section if isinstance(section, dict) else {}


def get_reconciliation_policy(project_root: Path) -> dict[str, Any]:
    """Return this project's provider reconciliation policy.

    ``reconciliation`` in settings holds the mode and the allowlist; the providers the
    operator has already been asked about are local state. Defaults to ``{"mode": "auto"}``
    (enable whatever CLI is detected) when never explicitly configured. Use
    `is_reconciliation_policy_configured` to distinguish "never set" from "explicitly set to auto".
    """
    section = _reconciliation_settings(project_root)
    if section.get("mode") not in _VALID_RECONCILIATION_MODES:
        return dict(_DEFAULT_RECONCILIATION_POLICY)
    policy: dict[str, Any] = {"mode": section["mode"]}
    if isinstance(section.get("allowed-providers"), list):
        policy["allowed-providers"] = list(section["allowed-providers"])
    decided = get_observation(project_root, _COMPONENT_ID, _DECIDED_KEY)
    if isinstance(decided, list):
        policy["decided-providers"] = list(decided)
    return policy


def is_reconciliation_policy_configured(project_root: Path) -> bool:
    """Return whether a reconciliation policy has ever been explicitly written.

    Distinct from `get_reconciliation_policy`, which always returns a usable
    policy (defaulting to auto) even when this is False.
    """
    return _reconciliation_settings(project_root).get("mode") in _VALID_RECONCILIATION_MODES


def set_reconciliation_policy(
    project_root: Path,
    *,
    mode: str,
    allowed_providers: list[str] | None = None,
    decided_providers: list[str] | None = None,
) -> dict[str, Any]:
    """Persist this project's provider reconciliation policy.

    `allowed_providers`/`decided_providers` are only kept when explicitly
    passed, so switching back to `mode="auto"` round-trips as ``{"mode":
    "auto"}`` with no stale lists left over from a prior allowlist/prompt mode.
    """
    from audiagentic.foundation.config.writer import write_settings_patch

    if mode not in _VALID_RECONCILIATION_MODES:
        raise AudiaGenticError(
            code="VAL-PCFG-002",
            kind="providers",
            message="invalid reconciliation-policy mode",
            details={"mode": mode, "allowed": list(_VALID_RECONCILIATION_MODES)},
        )
    allowed = None if allowed_providers is None else sorted(set(allowed_providers))
    write_settings_patch(
        "project", {"reconciliation": {"mode": mode, "allowed-providers": allowed}}, project_root=project_root,
    )
    if decided_providers is None:
        clear_observation(project_root, _COMPONENT_ID, _DECIDED_KEY)
    else:
        record_observation(
            project_root, _COMPONENT_ID, _DECIDED_KEY, sorted(set(decided_providers)), source="reconcile",
        )
    return get_reconciliation_policy(project_root)


def _configured_providers(project_root: Path) -> dict[str, Any]:
    """Providers with settings or local enablement state, as provider-config entries.

    ``install-mode`` and ``access-mode`` are facts of the provider descriptor, not configuration,
    so they are derived here and never written to a settings file.
    """
    from ...descriptors.registry import all_descriptors

    entries = _settings_entries(project_root)
    observed = {
        key[len(ENABLED_PREFIX):] for key in observed_keys(project_root, _COMPONENT_ID, ENABLED_PREFIX)
    }
    descriptors = all_descriptors()
    providers: dict[str, Any] = {}
    for provider_id in sorted((set(entries) | observed) & set(descriptors)):
        descriptor = descriptors[provider_id]
        providers[provider_id] = {
            "install-mode": descriptor.install_mode,
            "access-mode": descriptor.access_mode,
            **_provider_options(entries.get(provider_id)),
        }
    return providers


def load_provider_config_lenient(project_root: Path) -> dict[str, Any]:
    """Read provider config without schema validation.

    For callers that only need provider presence/enablement (resolution, reconcile
    fallback) and must tolerate partial blocks that strict validation would reject.
    """
    payload: dict[str, Any] = {"contract-version": "v1", "providers": _configured_providers(project_root)}
    if is_reconciliation_policy_configured(project_root):
        payload["reconciliation-policy"] = get_reconciliation_policy(project_root)
    return payload


def load_provider_config(project_root: Path) -> dict[str, Any]:
    payload = load_provider_config_lenient(project_root)
    payload["providers"] = {
        provider_id: apply_feature_enabled_state(project_root, provider_id, provider_cfg)
        for provider_id, provider_cfg in payload["providers"].items()
    }
    issues = validate_provider_config(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-PCFG-001",
            kind="providers",
            message="provider config failed validation",
            details={"issues": issues},
        )
    return payload
