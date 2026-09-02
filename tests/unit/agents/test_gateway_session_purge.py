from pathlib import Path

from audiagentic.components.agents.agents_paths import gateway_request_dir, gateway_session_dir
from audiagentic.components.agents.gateway import api, store
from audiagentic.components.agents.gateway.session import sessions_store


def test_purge_session_removes_terminal_requests_and_session_data(tmp_path: Path) -> None:
    session_id = "ses_purge_dashboard"
    request_id = "req_purge_dashboard"
    session = sessions_store.build_session_record(
        session_id=session_id,
        execution_profile_id="test",
    )
    session["activity"]["request-ids"] = [request_id]
    sessions_store.write_session_record(tmp_path, session)
    sessions_store.transition_session_record(tmp_path, session_id, "closed", updates={"close-reason": "client-request"})

    request = store.build_record(
        request_id=request_id,
        execution_profile_id="test",
        prompt_body="test",
        session_id=session_id,
    )
    store.write_record(tmp_path, request)
    store.transition_record(tmp_path, request_id, "running")
    store.transition_record(tmp_path, request_id, "completed")
    (gateway_request_dir(tmp_path, request_id) / "output").mkdir(parents=True, exist_ok=True)
    (gateway_request_dir(tmp_path, request_id) / "output" / "final-response.txt").write_text("done", encoding="utf-8")

    result = api.purge_execution_session(tmp_path, session_id)

    assert result == {"session-id": session_id, "outcome": "purged", "request-count": 1}
    assert not gateway_session_dir(tmp_path, session_id).exists()
    assert not gateway_request_dir(tmp_path, request_id).exists()


def test_purge_session_blocks_non_terminal_request(tmp_path: Path) -> None:
    session_id = "ses_purge_dashboard_blocked"
    request_id = "req_purge_dashboard_blocked"
    session = sessions_store.build_session_record(
        session_id=session_id,
        execution_profile_id="test",
    )
    session["activity"]["request-ids"] = [request_id]
    sessions_store.write_session_record(tmp_path, session)
    sessions_store.transition_session_record(tmp_path, session_id, "closed", updates={"close-reason": "client-request"})
    store.write_record(
        tmp_path,
        store.build_record(
            request_id=request_id,
            execution_profile_id="test",
            prompt_body="test",
            session_id=session_id,
        ),
    )

    result = api.purge_execution_session(tmp_path, session_id)

    assert result["outcome"] == "blocked"
    assert result["reason"] == "session-has-active-requests"
    assert gateway_session_dir(tmp_path, session_id).exists()
