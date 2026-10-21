"""A proven no-Send retry retires its exact attempt, never a successor."""
import asyncio
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.session import sessions, sessions_store
from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatMessageRef, ChatSnapshot
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_load_budget_before_prepared_checkpoint_and_aba(tmp_path):
    owner, metadata = setup_attempt(tmp_path)
    record = sessions_store.read_session_record(tmp_path, "ses-unsent")
    record["provider"]["metadata"] = {"project-id": metadata["project-id"]}
    sessions_store.write_session_record(tmp_path, record)
    def budget(**operation):
        return sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner, maximum=2, **operation)
    assert budget() == (0, 0)
    assert budget(action="increment", expected=(0, 0)) == (1, 1)
    assert budget(action="reset", expected=(1, 1)) == (0, 2)
    with pytest.raises(AudiaGenticError):
        budget(action="increment", expected=(0, 0))  # Count matches, revision does not.
    assert budget(action="increment", expected=(0, 2)) == (1, 3)
    assert budget(action="increment", expected=(1, 3)) == (2, 4)
    with pytest.raises(AudiaGenticError):
        budget(action="increment", expected=(2, 4))
    current = sessions_store.session_provider_metadata(sessions_store.read_session_record(tmp_path, "ses-unsent"))
    assert "submission-state" not in current and "unresolved-turn-pending" not in current
    # Generic binding/checkpoint metadata cannot reset or remove budget authority.
    sessions_store.update_provider_metadata(tmp_path, "ses-unsent", {"conversation-load-recovery-attempts": 0}, remove_keys=("conversation-load-recovery-revision",))
    assert budget() == (2, 4)
    sessions_store.record_session_turn(tmp_path, "ses-unsent", "req-unsent",
        provider_metadata={"conversation-load-recovery-attempts": 0, "conversation-load-recovery-revision": 0})
    sessions_store.record_session_turn(tmp_path, "ses-unsent", "req-unsent",
        provider_metadata={"conversation-load-recovery-attempts": 0})
    assert budget() == (2, 4)


@pytest.mark.parametrize("maximum", [True, -1, "2", 1_000_001])
def test_load_budget_rejects_invalid_configuration(tmp_path, maximum):
    owner, _ = setup_attempt(tmp_path)
    with pytest.raises(ValueError):
        sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner, maximum=maximum)


@pytest.mark.parametrize("mutation", [
    {"worker-id": "stale"}, {"dispatch-owner-epoch": "stale"},
    {"attempt-epoch": 2}, {"state": "completed"},
])
def test_load_budget_rejects_stale_owner(tmp_path, mutation):
    owner, _ = setup_attempt(tmp_path)
    request = store.read_record(tmp_path, "req-unsent")
    request.update(mutation)
    store.write_record(tmp_path, request)
    with pytest.raises(AudiaGenticError):
        sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner)


@pytest.mark.parametrize("key,value", [
    ("conversation-load-recovery-attempts", True),
    ("conversation-load-recovery-attempts", -1),
    ("conversation-load-recovery-revision", "1"),
    ("unresolved-turn-id", "successor"),
    ("unresolved-turn-id", None),
    ("project-id", "g-p-other"),
])
def test_load_budget_rejects_corrupt_or_foreign_state(tmp_path, key, value):
    owner, _ = setup_attempt(tmp_path)
    record = sessions_store.read_session_record(tmp_path, "ses-unsent")
    record["provider"]["metadata"][key] = value
    sessions_store.write_session_record(tmp_path, record)
    with pytest.raises(AudiaGenticError):
        sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner)


def budget_chat(tmp_path):
    owner, metadata = setup_attempt(tmp_path)
    config = SimpleNamespace(
        workflow=SimpleNamespace(recovery=SimpleNamespace(
            conversation_load_failure_max_attempts=2,
            conversation_load_failure_recovery_enabled=True, action_pause_seconds=0,
        )), chat=SimpleNamespace(ready_timeout_seconds=0, navigation_timeout_seconds=1),
        turn=SimpleNamespace(poll_interval_seconds=0),
    )
    sink = sessions._make_submission_checkpoint_sink(tmp_path, "ses-unsent", request_id="req-unsent", **owner)
    chat = PersistentChat(ag_session_id="ses-unsent", project_name="project",
        project_url=None, runtime=SimpleNamespace(), config=config,
        binding_sink=lambda _: None, checkpoint_sink=sink,
        provider_session_id="provider-session", chat_url="https://chatgpt.com/g/g-p-audiagentic-exact/c/provider-session")
    chat.page_handle = "retained"
    chat.target_id = "target"
    async def page(_handle):
        return SimpleNamespace(target_id="target", url=chat.chat_url)
    chat._gpt_browser = lambda: SimpleNamespace(page_by_handle=page)
    chat.runtime.release_page = lambda *_args: None
    return chat, owner


