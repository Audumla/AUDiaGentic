from __future__ import annotations

from audiagentic.components.agents.agents_paths import gateway_request_dir
from audiagentic.components.agents.gateway.session.retention import request_retention_pin
from audiagentic.components.agents.gateway.session.root_registry import (
    register_session_root,
    unregister_session_root,
)
from audiagentic.components.agents.gateway.session.sessions_store import (
    build_session_record,
    record_session_turn,
    read_session_record,
    update_provider_metadata,
    write_session_record,
)


def test_request_referenced_by_durable_session_is_retention_pinned(tmp_path):
    record = build_session_record(session_id="ses_retained", execution_profile_id="review")
    write_session_record(tmp_path, record)
    record_session_turn(tmp_path, "ses_retained", "req_continuation")

    pin = request_retention_pin(tmp_path, "req_continuation")

    assert pin.pinned is True
    assert pin.reason == "session-lineage-reference"


def test_unreferenced_request_is_not_retention_pinned(tmp_path):
    assert request_retention_pin(tmp_path, "req_unreferenced").pinned is False


def test_provider_metadata_checkpoint_updates_and_clears_only_checkpoint_fields(tmp_path):
    record = build_session_record(
        session_id="ses_checkpoint",
        execution_profile_id="review",
        provider_id="gpt-auto",
        provider_metadata={"chat-url": "https://chatgpt.com/c/existing"},
    )
    write_session_record(tmp_path, record)
    update_provider_metadata(
        tmp_path,
        "ses_checkpoint",
        {
            "unresolved-turn-pending": True,
            "recovery-state": "side-effect-may-have-started",
            "unresolved-turn-id": "turn-1",
        },
    )
    pending = read_session_record(tmp_path, "ses_checkpoint")
    assert pending["provider"]["metadata"]["unresolved-turn-pending"] is True
    assert pending["provider"]["metadata"]["chat-url"].endswith("existing")

    update_provider_metadata(
        tmp_path,
        "ses_checkpoint",
        {"unresolved-turn-pending": False},
        remove_keys=("recovery-state", "unresolved-turn-id"),
    )
    cleared = read_session_record(tmp_path, "ses_checkpoint")
    assert cleared["provider"]["metadata"] == {
        "chat-url": "https://chatgpt.com/c/existing",
        "unresolved-turn-pending": False,
    }


def test_durable_request_runtime_root_is_retention_pinned(tmp_path):
    runtime = gateway_request_dir(tmp_path, "req_runtime") / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "provider-state.json").write_text("{}", encoding="utf-8")

    pin = request_retention_pin(tmp_path, "req_runtime")

    assert pin.pinned is True
    assert pin.reason == "durable-runtime-root"


def test_empty_runtime_root_does_not_create_false_retention_pin(tmp_path):
    runtime = gateway_request_dir(tmp_path, "req_empty") / "runtime"
    runtime.mkdir(parents=True)

    pin = request_retention_pin(tmp_path, "req_empty")

    assert pin.pinned is False
    assert pin.reason is None


def test_relocated_session_root_registry_pins_request_until_explicit_release(tmp_path):
    register_session_root(
        tmp_path,
        session_id="ses_relocated",
        request_ids=("req_relocated",),
        root=tmp_path / "sessions" / "ses_relocated",
    )
    pinned = request_retention_pin(tmp_path, "req_relocated")
    assert pinned.pinned is True
    assert pinned.reason == "relocated-session-lineage"
    unregister_session_root(tmp_path, session_id="ses_relocated")
    assert request_retention_pin(tmp_path, "req_relocated").pinned is False
