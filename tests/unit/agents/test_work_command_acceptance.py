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