def test_provider_budget_commit_survives_request_projection_failure(tmp_path):
    chat, owner = budget_chat(tmp_path)
    async def failed_projection(_metadata):
        raise OSError("projection disk unavailable")
    chat.set_request_metadata_sink(failed_projection)
    assert asyncio.run(chat._persist_load_recovery_budget("increment", expected=(0, 0))) == (1, 1)
    assert sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner) == (1, 1)
    # Canonical session, not the missing request projection, hydrates a restart.
    resumed = sessions_store.session_provider_metadata(sessions_store.read_session_record(tmp_path, "ses-unsent"))
    assert resumed["conversation-load-recovery-attempts"] == 1
    assert resumed["conversation-load-recovery-revision"] == 1


def test_provider_budget_rechecks_owner_after_projection(tmp_path):
    chat, _ = budget_chat(tmp_path)
    async def retire_owner(_metadata):
        record = store.read_record(tmp_path, "req-unsent")
        record["state"] = "interrupted"
        store.write_record(tmp_path, record)
    chat.set_request_metadata_sink(retire_owner)
    with pytest.raises(AudiaGenticError):
        asyncio.run(chat._persist_load_recovery_budget("increment", expected=(0, 0)))


def test_provider_budget_does_not_mutate_memory_after_session_failure(tmp_path, monkeypatch):
    chat, _ = budget_chat(tmp_path)
    def fail(*_args, **_kwargs):
        raise OSError("session commit failed")
    monkeypatch.setattr(sessions_store, "write_session_record", fail)
    with pytest.raises(OSError):
        asyncio.run(chat._persist_load_recovery_budget("increment", expected=(0, 0)))
    assert chat._conversation_load_recovery_attempts == 0
    assert chat._conversation_load_recovery_revision == 0


def test_provider_reset_requires_current_positive_observation(tmp_path):
    chat, owner = budget_chat(tmp_path)
    asyncio.run(chat._persist_load_recovery_budget("increment", expected=(0, 0)))
    healthy = ChatSnapshot.from_bridge({"url": chat.chat_url, "composerPresent": True,
        "composerEditable": True, "userCount": 1, "assistantCount": 1,
        "latestUserId": "user", "latestAssistantId": "answer", "latestAssistantText": "done"})
    chat._load_budget_observation = (healthy, (1, 1), chat._binding_token(healthy))
    # A different snapshot, binding generation or revision is not reset proof.
    from dataclasses import replace
    asyncio.run(chat._reset_load_recovery_budget_after_positive_snapshot(replace(healthy)))
    chat._page_generation += 1
    asyncio.run(chat._reset_load_recovery_budget_after_positive_snapshot(healthy))
    assert chat._conversation_load_recovery_attempts == 1
    chat._page_generation -= 1
    asyncio.run(chat._reset_load_recovery_budget_after_positive_snapshot(healthy))
    assert sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner) == (0, 2)


def test_real_load_replacement_uses_budget_not_submission_writer(tmp_path):
    chat, owner = budget_chat(tmp_path)
    # Reproduce readiness after an unsent attempt was canonically retired.
    record = sessions_store.read_session_record(tmp_path, "ses-unsent")
    record["provider"]["metadata"] = {"project-id": "g-p-audiagentic-exact"}
    sessions_store.write_session_record(tmp_path, record)
    failed = ChatSnapshot.from_bridge({"url": chat.chat_url, "domSignals": {"conversation-load-failed": True}, "errorPresent": True})
    async def create():
        assert sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner) == (1, 1)
        raise RuntimeError("simulated replacement unavailable")
    chat._create_recovery_page = create
    with pytest.raises(RuntimeError, match="simulated replacement unavailable"):
        asyncio.run(chat._replace_load_failed_page(failed))
    # The failure is the provider operation, not CON-AGW-125 stage rejection.
    assert chat._conversation_load_recovery_attempts == 1


