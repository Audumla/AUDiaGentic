"""Machine-global prompt profiles for agent execution."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import global_agents_config_path
from audiagentic.components.agents.configuration.repository import AgentsConfigRepository
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _profiles() -> dict[str, dict[str, Any]]:
    path = global_agents_config_path()
    try:
        snapshot = AgentsConfigRepository(config_path=path, required=True).read(path.parent)
    except Exception as exc:  # noqa: BLE001 - convert config boundary failures
        raise AudiaGenticError(
            code="CFG-APT-002", kind="agents",
            message="global agent prompt profiles are unavailable",
            details={"config-path": str(path)},
        ) from exc
    return {str(item["profile_id"]): dict(item) for item in snapshot.document.prompt_profiles}


def template_name_for_profile(profile_id: str, *, has_body: bool) -> str:
    if not has_body:
        raise AudiaGenticError(
            code="VAL-APT-001", kind="agents",
            message="agent execution requires a non-empty prompt body",
            details={"profile-id": profile_id},
        )
    profile = _profiles().get(profile_id)
    if profile is None:
        raise AudiaGenticError(
            code="CFG-APT-001", kind="agents",
            message="unknown prompt profile",
            details={"profile-id": profile_id, "known": sorted(_profiles())},
        )
    key = "template_with_body"
    value = profile.get(key, profile.get(key.replace("_", "-")))
    if not isinstance(value, str) or not value.strip():
        raise AudiaGenticError(
            code="CFG-APT-003", kind="agents",
            message="prompt profile template path is invalid",
            details={"profile-id": profile_id, "field": key},
        )
    return value


def _template_path(template_name: str) -> Path:
    root = global_agents_config_path().parent.resolve()
    path = (root / template_name).resolve()
    if path != root and root not in path.parents:
        raise AudiaGenticError(
            code="SEC-APT-001", kind="agents",
            message="prompt template path escapes global agent configuration",
            details={"template": template_name},
        )
    return path


def load_profile_template(profile_id: str, *, has_body: bool) -> tuple[str, str, str]:
    """Return (template text, logical name, sha256 digest)."""
    name = template_name_for_profile(profile_id, has_body=has_body)
    path = _template_path(name)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AudiaGenticError(
            code="IO-APT-001", kind="agents",
            message="packaged prompt profile template is missing",
            details={"profile-id": profile_id, "template-name": name},
        ) from exc
    # Source files carry a readability newline; compatibility templates are
    # defined without that terminal byte, matching the legacy builder.
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    digest = hashlib.sha256(raw).hexdigest()
    try:
        return raw.decode("utf-8"), name, digest
    except UnicodeDecodeError as exc:
        raise AudiaGenticError(
            code="CON-APT-002", kind="agents",
            message="configured prompt profile template is not UTF-8",
            details={"template-name": name},
        ) from exc


def verify_template_digest(template_name: str, expected_digest: str) -> str:
    path = _template_path(template_name)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AudiaGenticError(
            code="IO-APT-001", kind="agents",
            message="packaged prompt profile template is missing",
            details={"template-name": template_name},
        ) from exc
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_digest:
        raise AudiaGenticError(
            code="CON-APT-001", kind="agents",
            message="packaged prompt profile template digest changed",
            details={"template-name": template_name, "expected": expected_digest, "actual": actual},
        )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AudiaGenticError(
            code="CON-APT-002", kind="agents",
            message="configured prompt profile template is not UTF-8",
            details={"template-name": template_name},
        ) from exc


def known_profile_ids() -> tuple[str, ...]:
    return tuple(sorted(_profiles()))
