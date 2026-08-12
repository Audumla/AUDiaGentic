from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.workflow.transitions import load_workflow, transition_allowed


def test_agents_reuse_foundation_workflow_authority() -> None:
    root = Path(__file__).parents[3] / "src" / "audiagentic" / "components" / "agents"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    assert "class WorkflowDefinition" not in source
    assert "class StateMachine" not in source
    assert "class TransitionEngine" not in source


def test_context_and_work_workflows_use_foundation_transitions() -> None:
    path = Path(__file__).parents[3] / "src" / "audiagentic" / "components" / "agents" / "workflows.yaml"
    context = load_workflow(path, "agent-context")
    work = load_workflow(path, "agent-work")
    assert transition_allowed(context, "open", "closed")
    assert transition_allowed(work, "submitted", "active")
    assert not transition_allowed(work, "completed", "active")
