from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.agents_paths import agent_context_path, agent_work_inputs_path
from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.components.agents.configuration.repository import AgentsConfigRepository
from audiagentic.components.agents.context.service import close_context, open_context
from audiagentic.components.agents.models.prompt_definition import PromptDefinition, PromptTextPart
from audiagentic.components.agents.work.inputs import new_work_input
from audiagentic.components.agents.work.reconcile import reconcile_work
from audiagentic.components.agents.work.service import (
    cancel_work,
    get_work,
    read_work_output,
    submit_work,
)


def _seed(root: Path) -> None:
    document = AgentsConfigDocument(
        "v2", (PromptDefinition("p", "", (PromptTextPart("x"),)),),
        ({"role_id": "r", "instructions": "x", "required_capabilities": []},),
        ({"profile_id": "p", "provider_id": "local-openai", "instances": ["plain"]},),
        ({"agent_id": "a", "name": "A", "prompt_id": "p", "role_ids": ["r"], "execution_profile_id": "p"},),
    )
    AgentsConfigRepository().replace(root, document, expected_digest=None)


def test_context_is_logical_and_work_input_is_idempotent(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a", "test")
    work = submit_work(tmp_path, context.context_id, new_work_input("m1", "hello"))
    assert get_work(tmp_path, work.work_id).state.value == "active"
    assert agent_context_path(tmp_path, context.context_id).exists()
    assert agent_work_inputs_path(tmp_path, work.work_id).read_text().count("m1") == 1
    close_context(tmp_path, context.context_id)
    with pytest.raises(ValueError, match="closed"):
        submit_work(tmp_path, context.context_id, new_work_input("m2", "no"))


def test_work_cancel_is_terminal_and_output_projects_gateway_owner(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    work = submit_work(tmp_path, context.context_id, new_work_input("m1", "hello"))

    cancelled = cancel_work(tmp_path, work.work_id)
    assert cancelled.state.value == "cancelled"
    assert cancel_work(tmp_path, work.work_id).state.value == "cancelled"
    assert read_work_output(tmp_path, work.work_id) == {
        "work_id": work.work_id,
        "execution_id": None,
        "events": [],
    }


def test_work_reconciliation_is_restart_safe_and_terminal_idempotent(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    work = submit_work(tmp_path, context.context_id, new_work_input("m1", "hello"))

    completed = reconcile_work(tmp_path, work, execution_state="completed")
    replayed = reconcile_work(tmp_path, completed, execution_state="completed")

    assert completed.state.value == "completed"
    assert replayed == completed
