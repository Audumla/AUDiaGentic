"""Event-trigger loader and validator for agent jobs.

Reads ``.audiagentic/config/agent-jobs/event-triggers.yaml``, validates each
trigger against the local JSON Schema (EDJ19 — component-only, NOT registered in
foundation schema_registry), and returns a list of :class:`TriggerConfig`
instances.  Disabled triggers are returned too (``enabled=False``); suppression
is the observer's responsibility so it stays auditable (EDJ23).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.components.agent_jobs.prompt_templates import load_prompt_from_file
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.templates import _MISSING, resolve_path

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
    filter: dict[str, Any] | None = None
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
        prompt_template, _ = load_prompt_from_file(
            project_root, template_file, source_label=f"Trigger {trigger['trigger-id']!r}"
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
        filter=trigger.get("filter"),
        metadata_propagation=trigger.get("metadata-propagation"),
    )


def matches_filter(context: dict[str, Any], filter_spec: dict[str, Any] | None) -> bool:
    """Evaluate a trigger's filter conditions against an event context (EDJ15).

    *context* is exactly ``{"payload": payload, "metadata": metadata}``. Each
    filter key is a dotted path resolved via the shared
    :func:`foundation.templates.resolve_path`; scalar expectations match by
    equality, lists by membership; all clauses AND. A missing path, a present
    ``None``, or any mismatch yields ``False`` — never an exception. No
    expression language: equality/membership only.
    """
    if not filter_spec:
        return True
    for path, expected in filter_spec.items():
        value = resolve_path(context, path)
        if value is _MISSING or value is None:
            return False
        if isinstance(expected, list):
            if value not in expected:
                return False
        elif value != expected:
            return False
    return True


def load_event_triggers(project_root: Path) -> list[TriggerConfig]:
    """Load and validate event triggers from the project config directory.

    Parameters
    ----------
    project_root:
        Root of the AUDiaGentic project (parent of ``.audiagentic/``).

    Returns
    -------
    List of every schema-valid :class:`TriggerConfig`, including triggers with
    ``enabled: false`` — callers that must not act on disabled triggers check
    ``TriggerConfig.enabled`` themselves (the observer suppresses them with an
    audit record).

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

        result.append(_coerce(trigger, project_root))

    return result
