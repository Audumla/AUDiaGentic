"""Caller labels and real ACP work must survive the public gateway seams."""
from pathlib import Path
from unittest.mock import patch

import pytest

from audiagentic.components.agents.gateway import api
from audiagentic.components.agents.gateway.activity import RequestActivityRelay
from audiagentic.components.agents.gateway.service.dashboard import _request_row
from audiagentic.components.agents.mcp import gateway_mcp
from audiagentic.foundation.transports.acp import AcpEvent, _map_acp_event_to_observation


@pytest.mark.parametrize("title", ["", " ", "x" * 121, "two\nlines", 123])
def test_invalid_title_rejected_before_admission(tmp_path, title):
    with pytest.raises(Exception, match="title must be"):
        api.submit_execution_request(tmp_path, title=title)


def test_caller_title_forwarded_and_visible_without_execution_identity():
    with patch.object(gateway_mcp, "project_root_from_env", return_value=Path(".")), patch.object(
        gateway_mcp, "call_gateway_method", return_value={"request-id": "req_test"}
    ) as submit:
        gateway_mcp.agent_task_submit("luna", prompt_body="Do work", title="Review lifecycle")
    assert submit.call_args.kwargs["title"] == "Review lifecycle"
    row = _request_row({"request-id": "req_test", "title": "Review lifecycle"}, include_execution=False)
    assert row["title"] == "Review lifecycle"


@pytest.mark.parametrize("kind,phase", [("assistant-message", "response-progress"), ("thought", "thinking")])
def test_acp_content_renews_activity_without_leaking_body(tmp_path, kind, phase):
    event = AcpEvent(sequence=1, kind=kind, timestamp="2026-01-01T00:00:00Z",
                     session_id="backend", text="private content", terminal=False,
                     error=None, ext={"acp": {}})
    observation = _map_acp_event_to_observation(event, "ses_test", "req_test")
    relay = RequestActivityRelay(tmp_path, "req_test", owner_epoch="owner", worker_id="worker", attempt_epoch=1)
    with patch("audiagentic.components.agents.gateway.activity.store.record_owned_activity") as record:
        for sequence in [1, 1]:
            relay.observe_provider(source_sequence=sequence, source_instance="turn", phase=observation.attributes["model_activity"])
        assert record.call_count == 1
        assert record.call_args.kwargs["phase"] == phase
        assert "private content" not in str(record.call_args)
        relay.observe_provider(source_sequence=2, source_instance="turn", phase="heartbeat")
        relay.observe_provider(source_sequence=3, source_instance="turn", phase="transport-error")
        assert record.call_count == 1
