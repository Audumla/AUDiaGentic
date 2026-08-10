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


def _policy_yaml_path(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "config" / "provider-policy.yaml"


def _provider_settings_path(project_root: Path, provider_id: str) -> Path:
    """Return the project-owned settings file for one provider."""
    return project_root / ".audiagentic" / "config" / "providers" / f"{provider_id}.yaml"


def load_provider_settings(project_root: Path, provider_id: str) -> dict[str, Any]:
    """Load one provider's project-owned settings file."""
    path = _provider_settings_path(project_root, provider_id)
    if not path.exists():
        return {}
    payload = load_yaml_file(path)
    if not isinstance(payload, dict):  # defensive; load_yaml_file already enforces this
        raise AudiaGenticError(
            code="VAL-PCFG-003",
            kind="providers",
            message="provider settings must be a YAML mapping",
            details={"provider-id": provider_id, "path": str(path)},
        )
    return payload


def _merge_provider_files(project_root: Path, providers: dict[str, Any]) -> dict[str, Any]:
    """Merge one complete provider file over any legacy registry entry."""
    directory = project_root / ".audiagentic" / "config" / "providers"
    if not directory.is_dir():
        return providers
    merged = dict(providers)
    for path in sorted(directory.glob("*.yaml")):
        provider_id = path.stem
        file_cfg = load_yaml_file(path)
        base_cfg = merged.get(provider_id, {})
        if not isinstance(base_cfg, dict):
            base_cfg = {}
        merged[provider_id] = {**base_cfg, **file_cfg}
    return merged


def _save_provider_config(path: Path, payload: dict[str, Any]) -> None:
    save_yaml_file(path, payload, sort_keys=False, atomic=True)


def is_provider_enabled(project_root: Path, provider_id: str) -> bool:
    """Single source of truth for provider enablement: implementation feature state.

    Provider settings files hold launch config; whether a provider is enabled
    lives in `features.yaml` under the provider's implementation state.
    """
    return get_implementation_state(project_root, _COMPONENT_ID, provider_id).enabled


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


def patch_provider_config(
    project_root: Path,
    provider_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Atomically update one provider's complete project-owned config file."""
    patch = {key: value for key, value in patch.items() if key != "enabled"}
    path = _provider_settings_path(project_root, provider_id)
    if path.exists():
        payload = load_yaml_file(path)
    else:
        payload = {}
    payload.update(patch)
    _save_provider_config(path, payload)
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
    if fn(project_root, _COMPONENT_ID, provider_id).get("ok"):
        return
    state = get_implementation_state(project_root, _COMPONENT_ID, provider_id)
    set_implementation_state(
        project_root,
        _COMPONENT_ID,
        provider_id,
        ImplementationState(enabled=enabled, options=state.options),
    )


_VALID_RECONCILIATION_MODES = ("auto", "allowlist", "prompt")
_DEFAULT_RECONCILIATION_POLICY: dict[str, Any] = {"mode": "auto"}


def get_reconciliation_policy(project_root: Path) -> dict[str, Any]:
    """Return this project's provider reconciliation policy.

    Defaults to ``{"mode": "auto"}`` (today's behavior: enable whatever CLI
    is detected) when never explicitly configured. Use
    `is_reconciliation_policy_configured` to distinguish "never set" from
    "explicitly set to auto".
    """
    payload = load_provider_config_lenient(project_root)
    policy = payload.get("reconciliation-policy")
    if isinstance(policy, dict) and policy.get("mode") in _VALID_RECONCILIATION_MODES:
        return policy
    return dict(_DEFAULT_RECONCILIATION_POLICY)


def is_reconciliation_policy_configured(project_root: Path) -> bool:
    """Return whether a reconciliation-policy has ever been explicitly written.

    Distinct from `get_reconciliation_policy`, which always returns a usable
    policy (defaulting to auto) even when this is False.
    """
    payload = load_provider_config_lenient(project_root)
    return isinstance(payload.get("reconciliation-policy"), dict)


def set_reconciliation_policy(
    project_root: Path,
    *,
    mode: str,
    allowed_providers: list[str] | None = None,
    decided_providers: list[str] | None = None,
) -> dict[str, Any]:
    """Persist this project's provider reconciliation policy.

    `allowed_providers`/`decided_providers` are only written when explicitly
    passed, so switching back to `mode="auto"` round-trips as ``{"mode":
    "auto"}`` with no stale lists left over from a prior allowlist/prompt mode.
    """
    if mode not in _VALID_RECONCILIATION_MODES:
        raise AudiaGenticError(
            code="VAL-PCFG-002",
            kind="providers",
            message="invalid reconciliation-policy mode",
            details={"mode": mode, "allowed": list(_VALID_RECONCILIATION_MODES)},
        )
    path = _policy_yaml_path(project_root)
    policy: dict[str, Any] = {"mode": mode}
    if allowed_providers is not None:
        policy["allowed-providers"] = sorted(set(allowed_providers))
    if decided_providers is not None:
        policy["decided-providers"] = sorted(set(decided_providers))
    payload = {"contract-version": "v1", "reconciliation-policy": policy}
    validation_payload = load_provider_config_lenient(project_root)
    validation_payload["reconciliation-policy"] = policy
    issues = validate_provider_config(validation_payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-PCFG-001",
            kind="providers",
            message="provider config failed validation",
            details={"issues": issues, "path": str(path)},
        )
    _save_provider_config(path, payload)
    return policy


def load_provider_config_lenient(project_root: Path) -> dict[str, Any]:
    """Read provider config without schema validation.

    For callers that only need provider presence/enablement (resolution, reconcile
    fallback) and must tolerate partial blocks that strict validation would reject.
    """
    path = _providers_yaml_path(project_root)
    try:
        payload = load_yaml_file(path) if path.exists() else {"contract-version": "v1"}
        policy_path = _policy_yaml_path(project_root)
        if policy_path.exists():
            policy_payload = load_yaml_file(policy_path)
            if isinstance(policy_payload.get("reconciliation-policy"), dict):
                payload["reconciliation-policy"] = policy_payload["reconciliation-policy"]
    except Exception:  # noqa: BLE001
        return {"contract-version": "v1", "providers": {}}
    if not isinstance(payload, dict) or not payload:
        payload = {"contract-version": "v1"}
    providers = payload.get("providers", {})
    if not isinstance(providers, dict):
        providers = {}
    payload = dict(payload)
    payload["providers"] = _merge_provider_files(project_root, providers)
    return payload


def load_provider_config(project_root: Path) -> dict[str, Any]:
    path = _providers_yaml_path(project_root)
    try:
        payload = load_yaml_file(path) if path.exists() else {"contract-version": "v1"}
        policy_path = _policy_yaml_path(project_root)
        if policy_path.exists():
            policy_payload = load_yaml_file(policy_path)
            if isinstance(policy_payload.get("reconciliation-policy"), dict):
                payload["reconciliation-policy"] = policy_payload["reconciliation-policy"]
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="IO-PCFG-001",
            kind="providers",
            message="failed to read provider config",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if not isinstance(payload, dict) or not payload:
        payload = {"contract-version": "v1"}
    providers = payload.get("providers", {})
    if isinstance(providers, dict):
        payload = dict(payload)
        providers = _merge_provider_files(project_root, providers)
        payload["providers"] = {
            provider_id: apply_feature_enabled_state(project_root, provider_id, provider_cfg)
            if isinstance(provider_cfg, dict)
            else provider_cfg
            for provider_id, provider_cfg in providers.items()
        }
    issues = validate_provider_config(payload)
    if issues:
        raise AudiaGenticError(
            code="VAL-PCFG-001",
            kind="providers",
            message="provider config failed validation",
            details={"issues": issues, "path": str(path)},
        )
    return payload
