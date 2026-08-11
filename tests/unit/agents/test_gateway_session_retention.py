from __future__ import annotations

from audiagentic.components.agents.gateway.session.retention import request_retention_pin
from audiagentic.components.agents.gateway.session.sessions_store import (
    build_session_record,
    record_session_turn,
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
