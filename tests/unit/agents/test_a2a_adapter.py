"""SH61a: the A2A semantic adapter over the gateway Work ports (identity, continuation, wait, mapping)."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.protocols.a2a import A2aServerAdapter
from audiagentic.components.agents.protocols.a2a.mapping import output_text, work_status
from audiagentic.foundation.contracts.errors import AudiaGenticError


class FakePorts:
    """In-memory stand-in with the owner's observable rules (key replay/conflict, terminal refusal)."""

    def __init__(self, *, context_state: str = "open", final_state: str = "completed") -> None:
        self.context_state = context_state
        self.final_state = final_state
        self.accepted: dict[str, dict] = {}
        self.works: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.output = {"text": "done"}

    def list_agent_definitions(self, root):
        return [{"agent_id": "agent-a", "name": "A", "publication": {"a2a": True}, "advertised_skills": ["review"]}]

    def get_agent_context(self, root, context_id):
        return {"context_id": context_id, "state": self.context_state}

    def open_agent_context(self, root, agent_id, title=None):
        self.calls.append(("open", agent_id))
        return {"context_id": "ctx-new", "state": "open"}

    def accept_agent_work_message(self, root, context_id, message, *, protocol, work_id=None):
        self.calls.append(("accept", context_id, message, protocol, work_id))
        key = (context_id, message["message_id"])
        stored = self.accepted.get(str(key))
        if stored and stored["text"] != message["text"]:
            raise AudiaGenticError("CON-AGW-161", "conflict", "different payload")
        # The real owner derives a stable Work id from the delivery key, so a replay finds the same Work.
        wid = work_id or (stored or {}).get("_work") or f"work-{len(self.works) + 1}"
        if wid in self.works and self.works[wid]["state"] in {"completed", "failed", "cancelled", "rejected"} and not stored:
            raise AudiaGenticError("CON-AGW-162", "conflict", "terminal")
        self.accepted[str(key)] = {**message, "_work": wid}
        self.works.setdefault(wid, {"work_id": wid, "context_id": context_id, "state": "active"})
        return dict(self.works[wid])

    def wait_agent_work(self, root, work_id, timeout_seconds=None):
        self.calls.append(("wait", work_id, timeout_seconds))
        self.works[work_id]["state"] = self.final_state
        return {"work": dict(self.works[work_id]), "wait-outcome": "terminal"}

    def get_agent_work(self, root, work_id):
        if work_id not in self.works:
            raise AudiaGenticError("RES-AGW-153", "agent-work", "No Work with this id exists in the project")
        return dict(self.works[work_id])

    def cancel_agent_work(self, root, work_id):
        self.works[work_id]["state"] = "cancelled"
        return dict(self.works[work_id])

    def read_agent_work_output(self, root, work_id):
        return self.output


def _msg(message_id="m1", text="hello", **extra):
    return {"message": {"messageId": message_id, "role": "user", "parts": [{"kind": "text", "text": text}], **extra}}


def test_a_message_without_a_message_id_is_rejected_and_never_hashed(tmp_path: Path) -> None:
    ports = FakePorts()
    with pytest.raises(ValueError, match="messageId"):
        A2aServerAdapter(tmp_path, "agent-a", ports).send_message({"message": {"parts": [{"text": "x"}]}})
    assert ports.calls == []


def test_identity_is_the_message_id_so_identical_text_is_two_tasks(tmp_path: Path) -> None:
    adapter = A2aServerAdapter(tmp_path, "agent-a", FakePorts())
    one = adapter.send_message(_msg("m1", "same"))
    two = adapter.send_message(_msg("m2", "same"))
    assert one["id"] != two["id"]


def test_replay_returns_the_same_task_and_a_changed_payload_conflicts(tmp_path: Path) -> None:
    ports = FakePorts()
    adapter = A2aServerAdapter(tmp_path, "agent-a", ports)
    first = adapter.send_message(_msg("m1", "retry me", contextId="ctx-a"))
    again = adapter.send_message(_msg("m1", "retry me", contextId="ctx-a"))
    assert (first["id"], first["contextId"]) == (again["id"], again["contextId"])
    with pytest.raises(AudiaGenticError) as raised:
        adapter.send_message(_msg("m1", "something else", contextId="ctx-a"))
    assert raised.value.code == "CON-AGW-161"
    assert all(call[3] == "a2a" for call in ports.calls if call[0] == "accept")


