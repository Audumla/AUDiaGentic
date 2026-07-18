"""Generic agent job prompt context construction.

Trigger-neutral prompt context layer for agent jobs. Any launch path
(event trigger, code/API request, CLI/MCP prompt launch) creates the same
`AgentJobPromptContext` shape before rendering templates.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event.envelope import EventEnvelope
from audiagentic.foundation.logging.redaction import is_bulk_key, is_sensitive_key

logger = logging.getLogger(__name__)
# Sensitive-key matching delegated to foundation/logging/redaction.py.
# _REDACTION_DENYLIST removed — is_sensitive_key() is the single matcher (RV328).

# Maximum bytes per context section before truncation.
_MAX_SECTION_BYTES: int = 4 * 1024  # 4KB


@dataclass(frozen=True)
class AgentJobPromptContext:
    """Stable prompt context for template rendering.

    All fields are dict-based so that dotted-path template rendering via
    :func:`to_template_dict` produces nested access patterns like
    ``{event.payload.id}``.
    """

    job: dict[str, Any]
    project: dict[str, Any]
    launch: dict[str, Any]
    trigger: dict[str, Any]
    event: dict[str, Any]
    metadata: dict[str, Any]
    session: dict[str, Any]
    target: dict[str, Any]
    agent: dict[str, Any]
    correlation_id: str | None = None
    subject: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive keys at every depth using shared is_sensitive_key()."""
    result: dict[str, Any] = {}
    for k, v in data.items():
        if is_sensitive_key(k):
            continue
        if isinstance(v, dict):
            result[k] = _redact_dict(v)
        elif isinstance(v, list):
            result[k] = [_redact_dict(item) if isinstance(item, dict) else item for item in v]
        else:
            result[k] = v
    return result


