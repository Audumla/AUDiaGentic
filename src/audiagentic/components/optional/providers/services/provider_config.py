"""Provider config loading and validation helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import read_schema


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def validate_provider_config(payload: dict[str, Any]) -> list[str]:
    schema = read_schema("provider-config")
    validator = Draft202012Validator(schema)
    issues = sorted(error.message for error in validator.iter_errors(payload))
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
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.dump(payload, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def patch_provider_config(
    project_root: Path,
    provider_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Atomically update one provider's config block and return the full saved payload.

    Creates the providers.yaml and the provider entry if they don't exist.
    Merges patch shallowly into the existing provider block.
    """
    path = _providers_yaml_path(project_root)
    if path.exists():
        payload = _load_yaml(path)
    else:
        payload = {}
    providers = payload.setdefault("providers", {})
    if provider_id not in providers:
        providers[provider_id] = {}
    providers[provider_id].update(patch)
    _save_provider_config(path, payload)
    return payload


def set_provider_enabled(project_root: Path, provider_id: str, *, enabled: bool) -> dict[str, Any]:
    return patch_provider_config(project_root, provider_id, {"enabled": enabled})


def load_provider_config(project_root: Path) -> dict[str, Any]:
    path = project_root / ".audiagentic" / "config" / "runtime" / "providers.yaml"
    try:
        payload = _load_yaml(path)
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="PRV-IO-002",
            kind="io",
            message="failed to read provider config",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    issues = validate_provider_config(payload)
    if issues:
        raise AudiaGenticError(
            code="PRV-VALIDATION-009",
            kind="validation",
            message="provider config failed validation",
            details={"issues": issues, "path": str(path)},
        )
    return payload
