"""Installed-state manifest handling."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

ALLOWED_INSTALL_KINDS = {"fresh", "cutover", "update"}


@dataclass(frozen=True)
class InstalledStateManifest:
    contract_version: str
    installation_kind: str
    current_version: str
    previous_version: str | None
    components: dict[str, str]
    providers: dict[str, str]
    last_lifecycle_action: str
    updated_at: str


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_manifest(payload: dict[str, Any]) -> list[str]:
    required = {
        "contract-version",
        "installation-kind",
        "current-version",
        "previous-version",
        "components",
        "providers",
        "last-lifecycle-action",
        "updated-at",
    }
    missing = sorted(required - set(payload.keys()))
    issues: list[str] = []
    if missing:
        issues.append(f"missing fields: {', '.join(missing)}")
        return issues
    if payload.get("contract-version") != "v1":
        issues.append("contract-version must be v1")
    if payload.get("installation-kind") not in ALLOWED_INSTALL_KINDS:
        issues.append("installation-kind must be one of fresh, cutover, update")
    if not isinstance(payload.get("components"), dict):
        issues.append("components must be an object")
    if not isinstance(payload.get("providers"), dict):
        issues.append("providers must be an object")
    return issues


def read_manifest(project_root: Path) -> InstalledStateManifest:
    path = project_root / ".audiagentic" / "installed.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AudiaGenticError(
            code="LFC-VALIDATION-001",
            kind="validation",
            message="failed to read installed-state manifest",
            details={"error": str(exc)},
        ) from exc

    issues = validate_manifest(payload)
    if issues:
        raise AudiaGenticError(
            code="LFC-VALIDATION-002",
            kind="validation",
            message="installed-state manifest failed validation",
            details={"issues": issues},
        )

    return InstalledStateManifest(
        contract_version=payload["contract-version"],
        installation_kind=payload["installation-kind"],
        current_version=payload["current-version"],
        previous_version=payload["previous-version"],
        components=payload["components"],
        providers=payload["providers"],
        last_lifecycle_action=payload["last-lifecycle-action"],
        updated_at=payload["updated-at"],
    )


def write_manifest(project_root: Path, payload: dict[str, Any]) -> Path:
    issues = validate_manifest(payload)
    if issues:
        raise AudiaGenticError(
            code="LFC-VALIDATION-003",
            kind="validation",
            message="installed-state manifest failed validation",
            details={"issues": issues},
        )

    target_dir = project_root / ".audiagentic"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "installed.json"

    fd, tmp_path = tempfile.mkstemp(prefix="installed.", suffix=".tmp", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return target_path


def build_manifest(
    installation_kind: str,
    current_version: str,
    previous_version: str | None,
    components: dict[str, str],
    providers: dict[str, str],
    last_lifecycle_action: str,
) -> dict[str, Any]:
    return {
        "contract-version": "v1",
        "installation-kind": installation_kind,
        "current-version": current_version,
        "previous-version": previous_version,
        "components": components,
        "providers": providers,
        "last-lifecycle-action": last_lifecycle_action,
        "updated-at": _now_timestamp(),
    }
