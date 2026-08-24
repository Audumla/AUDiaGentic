"""Canonical schema id helpers for AUDiaGentic.

Foundation-pure: provider-id discovery lives outside foundation and is injected
into validators that need it, so this module has no dependency on any component.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

CANONICAL_SCHEMA_IDS = (
    "agent-execution-record",
    "agent-execution-session",
    "agent-output-event",
    "agent-status-snapshot",
    "approval-request",
    "change-event",
    "component-config",
    "error-envelope",
    "event-envelope",
    "event-topics",
    "interaction-request",
    "job-record",
    "lifecycle-plan",
    "lifecycle-result",
    "project-config",
    "prompt-launch-request",
    "prompt-syntax",
    "provider-config",
    "provider-completion",
    "provider-descriptor",
    "provider-model-catalog",
    "provider-health",
    "provider-stream-event",
    "provider-stream-manifest",
    "provider-session-input",
    "provider-session-manifest",
    "resolved-execution-profile",
    "review-bundle",
    "review-report",
    "stage-result",
    "status-evidence",
    "task-status-v4",
    "validation-report",
)


def validate_schema_files(schema_dir: Path) -> list[str]:
    """Ensure schema files align with canonical schema ids."""
    if not schema_dir.exists():
        return []
    expected = set(CANONICAL_SCHEMA_IDS)
    actual = set()
    for path in schema_dir.glob("*.json"):
        stem = path.stem
        if stem.endswith(".schema"):
            stem = stem[: -len(".schema")]
        actual.add(stem)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    findings = []
    if missing:
        findings.append(f"missing schema ids: {', '.join(missing)}")
    if extra:
        findings.append(f"unexpected schema ids: {', '.join(extra)}")
    return findings


def validate_ids(ids: Iterable[str], allowed: Iterable[str]) -> list[str]:
    allowed_set = set(allowed)
    invalid = sorted({value for value in ids if value not in allowed_set})
    if not invalid:
        return []
    return [f"invalid ids: {', '.join(invalid)}"]
