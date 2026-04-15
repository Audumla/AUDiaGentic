"""Provider status inspection helpers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.foundation.config.provider_catalog import (
    catalog_is_stale,
    read_model_catalog,
    runtime_catalog_path,
)
from audiagentic.foundation.config.provider_config import load_provider_config
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.interoperability.providers.health import health_check
from audiagentic.interoperability.providers.models import resolve_model_selection

CLI_PROBES: dict[str, list[str]] = {
    "codex": ["codex", "--version"],
    "claude": ["claude", "--version"],
    "gemini": ["gemini", "--version"],
    "qwen": ["qwen", "--version"],
    "copilot": ["gh", "copilot", "--help"],
    "continue": ["continue", "--version"],
    "cline": ["cline", "--version"],
    "opencode": ["opencode", "--version"],
}


def _probe_cli(command: list[str]) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if executable is None:
        return {
            "available": False,
            "command": command,
            "executable": None,
            "returncode": None,
            "stdout": "",
            "stderr": "command not found",
        }
    try:
        command_line = subprocess.list2cmdline(command)
        completed = subprocess.run(
            command_line,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "command": command,
            "executable": executable,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "available": completed.returncode == 0,
        "command": command,
        "executable": executable,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _provider_entry(
    *,
    provider_id: str,
    provider_cfg: dict[str, Any],
    project_root: Path,
    now_fn=None,
) -> dict[str, Any]:
    health = health_check(
        provider_id, {"provider-id": provider_id}, provider_cfg, now_fn=now_fn
    )
    entry: dict[str, Any] = {
        "provider-id": provider_id,
        "enabled": provider_cfg.get("enabled", False),
        "install-mode": provider_cfg.get("install-mode"),
        "access-mode": provider_cfg.get("access-mode"),
        "configured": health.get("configured", False),
        "status": health.get("status"),
        "error": health.get("error"),
        "checked-at": health.get("checked-at"),
        "default-model": provider_cfg.get("default-model"),
        "model-aliases": provider_cfg.get("model-aliases", {}),
    }

    prompt_surface = provider_cfg.get("prompt-surface")
    if isinstance(prompt_surface, dict):
        entry["prompt-surface"] = {
            "enabled": prompt_surface.get("enabled", False),
            "tag-syntax": prompt_surface.get("tag-syntax"),
            "first-line-policy": prompt_surface.get("first-line-policy"),
            "cli-mode": prompt_surface.get("cli-mode"),
            "vscode-mode": prompt_surface.get("vscode-mode"),
            "settings-profile": prompt_surface.get("settings-profile"),
            "supported-modes": [
                mode
                for mode in (
                    prompt_surface.get("cli-mode"),
                    prompt_surface.get("vscode-mode"),
                )
                if mode and mode != "unsupported"
            ],
        }

    catalog_path = runtime_catalog_path(project_root, provider_id)
    entry["catalog-path"] = str(catalog_path)
    entry["catalog-present"] = catalog_path.exists()
    entry["catalog-stale"] = None
    entry["catalog-model-count"] = None
    entry["catalog-source"] = None

    if provider_cfg.get("access-mode") == "cli":
        probe = CLI_PROBES.get(provider_id, [provider_id, "--version"])
        entry["cli-check"] = _probe_cli(probe)
    else:
        entry["cli-check"] = None

    if entry["catalog-present"]:
        try:
            catalog = read_model_catalog(project_root, provider_id)
        except AudiaGenticError as exc:
            entry["catalog-error"] = {
                "code": exc.code,
                "kind": exc.kind,
                "message": exc.message,
                "details": dict(exc.details or {}),
            }
        else:
            entry["catalog-source"] = catalog.get("source")
            entry["catalog-model-count"] = len(catalog.get("models", []))
            refresh = provider_cfg.get("catalog-refresh", {})
            max_age = refresh.get("max-age-hours")
            if isinstance(max_age, int) and max_age > 0:
                entry["catalog-stale"] = catalog_is_stale(
                    catalog, max_age_hours=max_age, now_fn=now_fn
                )
            try:
                resolved = resolve_model_selection(
                    provider_id=provider_id,
                    provider_config=provider_cfg,
                    job_request={},
                    catalog=catalog,
                    now_fn=now_fn,
                )
            except AudiaGenticError as exc:
                entry["model-selection-error"] = {
                    "code": exc.code,
                    "kind": exc.kind,
                    "message": exc.message,
                    "details": dict(exc.details or {}),
                }
            else:
                entry["resolved-model"] = resolved.get("model-id")
                entry["resolved-from"] = resolved.get("resolved-from")
                if "catalog-warning" in resolved:
                    entry["catalog-warning"] = resolved["catalog-warning"]

    if provider_cfg.get("access-mode") == "cli" and entry.get("cli-check", {}).get(
        "available"
    ):
        entry["status"] = "healthy" if entry["configured"] else "unhealthy"
        if (
            entry.get("catalog-present")
            and entry.get("catalog-error") is None
            and entry.get("model-selection-error") is None
        ):
            entry["status"] = "healthy"
    return entry


def build_provider_status(
    project_root: Path, provider_id: str | None = None, *, now_fn=None
) -> dict[str, Any]:
    provider_config = load_provider_config(project_root)
    providers = provider_config.get("providers", {})
    if provider_id is not None:
        if provider_id not in providers:
            raise AudiaGenticError(
                code="PRV-VALIDATION-010",
                kind="validation",
                message="unknown provider-id in provider config",
                details={"provider-id": provider_id},
            )
        provider_ids = [provider_id]
    else:
        provider_ids = sorted(providers)
    return {
        "contract-version": "v1",
        "ok": True,
        "project-root": str(project_root),
        "providers": [
            _provider_entry(
                provider_id=item,
                provider_cfg=providers[item],
                project_root=project_root,
                now_fn=now_fn,
            )
            for item in provider_ids
        ],
    }
