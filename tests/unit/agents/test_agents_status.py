"""Unit tests for agent_status — the agents component status-hook (AG13)."""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.configuration.management import (
    agent_status,
    create_execution_profile,
)


def test_agent_status_no_profiles(tmp_path: Path) -> None:
    result = agent_status(tmp_path).to_dict()
    # No default profile means the default gateway path (submit without an
    # explicit execution-profile-id) raises RES-EXP-003 — must not report
    # configured=True (RV37 finding: overstated readiness).
    assert result["configured"] is False
    assert result["active_implementation"] is None
    assert result["details"]["profile_count"] == 0
    assert result["details"]["default_profile_id"] is None
    assert result["details"]["gateway"]["total_requests"] == 0
    assert result["details"]["gateway"]["by_state"] == {}
    assert result["details"]["gateway"]["recent_failures"] == []


def test_agent_status_reports_profile_count_and_default(tmp_path: Path) -> None:
    create_execution_profile(tmp_path, {
        "profile_id": "a", "provider_id": "local-openai", "instances": ["gpt-4o"], "is_default": True,
    })
    create_execution_profile(tmp_path, {
        "profile_id": "b", "provider_id": "codex", "instances": ["gpt-4o"],
    })
    result = agent_status(tmp_path).to_dict()
    assert result["configured"] is True
    assert result["details"]["profile_count"] == 2
    assert result["details"]["default_profile_id"] == "a"
