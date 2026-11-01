"""SH60a: one atomic, replay-safe acceptance of a caller command on Work (identity, digest, continuation)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.agents.agents_paths import agent_work_inputs_path, agent_work_path
from audiagentic.components.agents.context.service import close_context, open_context
from audiagentic.components.agents.work.contracts import AgentWorkState
from audiagentic.components.agents.work.inputs import new_work_input
from audiagentic.components.agents.work.service import (
    accept_work_command,
    cancel_work,
    get_work,
    work_command_digest,
    work_delivery_key,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_context_work import _seed

pytestmark = pytest.mark.usefixtures("in_process_gateway")


def _key(context_id: str, message_id: str, *, principal: str = "alice", protocol: str = "a2a") -> str:
    return work_delivery_key(principal=principal, subject=None, protocol=protocol, project_id="proj",
                             context_id=context_id, target_generation=None, message_id=message_id)


@pytest.fixture
def context(tmp_path: Path):
    _seed(tmp_path)
    return open_context(tmp_path, "a", "t")


def test_identical_text_with_distinct_delivery_ids_is_two_commands(tmp_path: Path, context) -> None:
    first = accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m1"),
                                message=new_work_input("m1", "same text"))
    second = accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m2"),
                                 message=new_work_input("m2", "same text"))
    assert first.work.work_id != second.work.work_id and not first.replayed and not second.replayed


def test_same_delivery_replays_the_original_receipt(tmp_path: Path, context) -> None:
    key = _key(context.context_id, "m1")
    first = accept_work_command(tmp_path, context.context_id, delivery_key=key, message=new_work_input("m1", "hi"))
    again = accept_work_command(tmp_path, context.context_id, delivery_key=key, message=new_work_input("m1", "hi"))
    assert again.replayed and again.work.work_id == first.work.work_id
    assert again.command["accepted_at"] == first.command["accepted_at"]
    assert len(get_work(tmp_path, first.work.work_id).commands) == 1
    assert agent_work_inputs_path(tmp_path, first.work.work_id).read_text().count('"m1"') == 1


def test_a_changed_payload_under_the_same_identity_conflicts(tmp_path: Path, context) -> None:
    key = _key(context.context_id, "m1")
    accept_work_command(tmp_path, context.context_id, delivery_key=key, message=new_work_input("m1", "one"))
    with pytest.raises(AudiaGenticError) as raised:
        accept_work_command(tmp_path, context.context_id, delivery_key=key, message=new_work_input("m1", "two"))
    assert raised.value.code == "CON-AGW-161"


def test_the_digest_ignores_created_at_and_covers_inputs_and_intent() -> None:
    assert work_command_digest("t", {"a": 1}) == work_command_digest("t", {"a": 1})
    assert work_command_digest("t", {"a": 1}) != work_command_digest("t", {"a": 2})
    assert work_command_digest("t", {}, {"target": "x"}) != work_command_digest("t", {}, {"target": "y"})


def test_the_key_separates_principal_protocol_and_project(tmp_path: Path, context) -> None:
    base = _key(context.context_id, "m1")
    assert base != _key(context.context_id, "m1", principal="bob")
    assert base != _key(context.context_id, "m1", protocol="acp")
    with pytest.raises(AudiaGenticError) as raised:
        work_delivery_key(principal="", subject=None, protocol="a2a", project_id="p", context_id="c",
                          target_generation=None, message_id="m")
    assert raised.value.code == "CON-AGW-163"


def test_continuation_appends_to_the_existing_non_terminal_work(tmp_path: Path, context) -> None:
    first = accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m1"),
                                message=new_work_input("m1", "start"), work_id="work_x")
    second = accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m2"),
                                 message=new_work_input("m2", "more"), work_id="work_x")
    assert second.work.work_id == first.work.work_id == "work_x" and not second.replayed
    assert [c["message"]["message_id"] for c in get_work(tmp_path, "work_x").commands] == ["m1", "m2"]


def test_terminal_work_refuses_a_new_command_but_replays_a_committed_one(tmp_path: Path, context) -> None:
    key = _key(context.context_id, "m1")
    accept_work_command(tmp_path, context.context_id, delivery_key=key, message=new_work_input("m1", "go"),
                        work_id="work_t")
    cancel_work(tmp_path, "work_t")
    assert get_work(tmp_path, "work_t").state is AgentWorkState.CANCELLED
    replay = accept_work_command(tmp_path, context.context_id, delivery_key=key, message=new_work_input("m1", "go"),
                                 work_id="work_t")
    assert replay.replayed
    with pytest.raises(AudiaGenticError) as raised:
        accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m2"),
                            message=new_work_input("m2", "late"), work_id="work_t")
    assert raised.value.code == "CON-AGW-162"


def test_a_closed_context_accepts_nothing_and_a_foreign_context_is_refused(tmp_path: Path, context) -> None:
    accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m1"),
                        message=new_work_input("m1", "x"), work_id="work_c")
    other = open_context(tmp_path, "a", "other")
    with pytest.raises(AudiaGenticError) as raised:
        accept_work_command(tmp_path, other.context_id, delivery_key=_key(other.context_id, "m9"),
                            message=new_work_input("m9", "x"), work_id="work_c")
    assert raised.value.code == "CON-AGW-160"
    close_context(tmp_path, context.context_id)
    with pytest.raises(AudiaGenticError) as raised:
        accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m2"),
                            message=new_work_input("m2", "x"))
    assert raised.value.code == "CON-AGW-164"


def test_a_lost_input_projection_is_rebuilt_from_the_record(tmp_path: Path, context) -> None:
    key = _key(context.context_id, "m1")
    receipt = accept_work_command(tmp_path, context.context_id, delivery_key=key, message=new_work_input("m1", "hi"))
    inputs = agent_work_inputs_path(tmp_path, receipt.work.work_id)
    inputs.unlink()  # crash after the commit, before/while the projection was written
    again = accept_work_command(tmp_path, context.context_id, delivery_key=key, message=new_work_input("m1", "hi"))
    assert again.replayed and json.loads(inputs.read_text().splitlines()[0])["message_id"] == "m1"


def test_later_transitions_keep_the_accepted_commands_and_historical_records_still_read(tmp_path: Path, context) -> None:
    from audiagentic.components.agents.work.service import submit_work

    receipt = accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m1"),
                                  message=new_work_input("m1", "hi"), work_id="work_k")
    cancel_work(tmp_path, "work_k")
    assert len(get_work(tmp_path, "work_k").commands) == 1
    old = submit_work(tmp_path, context.context_id, new_work_input("legacy", "old path"))
    assert "commands" not in json.loads(agent_work_path(tmp_path, old.work_id).read_text())
    assert get_work(tmp_path, old.work_id).commands == ()
    assert receipt.work.work_id == "work_k"


def test_concurrent_acceptance_of_one_delivery_commits_once(tmp_path: Path, context) -> None:
    from concurrent.futures import ThreadPoolExecutor

    key = _key(context.context_id, "m1")

    def accept(_):
        return accept_work_command(tmp_path, context.context_id, delivery_key=key,
                                   message=new_work_input("m1", "race"))

    with ThreadPoolExecutor(max_workers=6) as pool:
        receipts = list(pool.map(accept, range(6)))
    assert sum(1 for r in receipts if not r.replayed) == 1
    assert len({r.work.work_id for r in receipts}) == 1
    assert len(get_work(tmp_path, receipts[0].work.work_id).commands) == 1


# --- SH60b: dispatch and continuation through the gateway application ---------------------------------


def _app(monkeypatch=None):
    from audiagentic.components.agents.gateway.application import InProcessGatewayApplication

    app = InProcessGatewayApplication()
    admitted: list[dict] = []

    def admit(_root, **kwargs):
        key = kwargs["metadata"]["idempotency_key"]
        existing = next((a for a in admitted if a["key"] == key), None)
        if existing is None:
            existing = {"key": key, "request-id": f"req_{len(admitted) + 1}", "prompt": kwargs["prompt_body"]}
            admitted.append(existing)
        return {"request-id": existing["request-id"], "state": "queued"}

    app.submit_execution_request = admit  # type: ignore[method-assign]
    return app, admitted


_IDENTITY = {"principal": "alice", "subject": None, "protocol": "a2a", "project_id": "proj", "target_generation": None}


def test_accepting_a_message_admits_exactly_one_request_and_replays_it(tmp_path: Path, context) -> None:
    app, admitted = _app()
    message = {"message_id": "m1", "text": "hello", "inputs": {}}
    first = app.accept_agent_work_message(tmp_path, context.context_id, message, delivery_identity=_IDENTITY)
    again = app.accept_agent_work_message(tmp_path, context.context_id, message, delivery_identity=_IDENTITY)
    assert len(admitted) == 1 and first["active_execution_id"] == "req_1" == again["active_execution_id"]
    assert first["state"] == "active" and not first["replayed"] and again["replayed"]


def test_identical_text_with_a_new_message_id_is_a_second_admission(tmp_path: Path, context) -> None:
    app, admitted = _app()
    one = app.accept_agent_work_message(tmp_path, context.context_id, {"message_id": "m1", "text": "same"},
                                        delivery_identity=_IDENTITY)
    two = app.accept_agent_work_message(tmp_path, context.context_id, {"message_id": "m2", "text": "same"},
                                        delivery_identity=_IDENTITY)
    assert len(admitted) == 2 and one["work_id"] != two["work_id"]


def test_continuation_of_existing_work_admits_a_new_request_and_keeps_the_history(tmp_path: Path, context) -> None:
    app, admitted = _app()
    first = app.accept_agent_work_message(tmp_path, context.context_id, {"message_id": "m1", "text": "start"},
                                          delivery_identity=_IDENTITY, work_id="work_c")
    second = app.accept_agent_work_message(tmp_path, context.context_id, {"message_id": "m2", "text": "more"},
                                           delivery_identity=_IDENTITY, work_id="work_c")
    assert (first["work_id"], second["work_id"]) == ("work_c", "work_c")
    assert second["active_execution_id"] == "req_2"
    assert [c["execution_id"] for c in get_work(tmp_path, "work_c").commands] == ["req_1", "req_2"]
    assert [a["prompt"] for a in admitted] == ["start", "more"]


def test_a_crash_between_acceptance_and_admission_is_repaired_without_a_second_request(tmp_path: Path, context) -> None:
    app, admitted = _app()
    real_submit = app.submit_execution_request
    crashed = {"done": False}

    def crash_after_admit(root, **kwargs):
        result = real_submit(root, **kwargs)
        if not crashed["done"]:
            crashed["done"] = True
            raise RuntimeError("crash after admission, before the link")
        return result

    app.submit_execution_request = crash_after_admit  # type: ignore[method-assign]
    message = {"message_id": "m1", "text": "hello"}
    with pytest.raises(RuntimeError, match="crash after admission"):
        app.accept_agent_work_message(tmp_path, context.context_id, message, delivery_identity=_IDENTITY)
    work = next(w for w in __import__("audiagentic.components.agents.work.service", fromlist=["list_work"]).list_work(tmp_path))
    assert work.commands and not work.commands[0].get("execution_id")  # accepted, not yet linked
    repaired = app.dispatch_agent_work_commands(tmp_path, work.work_id)
    assert repaired["active_execution_id"] == "req_1" and len(admitted) == 1


def test_reconcile_admits_commands_that_never_reached_the_gateway(tmp_path: Path, context, monkeypatch) -> None:
    from audiagentic.components.agents.work.reconcile import reconcile_linked_execution

    app, admitted = _app()
    receipt = accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m1"),
                                  message=new_work_input("m1", "lost admission"))

    class _Client:
        def dispatch_agent_work_commands(self, root, work_id):
            return app.dispatch_agent_work_commands(root, work_id)

        def get_execution_request(self, root, request_id):
            return {"state": "running"}

    monkeypatch.setattr("audiagentic.components.agents.gateway.client.get_gateway_client", lambda _root: _Client())
    result = reconcile_linked_execution(tmp_path, receipt.work)
    assert result.active_execution_id == "req_1" and [a["prompt"] for a in admitted] == ["lost admission"]


def test_a_command_keeps_its_first_execution(tmp_path: Path, context) -> None:
    from audiagentic.components.agents.work.store import AgentWorkStore

    receipt = accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m1"),
                                  message=new_work_input("m1", "x"))
    key = receipt.command["delivery_key"]
    store = AgentWorkStore()
    store.link_command_execution(tmp_path, receipt.work.work_id, key, "req_a")
    store.link_command_execution(tmp_path, receipt.work.work_id, key, "req_a")  # idempotent
    with pytest.raises(AudiaGenticError) as raised:
        store.link_command_execution(tmp_path, receipt.work.work_id, key, "req_b")
    assert raised.value.code == "CON-AGW-166"


# --- SH60c: the correlated wait port --------------------------------------------------------------------


def test_wait_without_an_execution_is_not_terminal(tmp_path: Path, context) -> None:
    app, _ = _app()
    receipt = accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m1"),
                                  message=new_work_input("m1", "x"))
    result = app.wait_agent_work(tmp_path, receipt.work.work_id, 1)
    assert result["wait-outcome"] == "no-execution" and result["work"]["state"] == "submitted"


def test_a_wait_timeout_returns_the_non_terminal_state_without_inventing_success(tmp_path: Path, context) -> None:
    app, _ = _app()
    work = app.accept_agent_work_message(tmp_path, context.context_id, {"message_id": "m1", "text": "x"},
                                         delivery_identity=_IDENTITY)
    app.wait_execution_request = lambda root, request_id, timeout: {  # type: ignore[method-assign]
        "wait-outcome": "timeout", "status": {"state": "running"}}
    result = app.wait_agent_work(tmp_path, work["work_id"], 0.01)
    assert result["wait-outcome"] == "timeout" and result["work"]["state"] == "active"


def test_a_terminal_request_is_projected_onto_the_work_and_the_wait_is_bounded(tmp_path: Path, context) -> None:
    app, _ = _app()
    work = app.accept_agent_work_message(tmp_path, context.context_id, {"message_id": "m1", "text": "x"},
                                         delivery_identity=_IDENTITY)
    seen = {}

    def waited(root, request_id, timeout):
        seen["timeout"] = timeout
        return {"state": "completed"}

    app.wait_execution_request = waited  # type: ignore[method-assign]
    result = app.wait_agent_work(tmp_path, work["work_id"], 10_000)
    assert result["wait-outcome"] == "terminal" and result["work"]["state"] == "completed"
    assert seen["timeout"] <= 600.0
    assert get_work(tmp_path, work["work_id"]).state is AgentWorkState.COMPLETED


def test_the_trusted_identity_rejects_unknown_protocols_and_carries_the_declared_project(tmp_path: Path) -> None:
    from audiagentic.components.agents.gateway.application import trusted_delivery_identity

    identity = trusted_delivery_identity(tmp_path, principal="alice", protocol="acp")
    assert identity["principal"] == "alice" and identity["subject"] is None and identity["project_id"]
    with pytest.raises(AudiaGenticError) as raised:
        trusted_delivery_identity(tmp_path, principal="alice", protocol="smtp")
    assert raised.value.code == "CON-AGW-163"


# --- SH60d: exclusive acceptance and Work milestone events ------------------------------------------------


def test_exclusive_acceptance_refuses_a_second_outstanding_work_but_not_concurrent_unflagged_work(tmp_path: Path, context) -> None:
    accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m1"),
                        message=new_work_input("m1", "first"), exclusive=True)
    with pytest.raises(AudiaGenticError) as raised:
        accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m2"),
                            message=new_work_input("m2", "second"), exclusive=True)
    assert raised.value.code == "CON-AGW-167"
    other = accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m3"),
                                message=new_work_input("m3", "a2a-style concurrent"))  # not exclusive: allowed
    assert not other.replayed


def test_exclusive_acceptance_allows_a_new_prompt_once_the_earlier_work_is_terminal_and_replays_its_own(tmp_path: Path, context) -> None:
    key = _key(context.context_id, "m1")
    first = accept_work_command(tmp_path, context.context_id, delivery_key=key,
                                message=new_work_input("m1", "first"), exclusive=True)
    again = accept_work_command(tmp_path, context.context_id, delivery_key=key,
                                message=new_work_input("m1", "first"), exclusive=True)
    assert again.replayed and again.work.work_id == first.work.work_id  # an exact replay is not a second prompt
    cancel_work(tmp_path, first.work.work_id)
    second = accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, "m2"),
                                 message=new_work_input("m2", "next"), exclusive=True)
    assert not second.replayed


def test_simultaneous_exclusive_acceptances_commit_exactly_one(tmp_path: Path, context) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def accept(n):
        try:
            accept_work_command(tmp_path, context.context_id, delivery_key=_key(context.context_id, f"m{n}"),
                                message=new_work_input(f"m{n}", f"prompt {n}"), exclusive=True)
            return "ok"
        except AudiaGenticError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(accept, range(6)))
    assert results.count("ok") == 1 and results.count("CON-AGW-167") == 5


def _capture_events(monkeypatch):
    seen = []
    monkeypatch.setattr("audiagentic.components.agents.work.events.publish_work_event",
                        lambda topic, work, **kw: seen.append((topic, dict(work), kw)))
    return seen


def test_acceptance_replay_and_conflict_publish_distinct_bounded_events(tmp_path: Path, context, monkeypatch) -> None:
    from audiagentic.components.agents.work.events import topics

    seen = _capture_events(monkeypatch)
    key = _key(context.context_id, "m1")
    accept_work_command(tmp_path, context.context_id, delivery_key=key, message=new_work_input("m1", "secret prompt"))
    accept_work_command(tmp_path, context.context_id, delivery_key=key, message=new_work_input("m1", "secret prompt"))
    with pytest.raises(AudiaGenticError):
        accept_work_command(tmp_path, context.context_id, delivery_key=key, message=new_work_input("m1", "changed"))
    assert [topic for topic, _w, _k in seen] == [topics.WORK_MESSAGE_ACCEPTED_TOPIC, topics.WORK_MESSAGE_REPLAYED_TOPIC,
                                                 topics.WORK_MESSAGE_CONFLICT_TOPIC]


def test_the_event_publisher_never_raises_and_carries_no_text_principal_or_inputs(monkeypatch) -> None:
    from audiagentic.components.agents.work import events

    published = []

    class Bus:
        def publish(self, topic, payload):
            published.append((topic, payload))

    monkeypatch.setattr("audiagentic.foundation.event.get_bus", lambda: Bus())
    work = {"work_id": "w", "context_id": "c", "state": "active", "commands": [{"message": {"text": "secret"}}]}
    events.publish_work_event(events.topics.WORK_TERMINAL_TOPIC, work, delivery_key="a" * 64, execution_id="req_1")
    topic, payload = published[0]
    assert payload == {"work-id": "w", "context-id": "c", "state": "active", "delivery-key": "a" * 12, "execution-id": "req_1"}
    assert "secret" not in repr(payload)

    class Broken:
        def publish(self, topic, payload):
            raise RuntimeError("subscriber exploded")

    monkeypatch.setattr("audiagentic.foundation.event.get_bus", lambda: Broken())
    events.publish_work_event(events.topics.WORK_TERMINAL_TOPIC, work)  # must not raise


def test_dispatch_publishes_linked_and_reconcile_publishes_repaired_and_terminal_once(tmp_path: Path, context, monkeypatch) -> None:
    from audiagentic.components.agents.work.events import topics
    from audiagentic.components.agents.work.reconcile import reconcile_work

    seen = _capture_events(monkeypatch)
    app, _ = _app()
    work = app.accept_agent_work_message(tmp_path, context.context_id, {"message_id": "m1", "text": "x"},
                                         delivery_identity=_IDENTITY)
    assert topics.WORK_EXECUTION_LINKED_TOPIC in [topic for topic, _w, _k in seen]
    record = get_work(tmp_path, work["work_id"])
    done = reconcile_work(tmp_path, record, execution_state="completed")
    again = reconcile_work(tmp_path, done, execution_state="completed")
    assert again.state is AgentWorkState.COMPLETED
    assert [topic for topic, _w, _k in seen].count(topics.WORK_TERMINAL_TOPIC) == 1


def test_a_missing_work_is_a_registered_not_found_error_not_a_bare_key_error(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as raised:
        get_work(tmp_path, "work_does_not_exist")
    assert raised.value.code == "RES-AGW-153" and raised.value.details["work_id"] == "work_does_not_exist"
