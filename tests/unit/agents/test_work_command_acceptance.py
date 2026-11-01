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
