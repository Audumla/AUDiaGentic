from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml

from audiagentic.components.agents.agents_paths import (
    agent_context_path,
    agent_work_inputs_path,
    global_agents_config_path,
)
from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.components.agents.configuration.repository import AgentsConfigRepository
from audiagentic.components.agents.context.service import close_context, open_context
from audiagentic.components.agents.models.prompt_definition import PromptDefinition, PromptTextPart
from audiagentic.components.agents.work.contracts import AgentWorkWaitReason
from audiagentic.components.agents.work.delegation import delegate_child_work
from audiagentic.components.agents.work.event_adapter import dispatch_trigger_event
from audiagentic.components.agents.work.event_failures import (
    read_event_failures,
    record_event_failure,
)
from audiagentic.components.agents.work.event_ingress import WorkEventIngress
from audiagentic.components.agents.work.ingress import deterministic_work_id, submit_event_work
from audiagentic.components.agents.work.inputs import new_work_input
from audiagentic.components.agents.work.interactions import (
    resume_after_interaction,
    wait_for_interaction,
)
from audiagentic.components.agents.work.reconcile import reconcile_linked_execution, reconcile_work
from audiagentic.components.agents.work.reviews import review_work_id, submit_review_work
from audiagentic.components.agents.work.service import (
    cancel_work,
    get_work,
    link_work_execution,
    read_work_output,
    submit_child_work,
    submit_work,
)
from audiagentic.components.agents.work.triggers import event_pattern_matches, trigger_matches
from audiagentic.components.agents.work.work_api import (
    add_message,
    answer,
    cancel,
    get_status,
    list_status,
    overview,
    submit_packet,
    submit_review,
)


def _seed(root: Path) -> None:
    document = AgentsConfigDocument(
        "v2", (PromptDefinition("p", "", (PromptTextPart("x"),)),),
        ({"role_id": "r", "instructions": "x", "required_capabilities": []},),
        ({"profile_id": "p", "provider_id": "local-openai", "instances": ["plain"]},),
        ({"agent_id": "a", "name": "A", "prompt_id": "p", "role_ids": ["r"], "execution_profile_id": "p"},),
    )
    repository = AgentsConfigRepository(global_agents_config_path())
    repository.replace(root, document, expected_digest=repository.read(root).digest)


def test_context_and_work_transitions_use_foundation_workflow_authority() -> None:
    from audiagentic.components.agents.context import store as context_store
    from audiagentic.components.agents.work import store as work_store

    for module in (context_store, work_store):
        source = inspect.getsource(module)
        assert "load_workflow" in source
        assert "transition_allowed" in source
        assert "_TRANSITIONS" not in source


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


