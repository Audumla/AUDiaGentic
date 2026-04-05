"""Structured provider completion and result normalization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.contracts.schema_registry import read_schema


class ResultSource(str, Enum):
    """Where the final result was obtained."""

    STDOUT_JSON = "stdout-json"
    STDOUT_TEXT = "stdout-text"
    RESULT_FILE = "result-file"
    HOOK_SUMMARY = "hook-summary"
    RESPONSE_BODY = "response-body"
    FALLBACK_SYNTHETIC = "fallback-synthetic"


class NormalizationMethod(str, Enum):
    """How AUDiaGentic derived the canonical shape."""

    PROVIDER_NATIVE_JSON = "provider-native-json"
    STDOUT_JSON_BLOCK = "stdout-json-block"
    STDOUT_TEXT_PARSE = "stdout-text-parse"
    FILE_JSON_PARSE = "file-json-parse"
    FALLBACK_DERIVED = "fallback-derived"


class CompletionStatus(str, Enum):
    """Completion status."""

    OK = "ok"
    ERROR = "error"
    PARTIAL = "partial"
    TIMEOUT = "timeout"


class Decision(str, Enum):
    """Review decision."""

    APPROVED = "approved"
    BLOCKED = "blocked"
    REWORK = "rework"
    PENDING = "pending"


class Recommendation(str, Enum):
    """Review recommendation."""

    PASS = "pass"
    PASS_WITH_NOTES = "pass-with-notes"
    REWORK = "rework"
    BLOCK = "block"


@dataclass
class ProviderCompletion:
    """Canonical provider completion result."""

    contract_version: str = "v1"
    provider_id: str | None = None
    job_id: str | None = None
    prompt_id: str | None = None
    surface: str | None = None
    stage: str | None = None
    subject: dict[str, Any] | None = None
    status: str = CompletionStatus.OK.value
    decision: str | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    recommendation: str = Recommendation.PASS_WITH_NOTES.value
    follow_up_actions: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    result_source: str = ResultSource.FALLBACK_SYNTHETIC.value
    normalization_method: str = NormalizationMethod.FALLBACK_DERIVED.value
    raw_result_path: str | None = None
    created_at: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = _utc_now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "contract-version": self.contract_version,
            "provider-id": self.provider_id,
            "job-id": self.job_id,
            "prompt-id": self.prompt_id,
            "surface": self.surface,
            "stage": self.stage,
            "subject": self.subject,
            "status": self.status,
            "decision": self.decision,
            "findings": self.findings,
            "recommendation": self.recommendation,
            "follow-up-actions": self.follow_up_actions,
            "evidence": self.evidence,
            "notes": self.notes,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "result-source": self.result_source,
            "normalization-method": self.normalization_method,
            "raw-result-path": self.raw_result_path,
            "created-at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderCompletion":
        """Create from dictionary.
        
        Raises AudiaGenticError if the data fails schema validation.
        """
        issues = validate_provider_completion(data)
        if issues:
            raise AudiaGenticError(
                code="COMPLETION-VALIDATION-003",
                kind="validation",
                message="failed to load provider completion due to schema validation errors",
                details={"issues": issues, "provider-id": data.get("provider-id")},
            )
        return cls(
            contract_version=data.get("contract-version", "v1"),
            provider_id=data.get("provider-id"),
            job_id=data.get("job-id"),
            prompt_id=data.get("prompt-id"),
            surface=data.get("surface"),
            stage=data.get("stage"),
            subject=data.get("subject"),
            status=data.get("status", CompletionStatus.OK.value),
            decision=data.get("decision"),
            findings=data.get("findings", []),
            recommendation=data.get(
                "recommendation", Recommendation.PASS_WITH_NOTES.value
            ),
            follow_up_actions=data.get("follow-up-actions", []),
            evidence=data.get("evidence", []),
            notes=data.get("notes", []),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            returncode=data.get("returncode", 0),
            result_source=data.get(
                "result-source", ResultSource.FALLBACK_SYNTHETIC.value
            ),
            normalization_method=data.get(
                "normalization-method", NormalizationMethod.FALLBACK_DERIVED.value
            ),
            raw_result_path=data.get("raw-result-path"),
            created_at=data.get("created-at"),
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def try_extract_json_from_stdout(stdout: str) -> dict[str, Any] | None:
    """Attempt to find and parse a JSON block from provider stdout.
    
    Looks for a block matching ```json ... ``` and parses it.
    Returns None if no block is found or parsing fails.
    """
    import re
    match = re.search(r"```json\s*(.*?)\s*```", stdout, re.DOTALL)
    if match:
        try:
            val = json.loads(match.group(1))
            if isinstance(val, dict):
                return val
        except json.JSONDecodeError:
            pass
    return None


def _validate(payload: dict[str, Any]) -> list[str]:
    """Validate against the completion schema."""
    schema = read_schema("provider-completion")
    validator = Draft202012Validator(schema)
    return sorted(error.message for error in validator.iter_errors(payload))


def validate_provider_completion(payload: dict[str, Any]) -> list[str]:
    """Validate a provider completion payload."""
    return _validate(payload)


def normalize_provider_result(
    *,
    provider_id: str,
    job_id: str | None = None,
    prompt_id: str | None = None,
    surface: str | None = None,
    stage: str | None = None,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    result_source: ResultSource = ResultSource.FALLBACK_SYNTHETIC,
    normalization_method: NormalizationMethod = NormalizationMethod.FALLBACK_DERIVED,
    raw_result_path: Path | None = None,
    subject: dict[str, Any] | None = None,
) -> ProviderCompletion:
    """
    Normalize provider output into a canonical completion result.

    This is the shared normalization harness that all providers use.
    """
    completion = ProviderCompletion(
        provider_id=provider_id,
        job_id=job_id,
        prompt_id=prompt_id,
        surface=surface,
        stage=stage,
        subject=subject,
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        result_source=result_source.value,
        normalization_method=normalization_method.value,
        raw_result_path=str(raw_result_path) if raw_result_path else None,
    )

    if returncode != 0:
        completion.status = CompletionStatus.ERROR.value
        completion.notes.append(f"Provider returned non-zero exit code: {returncode}")

    issues = validate_provider_completion(completion.to_dict())
    if issues:
        raise AudiaGenticError(
            code="COMPLETION-VALIDATION-001",
            kind="validation",
            message="provider completion failed schema validation",
            details={"issues": issues, "provider-id": provider_id},
        )

    return completion


def build_synthetic_fallback(
    *,
    provider_id: str,
    job_id: str | None,
    stdout: str,
    stderr: str,
    returncode: int,
    subject: dict[str, Any] | None = None,
) -> ProviderCompletion:
    """
    Build a synthetic fallback completion when structured parsing fails.

    This explicitly marks the result as fallback-derived.
    """
    return normalize_provider_result(
        provider_id=provider_id,
        job_id=job_id,
        prompt_id=None,
        surface=None,
        stage=None,
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        result_source=ResultSource.FALLBACK_SYNTHETIC,
        normalization_method=NormalizationMethod.FALLBACK_DERIVED,
        subject=subject,
    )


def completion_artifact_dir(project_root: Path, job_id: str) -> Path:
    """Get the artifact directory for completions."""
    return project_root / ".audiagentic" / "runtime" / "jobs" / job_id / "completions"


def completion_path(project_root: Path, job_id: str, provider_id: str) -> Path:
    """Get the path for a provider completion artifact."""
    return (
        completion_artifact_dir(project_root, job_id) / f"completion.{provider_id}.json"
    )


def persist_completion(
    project_root: Path, job_id: str, completion: ProviderCompletion
) -> Path:
    """Persist a completion result to disk."""
    issues = validate_provider_completion(completion.to_dict())
    if issues:
        raise AudiaGenticError(
            code="COMPLETION-VALIDATION-002",
            kind="validation",
            message="provider completion cannot be persisted because validation failed",
            details={"issues": issues, "provider-id": completion.provider_id},
        )
    path = completion_path(project_root, job_id, completion.provider_id or "unknown")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(completion.to_dict(), handle, indent=2, sort_keys=True)
    return path
