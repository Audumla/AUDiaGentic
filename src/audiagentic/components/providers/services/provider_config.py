"""Provider config loading and validation helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import (
    get_implementation_state,
    set_implementation_state,
)
from audiagentic.foundation.io import load_yaml_file, save_yaml_file

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
        supported_modes = [mode for mode in (cli_mode, vscode_mode) if mode and mode != "unsupported"]
        if not supported_modes:
            issues.append(
                f"{provider_id}: prompt-surface.enabled requires at least one supported cli-mode or vscode-mode"
            )

    return issues


def _providers_yaml_path(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "config" / "runtime" / "providers.yaml"


def _save_provider_config(path: Path, payload: dict[str, Any]) -> None:
    save_yaml_file(path, payload, sort_keys=False, atomic=True)


def is_provider_enabled(project_root: Path, provider_id: str) -> bool:
    """Single source of truth for provider enablement: implementation feature state.

    `providers.yaml` holds only rich runtime config; whether a provider is enabled
    lives in `features.yaml` under the provider's implementation state.
    """
    return get_implementation_state(project_root, _COMPONENT_ID, provider_id).enabled


# Back-compat-free alias kept for call sites that read enablement during resolution.
def resolve_provider_enabled(project_root: Path, provider_id: str) -> bool:
    return is_provider_enabled(project_root, provider_id)


def apply_feature_enabled_state(
    project_root: Path,
    provider_id: str,
    provider_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Return provider_cfg with a derived `enabled` injected from feature state.

    `enabled` is never persisted to providers.yaml; it is computed for in-memory
    consumers (status, health) from the implementation feature state.
    """
    return {**provider_cfg, "enabled": is_provider_enabled(project_root, provider_id)}


def patch_provider_config(
    project_root: Path,
    provider_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Atomically update one provider's rich config block and return the saved payload.

    Creates the providers.yaml and the provider entry if they don't exist. `enabled`
    is not a providers.yaml concern — use `set_provider_enabled` (feature state).
    """
    patch = {key: value for key, value in patch.items() if key != "enabled"}
    path = _providers_yaml_path(project_root)
    if path.exists():
        payload = load_yaml_file(path)
    else:
        payload = {"contract-version": "v1"}
    providers = payload.setdefault("providers", {})
    if provider_id not in providers:
        providers[provider_id] = {}
    providers[provider_id].update(patch)
    _save_provider_config(path, payload)
    return payload


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
    if fn(project_root, _COMPONENT_ID, provider_id).get("ok"):
        return
    state = get_implementation_state(project_root, _COMPONENT_ID, provider_id)
    set_implementation_state(
        project_root,
        _COMPONENT_ID,
        provider_id,
        ImplementationState(enabled=enabled, options=state.options),
    )


def load_provider_config_lenient(project_root: Path) -> dict[str, Any]:
    """Read provider config without schema validation.

    For callers that only need provider presence/enablement (resolution, reconcile
    fallback) and must tolerate partial blocks that strict validation would reject.
    """
    path = _providers_yaml_path(project_root)
    if not path.exists():
        return {"contract-version": "v1", "providers": {}}
    try:
        payload = load_yaml_file(path)
    except Exception:  # noqa: BLE001
        return {"contract-version": "v1", "providers": {}}
    if not isinstance(payload, dict):
        return {"contract-version": "v1", "providers": {}}
    return payload


def load_provider_config(project_root: Path) -> dict[str, Any]:
    path = project_root / ".audiagentic" / "config" / "runtime" / "providers.yaml"
    if not path.exists():
        return {"contract-version": "v1", "providers": {}}
    try:
        payload = load_yaml_file(path)
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="IO-PCFG-001",
            kind="providers",
            message="failed to read provider config",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    issues = validate_provider_config(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-PCFG-001",
            kind="providers",
            message="provider config failed validation",
            details={"issues": issues, "path": str(path)},
        )
    providers = payload.get("providers", {})
    if isinstance(providers, dict):
        payload = dict(payload)
        payload["providers"] = {
            provider_id: apply_feature_enabled_state(project_root, provider_id, provider_cfg)
            if isinstance(provider_cfg, dict)
            else provider_cfg
            for provider_id, provider_cfg in providers.items()
        }
    return payload
