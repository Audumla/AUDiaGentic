"""AS92 transport/schema parity tests for the public status snapshot."""

from __future__ import annotations

from audiagentic.components.agents.status.session_lifecycle_projection import (
    SessionLifecycleDecision,
)
from audiagentic.components.agents.status.status_projection import (
    snapshot_for_request,
    snapshot_to_mapping,
)
from audiagentic.foundation.contracts.schema_registry import read_schema, validate_with_schema
from audiagentic.foundation.transports.agent_status import (
    AgentLifecycle,
    AgentOutcome,
    AgentStatusScope,
    AgentWaitReason,
    StatusEvidenceConfidence,
)


def _enum_values(enum_type: type) -> set[str]:
    return {member.value for member in enum_type}


def test_transport_enum_vocabularies_match_schema() -> None:
    schema = read_schema("agent-status-snapshot")
    properties = schema["properties"]

    assert set(properties["scope"]["enum"]) == _enum_values(AgentStatusScope)
    assert set(properties["lifecycle"]["enum"]) == _enum_values(AgentLifecycle)
    assert set(properties["outcome"]["enum"]) == _enum_values(AgentOutcome) | {None}
    assert set(properties["wait-reason"]["enum"]) == _enum_values(AgentWaitReason) | {None}
    assert set(properties["decisions"]["properties"]["evidence-confidence"]["enum"]) == _enum_values(StatusEvidenceConfidence)


def test_non_null_decisions_mapping_validates_nested_schema() -> None:
    decision = SessionLifecycleDecision(
        coarse_state="active",
        accepts_new_turn=True,
        session_reusable=True,
        turn_terminal=False,
        dependent_work_releasable=False,
        evidence_state="accepted",
        reason="active work",
    )
    snapshot = snapshot_for_request(
        {
            "request-id": "req-schema",
            "session-id": "ses-schema",
            "state": "running",
            "updated-at": "2026-08-23T00:00:00+00:00",
        },
        decision=decision,
    )
    payload = snapshot_to_mapping(snapshot)

    assert payload["decisions"] is not None
    assert validate_with_schema("agent-status-snapshot", payload) == []

    payload["decisions"]["provider-native"] = True
    assert validate_with_schema("agent-status-snapshot", payload)
