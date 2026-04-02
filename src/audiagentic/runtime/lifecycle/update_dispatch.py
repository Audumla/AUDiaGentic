"""Update dispatch selection."""
from __future__ import annotations

from dataclasses import dataclass

from audiagentic.contracts.errors import AudiaGenticError


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int


def parse_version(value: str) -> Version:
    parts = value.split(".")
    if len(parts) != 3:
        raise AudiaGenticError(
            code="LFC-VALIDATION-010",
            kind="validation",
            message="version must be in MAJOR.MINOR.PATCH format",
            details={"value": value},
        )
    try:
        major, minor, patch = (int(part) for part in parts)
    except ValueError as exc:
        raise AudiaGenticError(
            code="LFC-VALIDATION-011",
            kind="validation",
            message="version components must be integers",
            details={"value": value},
        ) from exc
    return Version(major=major, minor=minor, patch=patch)


def select_update_module(installed_version: str, target_version: str) -> str:
    installed = parse_version(installed_version)
    target = parse_version(target_version)
    if installed.major != target.major:
        raise AudiaGenticError(
            code="LFC-BUSINESS-002",
            kind="business-rule",
            message="unsupported upgrade path across major versions",
            details={"installed": installed_version, "target": target_version},
        )
    return f"update_v{installed.major}"