def test_load_reset_cannot_clear_later_durable_increment(tmp_path):
    chat, owner = budget_chat(tmp_path)
    asyncio.run(chat._persist_load_recovery_budget("increment", expected=(0, 0)))
    healthy = ChatSnapshot.from_bridge({"url": chat.chat_url, "composerPresent": True})
    chat._load_budget_observation = (healthy, (1, 1), chat._binding_token(healthy))
    sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner,
        action="increment", expected=(1, 1), maximum=2)
    with pytest.raises(AudiaGenticError):
        asyncio.run(chat._reset_load_recovery_budget_after_positive_snapshot(healthy))
    assert sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner) == (2, 2)


@pytest.mark.parametrize("changed", ["target", "conversation", "provider-session"])
def test_load_reset_revalidates_live_complete_binding(tmp_path, changed):
    chat, owner = budget_chat(tmp_path)
    asyncio.run(chat._persist_load_recovery_budget("increment", expected=(0, 0)))
    healthy = ChatSnapshot.from_bridge({"url": chat.chat_url, "composerPresent": True})
    chat._load_budget_observation = (healthy, (1, 1), chat._binding_token(healthy))
    async def page(_handle):
        return SimpleNamespace(target_id="recycled" if changed == "target" else "target",
            url=chat.chat_url + "-foreign" if changed == "conversation" else chat.chat_url)
    chat._gpt_browser = lambda: SimpleNamespace(page_by_handle=page)
    if changed == "provider-session":
        chat.provider_session_id = "foreign"
    asyncio.run(chat._reset_load_recovery_budget_after_positive_snapshot(healthy))
    assert sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner) == (1, 1)


def test_real_load_replacement_commit_failure_keeps_original_binding(tmp_path, monkeypatch):
    chat, _ = budget_chat(tmp_path)
    chat.page_handle = "retained"
    released = []
    created = []
    chat.runtime.release_page = lambda *args: released.append(args)
    async def create():
        created.append(True)
    chat._create_recovery_page = create
    def fail(*args, **kwargs):
        raise OSError("session commit failed")
    monkeypatch.setattr(sessions_store, "write_session_record", fail)
    failed = ChatSnapshot.from_bridge({"url": chat.chat_url, "domSignals": {"conversation-load-failed": True}})
    with pytest.raises(OSError, match="session commit failed"):
        asyncio.run(chat._replace_load_failed_page(failed))
    assert chat.page_handle == "retained"
    assert released == created == []


def test_real_readiness_replacement_and_positive_reset_without_submission_stage(tmp_path):
    chat, owner = budget_chat(tmp_path)
    record = sessions_store.read_session_record(tmp_path, "ses-unsent")
    record["provider"]["metadata"] = {"project-id": "g-p-audiagentic-exact"}
    sessions_store.write_session_record(tmp_path, record)
    navigated = []
    chat.config.workflow.bridge_signals = lambda: {}
    async def page(handle):
        return SimpleNamespace(handle=handle, target_id="replacement-target")
    async def snapshot(_page, **kwargs):
        return {"url": chat.chat_url, "composerPresent": True, "composerEditable": True}
    browser = SimpleNamespace(page_by_handle=page, snapshot=snapshot)
    chat._gpt_browser = lambda: browser
    async def create():
        assert sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner) == (1, 1)
        return "replacement"
    async def bridge_call(action, params, **kwargs):
        navigated.append(action)
    chat._create_recovery_page = create
    chat.runtime.bridge = SimpleNamespace(call=bridge_call)
    chat._wait_ready = lambda: chat.snapshot(allow_recovering=True)
    failed = ChatSnapshot.from_bridge({"url": chat.chat_url, "domSignals": {"conversation-load-failed": True}})
    assert asyncio.run(chat._replace_load_failed_page(failed)) is True
    assert navigated == ["navigate"]
    assert sessions_store.owned_conversation_load_budget(tmp_path, "ses-unsent", "req-unsent", **owner) == (0, 2)
    current = sessions_store.session_provider_metadata(sessions_store.read_session_record(tmp_path, "ses-unsent"))
    assert "submission-state" not in current and "unresolved-turn-pending" not in current


