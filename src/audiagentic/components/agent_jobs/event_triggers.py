"""Event-trigger loader and validator for agent jobs.

Reads ``.audiagentic/config/agent-jobs/event-triggers.yaml``, validates each
trigger against the local JSON Schema (EDJ19 — component-only, NOT registered in
foundation schema_registry), and returns a list of :class:`TriggerConfig`
instances.  Disabled triggers are skipped.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.path_safety import ensure_contained

logger = logging.getLogger(__name__)

_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "contracts" / "event-trigger.schema.json"
)
_TRIGGER_CONFIG_PATH = "config/agent-jobs/event-triggers.yaml"


@dataclass(frozen=True)
class TriggerConfig:
    """Deserialized event trigger configuration."""

    contract_version: str
    trigger_id: str
    kind: str
    enabled: bool = True
    event_pattern: str | None = None
    agent_profile_id: str | None = None
    workflow_profile: str | None = None
    target: dict[str, Any] | None = None
    prompt_template: str | None = None
    prompt_template_file: str | None = None
    metadata_propagation: dict[str, Any] | None = None


def _read_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_trigger(trigger: dict[str, Any]) -> list[str]:
    """Validate a single trigger dict against the JSON schema.

    Returns sorted error messages (empty list means valid).
    """
    validator = Draft202012Validator(_read_schema())
    return sorted(err.message for err in validator.iter_errors(trigger))


def _check_template_xor(trigger: dict[str, Any]) -> bool:
    """Return True if exactly one of prompt-template / prompt-template-file is set."""
    has_inline = "prompt-template" in trigger and isinstance(
        trigger["prompt-template"], str
    )
    has_file = "prompt-template-file" in trigger and isinstance(
        trigger["prompt-template-file"], str
    )
    return has_inline ^ has_file


def _load_template_file(
    project_root: Path,
    template_path: str,
    trigger_id: str,
) -> str:
    """Load a prompt template file with path containment check.

    Parameters
    ----------
    project_root:
        Root of the AUDiaGentic project.
    template_path:
        File path from ``prompt-template-file`` config field.
    trigger_id:
        Trigger identifier for error messages.

    Returns
    -------
    str
        The file contents as a string.

    Raises
    ------
    AudiaGenticError
        IO-PTMPL-001 if the file does not exist after containment resolution,
        IO-PTMPL-002 on read errors, IO-PATH-001 if path escapes project root.
    """
    try:
        resolved = ensure_contained(project_root, template_path)
    except AudiaGenticError as exc:
        if exc.code == "IO-PATH-001":
            raise AudiaGenticError(
                code="IO-PATH-001",
                kind="foundation",
                message=(
                    f"Trigger {trigger_id!r}: prompt-template-file {template_path!r} "
                    f"resolves outside the project root."
                ),
                details={
                    "trigger_id": trigger_id,
                    "requested_path": template_path,
                    "project_root": str(project_root),
                },
            ) from exc
        raise

    if not resolved.is_file():
        raise AudiaGenticError(
            code="IO-PTMPL-001",
            kind="agent-jobs",
            message=(
                f"Trigger {trigger_id!r}: prompt template file not found at "
                f"{resolved}"
            ),
            details={
                "trigger_id": trigger_id,
                "template_path": template_path,
                "resolved_path": str(resolved),
            },
        )

    try:
        return resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AudiaGenticError(
            code="IO-PTMPL-002",
            kind="agent-jobs",
            message=(
                f"Trigger {trigger_id!r}: failed to read prompt template file "
                f"{resolved}"
            ),
            details={
                "trigger_id": trigger_id,
                "template_path": template_path,
                "error": str(exc),
            },
        ) from exc


def _coerce(
    trigger: dict[str, Any],
    project_root: Path,
) -> TriggerConfig:
    """Convert a validated trigger dict into a dataclass instance.

    If ``prompt-template-file`` is set, the file content is loaded at
    registration time and stored in ``prompt_template`` for unified
    rendering downstream.
    """
    prompt_template = trigger.get("prompt-template")
    template_file = trigger.get("prompt-template-file")

    if template_file and not prompt_template:
        prompt_template = _load_template_file(
            project_root, template_file, trigger["trigger-id"]
        )

    return TriggerConfig(
        contract_version=trigger["contract-version"],
        trigger_id=trigger["trigger-id"],
        kind=trigger["kind"],
        enabled=trigger.get("enabled", True),
        event_pattern=trigger.get("event-pattern"),
        agent_profile_id=trigger.get("agent-profile-id"),
        workflow_profile=trigger.get("workflow-profile"),
        target=trigger.get("target"),
        prompt_template=prompt_template,
        prompt_template_file=template_file,
        metadata_propagation=trigger.get("metadata-propagation"),
    )


def load_event_triggers(project_root: Path) -> list[TriggerConfig]:
    """Load and validate event triggers from the project config directory.

    Parameters
    ----------
    project_root:
        Root of the AUDiaGentic project (parent of ``.audiagentic/``).

    Returns
    -------
    List of enabled :class:`TriggerConfig` instances.  Disabled triggers are
    silently skipped.

    Raises
    ------
    AudiaGenticError
        VAL-AJT-001 on schema validation failure, VAL-AJT-002 on duplicate
        trigger-id, VAL-AJT-003 on prompt-template XOR violation,
        IO-PTMPL-001 if a template file is missing, IO-PTMPL-002 on read
        errors, IO-PATH-001 if a template path escapes project root.
    """
    config_path = project_root / ".audiagentic" / _TRIGGER_CONFIG_PATH
    if not config_path.exists():
        return []

    raw = load_yaml_file(config_path)
    triggers_list = raw.get("triggers", raw.get("event-triggers"))
    if not isinstance(triggers_list, list):
        raise AudiaGenticError(
            code="VAL-AJT-001",
            kind="agent-jobs",
            message="event-triggers.yaml must contain a 'triggers' key with a list of trigger objects",
        )

    seen_ids: set[str] = set()
    result: list[TriggerConfig] = []

    for idx, trigger in enumerate(triggers_list):
        if not isinstance(trigger, dict):
            raise AudiaGenticError(
                code="VAL-AJT-001",
                kind="agent-jobs",
                message=f"trigger at index {idx} must be an object",
            )

        # -- prompt-template XOR prompt-template-file (check before schema
        # so we surface the specific VAL-AJT-003 code) --
        if not _check_template_xor(trigger):
            raise AudiaGenticError(
                code="VAL-AJT-003",
                kind="agent-jobs",
                message="exactly one of prompt-template or prompt-template-file is required",
                details={
                    "has-prompt-template": "prompt-template" in trigger,
                    "has-prompt-template-file": "prompt-template-file" in trigger,
                },
            )

        # -- schema validation (unknown fields rejected by additionalProperties:false) --
        issues = _validate_trigger(trigger)
        if issues:
            raise AudiaGenticError(
                code="VAL-AJT-001",
                kind="agent-jobs",
                message=f"trigger at index {idx} failed validation: {'; '.join(issues)}",
                details={"issues": issues},
            )

        # -- duplicate trigger-id (schema validation guarantees presence) --
        tid = trigger["trigger-id"]
        if tid in seen_ids:
            raise AudiaGenticError(
                code="VAL-AJT-002",
                kind="agent-jobs",
                message=f"duplicate trigger-id: {tid!r}",
                details={"trigger-id": tid},
            )
        seen_ids.add(tid)

        # -- event-pattern required when kind == "event" --
        if trigger["kind"] == "event" and not trigger.get("event-pattern"):
            raise AudiaGenticError(
                code="VAL-AJT-001",
                kind="agent-jobs",
                message=f"trigger {tid!r} with kind=event requires event-pattern",
                details={"trigger-id": tid},
            )

        # -- skip disabled --
        if not trigger.get("enabled", True):
            continue

        result.append(_coerce(trigger, project_root))

    return result