def test_task_id_continues_the_same_work_and_a_foreign_context_delivers_nothing(tmp_path: Path) -> None:
    ports = FakePorts(final_state="active")
    adapter = A2aServerAdapter(tmp_path, "agent-a", ports)
    first = adapter.send_message(_msg("m1", "start", contextId="ctx-a"))
    follow = adapter.send_message(_msg("m2", "more", taskId=first["id"], contextId="ctx-a"))
    assert follow["id"] == first["id"]
    assert ports.calls[-2][4] == first["id"]  # accepted with work_id=taskId
    before = len(ports.accepted)
    with pytest.raises(ValueError, match="different objects"):
        adapter.send_message(_msg("m3", "x", taskId=first["id"], contextId="ctx-other"))
    assert len(ports.accepted) == before


def test_no_context_opens_one_and_a_closed_context_is_refused(tmp_path: Path) -> None:
    ports = FakePorts()
    assert A2aServerAdapter(tmp_path, "agent-a", ports).send_message(_msg())["contextId"] == "ctx-new"
    assert ("open", "agent-a") in ports.calls
    closed = FakePorts(context_state="closed")
    with pytest.raises(ValueError, match="OPEN Agent Context"):
        A2aServerAdapter(tmp_path, "agent-a", closed).send_message(_msg(contextId="ctx-a"))
    assert closed.calls == []


def test_terminal_work_refuses_a_new_message(tmp_path: Path) -> None:
    ports = FakePorts()
    adapter = A2aServerAdapter(tmp_path, "agent-a", ports)
    task = adapter.send_message(_msg("m1", "go", contextId="ctx-a"))
    assert task["status"]["state"] == "completed"
    with pytest.raises(AudiaGenticError) as raised:
        adapter.send_message(_msg("m2", "late", taskId=task["id"], contextId="ctx-a"))
    assert raised.value.code == "CON-AGW-162"


def test_the_default_waits_and_return_immediately_does_not(tmp_path: Path) -> None:
    ports = FakePorts()
    adapter = A2aServerAdapter(tmp_path, "agent-a", ports)
    adapter.send_message(_msg("m1", contextId="ctx-a"))
    assert any(call[0] == "wait" and call[2] == 120.0 for call in ports.calls)
    quick = FakePorts()
    task = A2aServerAdapter(tmp_path, "agent-a", quick).send_message(
        {**_msg("m1", contextId="ctx-a"), "configuration": {"returnImmediately": True}})
    assert not any(call[0] == "wait" for call in quick.calls) and task["status"]["state"] == "working"


def test_a_wait_that_times_out_reports_the_real_non_terminal_task(tmp_path: Path) -> None:
    ports = FakePorts()
    ports.wait_agent_work = lambda root, wid, t=None: {"work": dict(ports.works[wid]), "wait-outcome": "timeout"}  # type: ignore[method-assign]
    task = A2aServerAdapter(tmp_path, "agent-a", ports).send_message(_msg(contextId="ctx-a"))
    assert task["status"]["state"] == "working" and "artifacts" not in task


@pytest.mark.parametrize("work, expected", [
    ({"state": "submitted"}, "submitted"), ({"state": "active"}, "working"),
    ({"state": "waiting", "wait_reason": "user-input"}, "input-required"),
    ({"state": "waiting", "wait_reason": "approval"}, "input-required"),
    ({"state": "waiting", "wait_reason": "authentication"}, "auth-required"),
    ({"state": "waiting", "wait_reason": "child-work"}, "working"),
    ({"state": "completed"}, "completed"), ({"state": "failed"}, "failed"),
    ({"state": "cancelled"}, "canceled"), ({"state": "rejected"}, "rejected"),
])
def test_every_work_state_has_an_explicit_mapping(work, expected) -> None:
    assert work_status(work) == expected


def test_an_unrecognized_work_state_is_an_error_not_a_guess() -> None:
    with pytest.raises(ValueError, match="unrecognized"):
        work_status({"state": "mystery"})