def setup_attempt(root):
    owner = dict(dispatch_owner_epoch="owner", worker_id="worker", attempt_epoch=1)
    metadata = {
        "project-id": "g-p-audiagentic-exact",
        "unresolved-turn-id": "req-unsent",
        "unresolved-turn-pending": True,
        "submission-state": "dispatching",
        "submission-stage": "composer-focused",
        "submission-attempt-id": "attempt-original",
        "send-intent-ever": False,
        "submission-proven": False,
        "prompt-text-digest": "digest",
    }
    session = sessions_store.build_session_record(
        session_id="ses-unsent", created_by_request_id="req-unsent",
        provider_transport_kind="provider-session", execution_profile_id="gpt-auto",
        provider_id="gpt-auto", model_id="chatgpt", provider_metadata=metadata,
    )
    sessions_store.write_session_record(root, session)
    request = store.build_record(
        request_id="req-unsent", execution_profile_id="gpt-auto", prompt_body="test",
        session_id="ses-unsent", resolved_provider_id="gpt-auto",
    )
    request.update({"state": "running", "worker-id": "worker", "attempt-epoch": 1,
                    "dispatch-owner-epoch": "owner", "provider-metadata": {"project-id": metadata["project-id"]}})
    store.write_record(root, request)
    return owner, metadata


def test_real_provider_unsent_retirement_can_prepare_same_request_again(tmp_path):
    owner, metadata = setup_attempt(tmp_path)
    sink = sessions._make_submission_checkpoint_sink(
        tmp_path, "ses-unsent", request_id="req-unsent", **owner,
    )
    chat = SimpleNamespace(_checkpoint_metadata=dict(metadata), _submission_proven=False,
                           _persist_checkpoint=sink)
    asyncio.run(PersistentChat.persist_proven_unsent_clear(chat))
    current = sessions_store.session_provider_metadata(sessions_store.read_session_record(tmp_path, "ses-unsent"))
    assert current == {"project-id": metadata["project-id"], "unresolved-turn-pending": False}
    assert chat._checkpoint_metadata == {}
    # Same logical request and owner, new provider attempt: no stage rollback.
    asyncio.run(sink({
        "submission-state": "prepared", "submission-proven": False,
        "unresolved-turn-pending": True, "unresolved-turn-id": "req-unsent",
        "prompt-text-digest": "digest", "recovery-state": "submission-prepared",
    }))
    assert sessions_store.session_provider_metadata(
        sessions_store.read_session_record(tmp_path, "ses-unsent")
    )["submission-state"] == "prepared"


@pytest.mark.parametrize("mutation", [
    {"send-intent-ever": True}, {"submission-stage": "send-intent"},
    {"submission-proven": True}, {"unresolved-turn-id": "req-successor"},
    {"submission-attempt-id": "attempt-successor"},
    {"submission-recovery-claim": "claim"}, {"submission-recovery-generation": 2},
    {"unresolved-turn-pending": False},
])
def test_unsent_retirement_cannot_clear_unsafe_or_successor_attempt(tmp_path, mutation):
    owner, metadata = setup_attempt(tmp_path)
    record = sessions_store.read_session_record(tmp_path, "ses-unsent")
    record["provider"]["metadata"].update(mutation)
    sessions_store.write_session_record(tmp_path, record)
    before = sessions_store.session_provider_metadata(record)
    with pytest.raises(AudiaGenticError):
        sessions_store.clear_owned_unsent_submission_checkpoint(
            tmp_path, "ses-unsent", "req-unsent", submission_attempt_id="attempt-original", **owner,
        )
    assert sessions_store.session_provider_metadata(
        sessions_store.read_session_record(tmp_path, "ses-unsent")
    ) == before


@pytest.mark.parametrize("mutation", [
    {"worker-id": "new-worker"}, {"dispatch-owner-epoch": "new-owner"},
    {"attempt-epoch": 2}, {"recovery-required": True},
])
def test_unsent_retirement_rejects_lost_dispatch_authority(tmp_path, mutation):
    owner, metadata = setup_attempt(tmp_path)
    request = store.read_record(tmp_path, "req-unsent")
    request.update(mutation)
    store.write_record(tmp_path, request)
    with pytest.raises(AudiaGenticError):
        sessions_store.clear_owned_unsent_submission_checkpoint(
            tmp_path, "ses-unsent", "req-unsent", submission_attempt_id="attempt-original", **owner,
        )
    assert sessions_store.session_provider_metadata(
        sessions_store.read_session_record(tmp_path, "ses-unsent")
    ) == metadata