def test_work_links_gateway_execution_without_copying_output(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    work = submit_work(tmp_path, context.context_id, new_work_input("m1", "hello"))
    linked = link_work_execution(tmp_path, work.work_id, "req_1", expected_revision=work.revision)
    assert linked.active_execution_id == "req_1"
    assert "output" not in linked.to_mapping()


def test_gateway_work_admission_replay_uses_one_deterministic_request(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    from audiagentic.components.agents.gateway.application import InProcessGatewayApplication

    app = InProcessGatewayApplication()
    admissions: list[str] = []

    def admit(_root, **kwargs):
        key = kwargs["metadata"]["idempotency_key"]
        admissions.append(key)
        return {"request-id": "req_once", "state": "queued"}

    app.submit_execution_request = admit  # type: ignore[method-assign]
    original_link = __import__(
        "audiagentic.components.agents.work.service", fromlist=["link_work_execution"]
    ).link_work_execution
    failed_once = True

    def crash_before_link(*args, **kwargs):
        nonlocal failed_once
        if failed_once:
            failed_once = False
            raise RuntimeError("simulated crash after gateway admission")
        return original_link(*args, **kwargs)

    monkeypatch.setattr(
        "audiagentic.components.agents.work.service.link_work_execution",
        crash_before_link,
    )
    message = {"message_id": "m-crash", "text": "hello", "inputs": {}, "created_at": "test"}
    with pytest.raises(RuntimeError, match="simulated crash"):
        app.submit_agent_work(tmp_path, context.context_id, message)
    replayed = app.submit_agent_work(tmp_path, context.context_id, message)
    assert replayed["active_execution_id"] == "req_once"
    assert admissions == ["agent-work:" + replayed["work_id"] + ":message:m-crash"] * 2


def test_gateway_application_cancellation_controls_linked_execution_first(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    work = submit_work(tmp_path, context.context_id, new_work_input("m1", "hello"))
    link_work_execution(tmp_path, work.work_id, "req_1", expected_revision=work.revision)

    from audiagentic.components.agents.gateway.application import InProcessGatewayApplication

    app = InProcessGatewayApplication()
    calls: list[str] = []
    app.cancel_execution_request = lambda _root, request_id: calls.append(request_id) or {"state": "cancelled"}  # type: ignore[method-assign]
    result = app.cancel_agent_work(tmp_path, work.work_id)
    assert calls == ["req_1"]
    assert result["state"] == "cancelled"


def test_work_waits_on_foundation_interaction_and_resumes_once_answered(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    work = submit_work(tmp_path, context.context_id, new_work_input("m1", "hello"))
    waiting = wait_for_interaction(
        tmp_path,
        work.work_id,
        kind="approval",
        title="Approve work",
        reason=AgentWorkWaitReason.APPROVAL,
        choices=("yes", "no"),
    )
    assert waiting.state.value == "waiting"
    assert resume_after_interaction(tmp_path, work.work_id) is None

    from audiagentic.foundation.interaction.api import respond

    respond(waiting.current_interaction_id, "yes", project_root=tmp_path)
    resumed = resume_after_interaction(tmp_path, work.work_id)
    assert resumed is not None
    assert resumed.state.value == "active"
    assert resumed.current_interaction_id is None


def test_child_review_work_uses_parent_link_and_same_context(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    parent = submit_work(tmp_path, context.context_id, new_work_input("m1", "review this"))
    child = submit_child_work(tmp_path, parent.work_id, new_work_input("review-1", "review it"))
    assert child.context_id == parent.context_id
    assert child.parent_work_id == parent.work_id


def test_delegation_surface_creates_child_work_only(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    parent = submit_work(tmp_path, context.context_id, new_work_input("m1", "delegate"))
    child = delegate_child_work(tmp_path, parent.work_id, message_id="child-1", text="review")
    assert child.parent_work_id == parent.work_id
    assert child.active_execution_id is None


def test_canonical_trigger_evaluation_has_match_filter_and_reject_paths() -> None:
    assert event_pattern_matches("planning.item.*", "planning.item.created")
    assert not event_pattern_matches("planning.item.*", "planning.item.created.extra")
    assert event_pattern_matches("planning.**", "planning.item.created.extra")
    trigger = {
        "enabled": True,
        "event-pattern": "planning.item.*",
        "filter": {"payload.priority": ["P1", "P2"]},
    }
    assert trigger_matches(trigger, event_type="planning.item.created", payload={"priority": "P1"})
    assert not trigger_matches(trigger, event_type="planning.item.updated", payload={"priority": "P3"})
    assert not trigger_matches({**trigger, "enabled": False}, event_type="planning.item.created", payload={"priority": "P1"})


def test_review_work_is_deterministic_child_and_replay_safe(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    parent = submit_work(tmp_path, context.context_id, new_work_input("m1", "review"))
    first = submit_review_work(tmp_path, parent.work_id, review_key="r1", prompt="Check this")
    replay = submit_review_work(tmp_path, parent.work_id, review_key="r1", prompt="Check this")
    assert first.work_id == review_work_id(parent.work_id, "r1")
    assert replay == first
    assert first.parent_work_id == parent.work_id


def test_event_adapter_is_ingress_only_and_creates_one_work_on_match(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    trigger = {
        "trigger-id": "review-trigger",
        "enabled": True,
        "event-pattern": "planning.item.*",
        "filter": {"payload.priority": "P1"},
    }
    assert dispatch_trigger_event(
        tmp_path,
        trigger=trigger,
        event_type="planning.item.created",
        payload={"priority": "P2"},
        metadata={"event-id": "evt-no"},
        context_id=context.context_id,
        prompt="ignored",
    ) is None
    first = dispatch_trigger_event(
        tmp_path,
        trigger=trigger,
        event_type="planning.item.created",
        payload={"priority": "P1"},
        metadata={"event-id": "evt-1"},
        context_id=context.context_id,
        prompt="review item",
    )
    replay = dispatch_trigger_event(
        tmp_path,
        trigger=trigger,
        event_type="planning.item.created",
        payload={"priority": "P1"},
        metadata={"event-id": "evt-1"},
        context_id=context.context_id,
        prompt="review item",
    )
    assert first is not None
    assert replay == first
    assert len(get_work(tmp_path, first.work_id).to_mapping()) == 10


def test_linked_execution_reconciliation_reads_gateway_state_only(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    work = submit_work(tmp_path, context.context_id, new_work_input("m1", "hello"))
    linked = link_work_execution(tmp_path, work.work_id, "req-1", expected_revision=work.revision)

    class FakeClient:
        def get_execution_request(self, _root, request_id):
            assert request_id == "req-1"
            return {"request-id": request_id, "state": "completed", "output": "not copied"}

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.client.get_gateway_client",
        lambda _root: FakeClient(),
    )
    result = reconcile_linked_execution(tmp_path, linked)
    assert result.state.value == "completed"
    assert "output" not in result.to_mapping()


def test_parent_cancellation_propagates_to_child_work_and_gateway_requests(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    parent = submit_work(tmp_path, context.context_id, new_work_input("m1", "parent"))
    child = submit_child_work(tmp_path, parent.work_id, new_work_input("m2", "child"))
    parent_linked = link_work_execution(tmp_path, parent.work_id, "req_parent", expected_revision=parent.revision)
    link_work_execution(tmp_path, child.work_id, "req_child", expected_revision=child.revision)

    from audiagentic.components.agents.gateway.application import InProcessGatewayApplication

    app = InProcessGatewayApplication()
    requests: list[str] = []
    app.cancel_execution_request = lambda _root, request_id: requests.append(request_id) or {"state": "cancelled"}  # type: ignore[method-assign]
    result = app.cancel_agent_work(tmp_path, parent.work_id)
    assert result["state"] == "cancelled"
    assert requests == [parent_linked.active_execution_id, "req_child"]
    assert get_work(tmp_path, child.work_id).state.value == "cancelled"


def test_event_ingress_reuses_one_work_identity_on_replay(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    first = submit_event_work(
        tmp_path,
        context_id=context.context_id,
        source="event-bus",
        delivery_id="delivery-1",
        text="event payload",
    )
    replay = submit_event_work(
        tmp_path,
        context_id=context.context_id,
        source="event-bus",
        delivery_id="delivery-1",
        text="event payload",
    )
    assert first.work_id == deterministic_work_id(source="event-bus", delivery_id="delivery-1")
    assert replay.work_id == first.work_id
    lines = agent_work_inputs_path(tmp_path, first.work_id).read_text().splitlines()
    assert len(lines) == 1

    with pytest.raises(ValueError, match="payload conflict"):
        submit_event_work(
            tmp_path,
            context_id=context.context_id,
            source="event-bus",
            delivery_id="delivery-1",
            text="different payload",
        )


def test_event_ingress_submits_matching_event_to_canonical_work(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    ingress = WorkEventIngress(
        tmp_path,
        context_id=context.context_id,
        triggers=[{"trigger-id": "trigger-a", "event-pattern": "orders.*"}],
    )

    first = ingress.submit(
        {"trigger-id": "trigger-a", "event-pattern": "orders.*"},
        "orders.created",
        {"order-id": "o-1"},
        {"event-id": "delivery-1"},
    )
    replay = ingress.submit(
        {"trigger-id": "trigger-a", "event-pattern": "orders.*"},
        "orders.created",
        {"order-id": "o-1"},
        {"event-id": "delivery-1"},
    )

    assert first is not None
    assert replay is not None
    assert replay.work_id == first.work_id
    assert ingress.submit(
        {"trigger-id": "trigger-a", "event-pattern": "payments.*"},
        "orders.created",
        {},
        {"event-id": "delivery-2"},
    ) is None


def test_event_ingress_subscription_lifecycle_is_idempotent(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    ingress = WorkEventIngress(
        tmp_path,
        context_id=context.context_id,
        triggers=[{"trigger-id": "trigger-a", "event-pattern": "orders.*"}],
    )
    ingress.start()
    ingress.start()
    ingress.stop()
    ingress.stop()


def test_event_ingress_can_load_triggers_from_canonical_agents_config(tmp_path: Path) -> None:
    _seed(tmp_path)
    path = global_agents_config_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["triggers"] = {
        "orders-created": {
            "event-pattern": "orders.created",
            "enabled": True,
        }
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    context = open_context(tmp_path, "a")
    ingress = WorkEventIngress.from_project_config(tmp_path, context_id=context.context_id)
    result = ingress.submit(
        {"trigger-id": "orders-created", "event-pattern": "orders.created", "enabled": True},
        "orders.created",
        {"order-id": "o-2"},
        {"event-id": "delivery-2"},
    )
    assert result is not None


def test_public_review_api_is_deterministic_child_work(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    parent = submit_work(tmp_path, context.context_id, new_work_input("m-review", "review"))
    first = submit_review(tmp_path, parent.work_id, review_key="review-1", prompt="check it")
    replay = submit_review(tmp_path, parent.work_id, review_key="review-1", prompt="check it")
    assert first["work_id"] == replay["work_id"]
    assert replay["parent_work_id"] == parent.work_id


def test_public_work_control_api_projects_status_message_and_cancel(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    parent = submit_work(tmp_path, context.context_id, new_work_input("control", "control"))
    assert get_status(tmp_path, parent.work_id)["work_id"] == parent.work_id
    assert any(item["work_id"] == parent.work_id for item in list_status(tmp_path))
    add_message(tmp_path, parent.work_id, message_id="answer-1", text="continue")
    result = cancel(tmp_path, parent.work_id)
    assert result["state"] == "cancelled"


def test_canonical_event_failure_record_is_redacted_and_operational(tmp_path: Path) -> None:
    record_event_failure(
        tmp_path,
        trigger_id="trigger-a",
        event_type="orders.created",
        correlation_id="corr-1",
        error_code="VAL-1",
    )
    records = read_event_failures(tmp_path)
    assert records[0]["trigger_id"] == "trigger-a"
    assert "payload" not in records[0]
    assert "prompt" not in records[0]


def test_public_work_overview_is_read_only_and_redacted(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    submit_work(tmp_path, context.context_id, new_work_input("overview", "hello"))
    summary = overview(tmp_path)
    assert summary["work-count"] == 1
    assert "prompt" not in summary
    assert "output" not in summary


def test_public_work_answer_resumes_foundation_interaction(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    work = submit_work(tmp_path, context.context_id, new_work_input("answer", "question"))
    waiting = wait_for_interaction(
        tmp_path,
        work.work_id,
        kind="approval",
        title="Approve Work",
        reason=AgentWorkWaitReason.APPROVAL,
    )
    resumed = answer(tmp_path, waiting.work_id, choice="approve")
    assert resumed["state"] == "active"


def test_packet_submission_is_deterministic_work_without_job_state(tmp_path: Path) -> None:
    _seed(tmp_path)
    context = open_context(tmp_path, "a")
    first = submit_packet(
        tmp_path,
        context_id=context.context_id,
        packet_id="packet-1",
        text="Implement packet one",
    )
    replay = submit_packet(
        tmp_path,
        context_id=context.context_id,
        packet_id="packet-1",
        text="Implement packet one",
    )
    assert first["work_id"] == replay["work_id"]
    assert not (tmp_path / ".audiagentic" / "runtime" / "jobs").exists()