def test_cancel_reports_the_real_outcome_and_refuses_finished_tasks(tmp_path: Path) -> None:
    ports = FakePorts(final_state="active")
    adapter = A2aServerAdapter(tmp_path, "agent-a", ports)
    task = adapter.send_message(_msg("m1", contextId="ctx-a"))
    assert adapter.cancel(task["id"])["status"]["state"] == "canceled"
    assert adapter.cancel(task["id"])["status"]["state"] == "canceled"  # already canceled: idempotent
    done = FakePorts()
    finished = A2aServerAdapter(tmp_path, "agent-a", done)
    finished_task = finished.send_message(_msg("m1", contextId="ctx-a"))
    with pytest.raises(ValueError, match="already completed"):
        finished.cancel(finished_task["id"])


def test_output_is_projected_as_a_bounded_text_artifact_only_when_completed(tmp_path: Path) -> None:
    ports = FakePorts()
    task = A2aServerAdapter(tmp_path, "agent-a", ports).send_message(_msg(contextId="ctx-a"))
    assert task["artifacts"][0]["parts"] == [{"kind": "text", "text": "done"}]
    assert output_text({"events": [{"text": "a"}, {"other": 1}, {"text": "b"}]}) == "ab"
    assert len(output_text({"text": "x" * 200_000})) == 64_000 and output_text(None) == ""


def test_rich_parts_are_refused_while_bare_text_parts_are_accepted(tmp_path: Path) -> None:
    adapter = A2aServerAdapter(tmp_path, "agent-a", FakePorts())
    for part in ({"kind": "file", "uri": "x"}, {"text": "x", "data": {}}, {"kind": "text"}):
        with pytest.raises(ValueError):
            adapter.send_message({"message": {"messageId": "m", "parts": [part]}})
    assert adapter.send_message({"message": {"messageId": "m", "parts": [{"text": "bare"}]}})["id"]


def test_the_card_declares_only_what_the_adapter_implements(tmp_path: Path) -> None:
    card = A2aServerAdapter(tmp_path, "agent-a", FakePorts()).agent_card()
    assert card["skills"][0]["id"] == "review"
    assert card["capabilities"] == {"streaming": False, "pushNotifications": False, "extendedAgentCard": False}
    assert set(card) == {"name", "description", "skills", "defaultInputModes", "defaultOutputModes", "capabilities"}


# --- against the real Work owner (admission stubbed) ----------------------------------------------------

from .test_context_work import _seed  # noqa: E402


@pytest.mark.usefixtures("in_process_gateway")
def test_the_adapter_runs_against_the_real_work_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from audiagentic.components.agents.context.service import open_context
    from audiagentic.components.agents.gateway.client import get_gateway_client

    _seed(tmp_path)
    context = open_context(tmp_path, "a", "t")
    client = get_gateway_client(tmp_path)
    admitted: list[str] = []

    def admit(_root, **kwargs):
        key = kwargs["metadata"]["idempotency_key"]
        if key not in admitted:
            admitted.append(key)
        return {"request-id": f"req_{admitted.index(key) + 1}", "state": "queued"}

    # The gateway application is a process-wide singleton: patch it with monkeypatch so it is restored.
    monkeypatch.setattr(client._application, "submit_execution_request", admit)
    monkeypatch.setattr(client._application, "wait_execution_request", lambda root, rid, t=None: {"wait-outcome": "timeout", "status": {"state": "running"}})

    class Ports:
        def __getattr__(self, name):
            return getattr(client, name)

        def list_agent_definitions(self, root):
            return [{"agent_id": "a", "publication": {"a2a": True}}]

    adapter = A2aServerAdapter(tmp_path, "a", Ports())
    request = _msg("m1", "hello", contextId=context.context_id)
    first = adapter.send_message(request)
    assert first["status"]["state"] == "working"
    again = adapter.send_message(request)
    assert again["id"] == first["id"] and len(admitted) == 1  # replay: no second admission
    follow = adapter.send_message(_msg("m2", "more", taskId=first["id"], contextId=context.context_id))
    assert follow["id"] == first["id"] and len(admitted) == 2  # continuation: same Work, new request
