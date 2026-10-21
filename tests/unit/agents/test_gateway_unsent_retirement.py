"""A proven no-Send retry retires its exact attempt, never a successor."""
import asyncio
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.session import sessions, sessions_store
from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.snapshot import ChatMessageRef, ChatSnapshot
from audiagentic.foundation.contracts.errors import AudiaGenticError


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
