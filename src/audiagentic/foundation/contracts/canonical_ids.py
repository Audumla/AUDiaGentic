"""Canonical id registry for AUDiaGentic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CANONICAL_PROVIDER_IDS = (
    "local-openai",
    "claude",
    "codex",
    "gemini",
    "qwen",
    "copilot",
    "continue",
    "cline",
    "opencode",
)

CANONICAL_COMPONENT_IDS = (
    "core-lifecycle",
    "release-audit-ledger",
    "agent-jobs",
    "provider-layer",
    "discord-overlay",
    "optional-server",
)

CANONICAL_SCHEMA_IDS = (
    "approval-request",
    "change-event",
    "component-config",
    "error-envelope",
    "event-envelope",
    "installed-state",
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
    "review-bundle",
    "review-report",
    "stage-result",
    "validation-report",
)


@dataclass(frozen=True)
class CanonicalIds:
    providers: tuple[str, ...]
    components: tuple[str, ...]
    schemas: tuple[str, ...]


def get_canonical_ids() -> CanonicalIds:
    return CanonicalIds(
        providers=CANONICAL_PROVIDER_IDS,
        components=CANONICAL_COMPONENT_IDS,
        schemas=CANONICAL_SCHEMA_IDS,
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