def _redact_event_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive and bulk keys from event payload at every depth."""
    result: dict[str, Any] = {}
    for k, v in data.items():
        if is_sensitive_key(k) or is_bulk_key(k):
            continue
        if isinstance(v, dict):
            result[k] = _redact_event_dict(v)
        elif isinstance(v, list):
            result[k] = [_redact_event_dict(item) if isinstance(item, dict) else item for item in v]
        else:
            result[k] = v
    return result


def _truncate_section(section: dict[str, Any]) -> dict[str, Any]:
    """Enforce per-section byte budget. Truncate string values if needed."""
    import json
    total = len(json.dumps(section))
    if total <= _MAX_SECTION_BYTES:
        return section
    truncated: dict[str, Any] = {}
    for k, v in section.items():
        value_bytes = len(json.dumps(v)) if v is not None else 0
        remaining = _MAX_SECTION_BYTES - len(json.dumps(truncated))
        if value_bytes > remaining and remaining > 64:
            truncated[k] = str(v)[:remaining - 12] + "...truncated"
        elif value_bytes <= remaining:
            truncated[k] = v
    return truncated


def _safe_section(data: dict[str, Any]) -> dict[str, Any]:
    """Apply redaction then size limit to a context section."""
    if not isinstance(data, dict):
        data = {"raw": data}
    redacted = _redact_dict(data)
    return _truncate_section(redacted)


# ---------------------------------------------------------------------------
# Public constructors
# ---------------------------------------------------------------------------

def build_prompt_context_from_event(
    *,
    envelope: EventEnvelope,
    trigger_config: dict[str, Any] | None = None,
    project_root: str = "",
    project_id: str = "",
    job_id: str = "",
    agent_profile_id: str = "",
    provider_id: str = "",
    model_id: str = "",
    target: dict[str, Any] | None = None,
    session_data: dict[str, Any] | None = None,
    source_surface: str = "event",
) -> AgentJobPromptContext:
    """Build context from an EventEnvelope + trigger config (event-driven launch).

    Args:
        envelope: The canonical event envelope.
        trigger_config: Optional TriggerConfig fields dict.
        project_root: Absolute path to the project root.
        project_id: Project identifier string.
        job_id: Job identifier string.
        agent_profile_id: Resolved agent profile id.
        provider_id: Resolved provider id.
        model_id: Resolved model id.
        target: Optional launch target info dict.
        session_data: Optional pre-loaded session data dict.
        source_surface: Launch surface label (default "event").

    Returns:
        Fully-populated AgentJobPromptContext ready for template rendering.
    """
    now = _now_iso()

    # -- job section --
    job_section: dict[str, Any] = {
        "id": job_id,
        "created_at": now,
    }

    # -- project section --
    project_section: dict[str, Any] = {
        "root": project_root,
        "id": project_id,
    }

    # -- launch section --
    launch_section: dict[str, Any] = {
        "source": source_surface,
        "surface": source_surface,
        "input": {},
    }
    if trigger_config and trigger_config.get("event_pattern"):
        launch_section["input"] = {"trigger_id": trigger_config.get("trigger_id", "")}

    # -- trigger section --
    trigger_section: dict[str, Any] = {}
    if trigger_config:
        trigger_section = {
            "id": trigger_config.get("trigger_id", ""),
            "event_pattern": trigger_config.get("event_pattern", ""),
            "kind": trigger_config.get("kind", ""),
        }

    # -- event section: flatten envelope fields --
    payload = _redact_event_dict(dict(envelope.payload)) if envelope.payload else {}
    event_section: dict[str, Any] = {
        "type": envelope.type,
        "source_component": envelope.source_component,
        "occurred_at": envelope.occurred_at,
        "payload": payload,
    }

    # -- metadata section --
    correlation_id = envelope.correlation_id or ""
    subject_data = dict(envelope.subject) if envelope.subject else {}
    metadata_section: dict[str, Any] = {
        "correlation_id": correlation_id,
        "subject": subject_data,
    }

    # Planning item ID alias: inject plan_item.id from subject when available.
    if envelope.type == "planning.item.created" and subject_data:
        plan_item_id = subject_data.get("id") or payload.get("item_id") or payload.get("id", "")
        event_section["plan_item"] = {"id": plan_item_id}

    # -- session section --
    session_section: dict[str, Any] = dict(session_data) if session_data else {}

    # -- target section --
    target_section: dict[str, Any] = dict(target) if target else {}

    # -- agent section --
    agent_section: dict[str, Any] = {
        "profile_id": agent_profile_id,
        "provider_id": provider_id,
        "model_id": model_id,
    }

    # Apply safety transforms to all sections.
    return AgentJobPromptContext(
        job=_safe_section(job_section),
        project=_safe_section(project_section),
        launch=_safe_section(launch_section),
        trigger=_safe_section(trigger_section),
        event=_safe_section(event_section),
        metadata=_safe_section(metadata_section),
        session=_safe_section(session_section),
        target=_safe_section(target_section),
        agent=_safe_section(agent_section),
        correlation_id=correlation_id,
        subject=subject_data or None,
    )


def build_prompt_context_from_request(
    *,
    request: dict[str, Any],
    project_root: str = "",
    project_id: str = "",
    job_id: str = "",
    agent_profile_id: str = "",
    provider_id: str = "",
    model_id: str = "",
    explicit_context: dict[str, Any] | None = None,
    session_data: dict[str, Any] | None = None,
) -> AgentJobPromptContext:
    """Build context from a direct request dict (code/API/CLI/MCP launch).

    Args:
        request: The raw prompt-launch request dict.
        project_root: Absolute path to the project root.
        project_id: Project identifier string.
        job_id: Job identifier string.
        agent_profile_id: Resolved agent profile id.
        provider_id: Resolved provider id.
        model_id: Resolved model id.
        explicit_context: Optional caller-supplied context data merged into sections.
        session_data: Optional pre-loaded session data dict.

    Returns:
        Fully-populated AgentJobPromptContext ready for template rendering.
    """
    now = _now_iso()
    source = request.get("source", {})
    target_raw = request.get("target", {})
    tag = request.get("tag", "")

    # -- job section --
    job_section: dict[str, Any] = {
        "id": job_id,
        "created_at": now,
    }

    # -- project section --
    project_section: dict[str, Any] = {
        "root": project_root,
        "id": project_id,
    }

    # -- launch section --
    launch_section: dict[str, Any] = {
        "source": source.get("surface", "cli"),
        "surface": source.get("surface", "cli"),
        "input": {
            "prompt_id": request.get("prompt_id", ""),
            "tag": tag,
            "session_id": source.get("session_id", ""),
        },
    }

    # -- trigger section: empty for direct launch --
    trigger_section: dict[str, Any] = {}

    # -- event section: empty for direct launch --
    event_section: dict[str, Any] = {}

    # -- metadata section --
    correlation_id = source.get("correlation_id", "") or ""
    subject_data: dict[str, Any] | None = source.get("subject")
    if not isinstance(subject_data, dict):
        subject_data = None
    metadata_section: dict[str, Any] = {
        "correlation_id": correlation_id,
        "subject": subject_data or {},
    }

    # -- session section --
    session_section: dict[str, Any] = dict(session_data) if session_data else {}

    # -- target section --
    target_section: dict[str, Any] = dict(target_raw) if target_raw else {}

    # -- agent section --
    agent_section: dict[str, Any] = {
        "profile_id": agent_profile_id,
        "provider_id": provider_id,
        "model_id": model_id,
    }

    # Merge caller-supplied explicit context into session or launch.input.
    if explicit_context and isinstance(explicit_context, dict):
        for k, v in explicit_context.items():
            if k not in metadata_section:
                metadata_section[k] = v

    return AgentJobPromptContext(
        job=_safe_section(job_section),
        project=_safe_section(project_section),
        launch=_safe_section(launch_section),
        trigger=_safe_section(trigger_section),
        event=_safe_section(event_section),
        metadata=_safe_section(metadata_section),
        session=_safe_section(session_section),
        target=_safe_section(target_section),
        agent=_safe_section(agent_section),
        correlation_id=correlation_id,
        subject=subject_data,
    )


# ---------------------------------------------------------------------------
# Template rendering export
# ---------------------------------------------------------------------------

def to_template_dict(context: AgentJobPromptContext) -> dict[str, Any]:
    """Flatten context into a single-level dict for dotted-path template rendering.

    Each top-level key (``job``, ``project``, ``launch``, etc.) becomes a nested
    section accessible via paths like ``{job.id}``, ``{event.payload.id}``, etc.
    Top-level aliases ``correlation_id`` and ``subject`` are also included as
    flat keys for simple templates.
    """
    result: dict[str, Any] = {
        "job": context.job,
        "project": context.project,
        "launch": context.launch,
        "trigger": context.trigger,
        "event": context.event,
        "metadata": context.metadata,
        "session": context.session,
        "target": context.target,
        "agent": context.agent,
    }
    if context.correlation_id:
        result["correlation_id"] = context.correlation_id
    if context.subject:
        result["subject"] = context.subject
    return result


# ---------------------------------------------------------------------------
# Session loading helper
# ---------------------------------------------------------------------------

def load_session_data(
    project_root: str | Path,
    session_id: str,
) -> dict[str, Any]:
    """Load session data from the session input store for a given session id.

    Reads the most recent NDJSON input records associated with the session and
    returns them as a consolidated dict.

    Args:
        project_root: Path to the project root directory.
        session_id: Session identifier to load.

    Returns:
        Consolidated session data dict. Empty dict on missing or unreadable store.

    Raises:
        AudiaGenticError: IO-CTX-002 if the session store is structurally corrupt.
    """
    root = Path(project_root) if isinstance(project_root, str) else project_root
    input_path = root / ".audiagentic" / "runtime" / "jobs"
    if not input_path.is_dir():
        return {}

    records: list[dict[str, Any]] = []
    try:
        for ndjson_file in sorted(input_path.glob("**/input.ndjson")):
            try:
                text = ndjson_file.read_text(encoding="utf-8").strip()
                if not text:
                    continue
                for line in text.splitlines():
                    line = line.strip()
                    if line:
                        record = _loads_json(line)
                        if isinstance(record, dict):
                            records.append(record)
            except PermissionError:
                # Permission is an operator-actionable store failure, unlike a
                # malformed individual record. Let the outer contract map it
                # to IO-CTX-002 rather than silently presenting an empty
                # session as valid.
                raise
            except Exception:  # noqa: BLE001
                continue
    except PermissionError as exc:
        raise AudiaGenticError(
            code="IO-CTX-002",
            kind="agent-jobs",
            message=f"failed to read session input store for session {session_id!r}",
            details={"session_id": session_id, "error": str(exc)},
        ) from exc

    if not records:
        return {}

    # Group by job-id; pick the last record per job as the current state.
    by_job: dict[str, dict[str, Any]] = {}
    for rec in records:
        job_id = rec.get("job-id", rec.get("job_id"))
        if job_id:
            by_job[job_id] = rec

    return {
        "session_id": session_id,
        "jobs": by_job,
        "record_count": len(records),
    }


# ---------------------------------------------------------------------------
# Internal time / json helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return now_iso_z()


def _loads_json(text: str) -> Any:
    import json as _json
    return _json.loads(text)
from audiagentic.foundation.time import now_iso_z
