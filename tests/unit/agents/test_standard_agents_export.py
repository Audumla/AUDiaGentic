from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.export.standard_agents import (
    NonPortableProjectionError,
    project_agent,
    render_typescript,
)


def _composition(instances=None):
    return {
        "agent": {"agent_id": "agent-a", "name": "Agent A"},
        "roles": [{"role_id": "role-a", "instructions": "Be precise."}, {"role_id": "role-b", "instructions": "Be kind."}],
        "prompt": {"content": "Answer clearly."},
        "execution_profile": {"instances": instances or [{"provider_id": "openai", "model_id": "gpt-5"}]},
    }


def test_standard_export_is_deterministic_and_multi_role_is_not_dual_ai():
    projected = project_agent(_composition())
    assert projected["kind"] == "ai_human"
    assert len(projected["instructions"].splitlines()) == 5
    assert render_typescript(projected) == render_typescript(project_agent(_composition()))


def test_dynamic_profile_is_not_lied_about_as_a_standard_model():
    with pytest.raises(NonPortableProjectionError, match="multi-instance"):
        project_agent(_composition([{"provider_id": "a", "model_id": "m"}, {"provider_id": "b", "model_id": "m"}]))


def test_protocol_and_export_surfaces_do_not_own_legacy_jobs() -> None:
    package_root = Path(__file__).parents[3] / "src" / "audiagentic" / "components" / "agents"
    roots = (package_root / "protocols", package_root / "export")
    offenders = [
        str(path)
        for root in roots
        for path in root.rglob("*.py")
        if "components.agent_jobs" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