def test_real_pre_send_checkpoint_freezes_latest_anchor_for_repeated_prompts():
    recorded = []

    async def persist(metadata):
        recorded.append(metadata)

    chat = SimpleNamespace(
        _checkpoint_metadata={}, _submission_proven=False,
        _conversation_load_recovery_attempts=0, unresolved_prompt_text_digest="digest",
        unresolved_metadata=lambda: {"unresolved-turn-pending": True, "submission-proven": False},
        _persist_checkpoint=persist,
    )
    baseline = ChatSnapshot.from_bridge({
        "url": "https://chatgpt.com/c/example", "userCount": 5, "assistantCount": 5,
        "latestUserId": "latest-existing", "latestAssistantId": "latest-answer",
        "messageRefs": [
            {"role": "user", "messageId": "older-existing", "text": "same prompt", "sequence": 0},
            {"role": "assistant", "messageId": "older-answer", "text": "same answer", "sequence": 1},
            {"role": "user", "messageId": "latest-existing", "text": "same prompt", "sequence": 2},
            {"role": "assistant", "messageId": "latest-answer", "text": "same answer", "sequence": 3},
        ],
    })
    asyncio.run(PersistentChat.persist_unresolved_checkpoint(chat, turn_id="new-request", baseline=baseline))
    anchor = recorded[-1]["unresolved-baseline-user-id"]
    assert anchor == "latest-existing"
    assert not baseline.has_ordered_message_advance("user", anchor, "older-existing")
    assert not baseline.has_ordered_message_advance("user", anchor, "latest-existing")
    from dataclasses import replace
    current = replace(baseline, message_refs=baseline.message_refs + (
        ChatMessageRef("user", "actually-new", "same prompt", 4),
    ))
    assert current.has_ordered_message_advance("user", anchor, "actually-new")


def test_owned_manual_annotation_preserves_entire_proven_checkpoint(tmp_path):
    owner, metadata = setup_attempt(tmp_path)
    record = sessions_store.read_session_record(tmp_path, "ses-unsent")
    record["provider"]["metadata"].update({
        "submission-state": "proven", "submission-proven": True,
        "send-intent-ever": True, "submission-stage": "send-click-acknowledged",
    })
    sessions_store.write_session_record(tmp_path, record)
    expected = dict(record["provider"]["metadata"])
    expected["recovery-state"] = "manual-reconcile-required"
    for _ in range(2):  # Repeating the diagnostic annotation is harmless.
        sessions_store.annotate_owned_manual_reconciliation(tmp_path, "ses-unsent", "req-unsent", **owner)
        assert sessions_store.session_provider_metadata(
            sessions_store.read_session_record(tmp_path, "ses-unsent")
        ) == expected


@pytest.mark.parametrize("mutation", [
    {"unresolved-turn-id": "successor"}, {"unresolved-turn-pending": False},
    {"project-id": "g-p-other-project"},
])
def test_manual_annotation_cannot_touch_foreign_or_resolved_checkpoint(tmp_path, mutation):
    owner, metadata = setup_attempt(tmp_path)
    record = sessions_store.read_session_record(tmp_path, "ses-unsent")
    record["provider"]["metadata"].update(mutation)
    sessions_store.write_session_record(tmp_path, record)
    before = sessions_store.session_provider_metadata(record)
    with pytest.raises(AudiaGenticError):
        sessions_store.annotate_owned_manual_reconciliation(tmp_path, "ses-unsent", "req-unsent", **owner)
    assert sessions_store.session_provider_metadata(
        sessions_store.read_session_record(tmp_path, "ses-unsent")
    ) == before


@pytest.mark.parametrize("mutation", [
    {"worker-id": "new-worker"}, {"dispatch-owner-epoch": "new-owner"},
    {"attempt-epoch": 2}, {"state": "interrupted"},
])
def test_manual_annotation_rejects_stale_or_retired_owner(tmp_path, mutation):
    owner, metadata = setup_attempt(tmp_path)
    record = store.read_record(tmp_path, "req-unsent")
    record.update(mutation)
    store.write_record(tmp_path, record)
    with pytest.raises(AudiaGenticError):
        sessions_store.annotate_owned_manual_reconciliation(tmp_path, "ses-unsent", "req-unsent", **owner)
    assert sessions_store.session_provider_metadata(
        sessions_store.read_session_record(tmp_path, "ses-unsent")
    ) == metadata
