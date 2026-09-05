"""Restart controls stay authenticated and replace code only after host cleanup."""
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from audiagentic.components.agents.gateway.service import process
from audiagentic.components.agents.gateway.service.http_transport import GatewayHTTPServer


def test_restart_reexecutes_after_close_with_original_args(monkeypatch):
    events = []
    host = SimpleNamespace(
        lifecycle=SimpleNamespace(restart_requested=True),
        serve_forever=lambda: events.append("serve"),
        close=lambda: events.append("close"),
    )
    monkeypatch.setattr(process.GatewayServiceHost, "create", lambda **kwargs: host)
    monkeypatch.setenv("AUDIAGENTIC_SERVICE_OWNER_EPOCH", "old")
    launches = []
    monkeypatch.setattr(process.subprocess, "Popen", lambda args, **kwargs: (events.append(args), launches.append(kwargs)))
    args = ["--port", "8765", "--token-file", "token", "--service-root", "custom"]
    process.main(args)
    assert events[:2] == ["serve", "close"]
    assert events[2][3:] == args
    assert "AUDIAGENTIC_SERVICE_OWNER_EPOCH" not in launches[0]["env"]
    assert launches[0]["stdin"] == process.subprocess.DEVNULL
    assert launches[0]["stdout"] == process.subprocess.DEVNULL
    assert launches[0]["stderr"] == process.subprocess.DEVNULL
    if process.sys.platform == "win32":
        assert launches[0]["creationflags"] == process.subprocess.CREATE_NO_WINDOW
    assert host.lifecycle.restart_enabled


@pytest.mark.parametrize("action", ["restart", "cancel-request", "project-image"])
def test_dashboard_action_requires_token_same_origin_and_closed_body(action):
    application = SimpleNamespace(
        dashboard_action_token="test-token",
        restart_dashboard_gateway=Mock(return_value={"restarting": True, "owner-epoch": "old"}),
        cancel_dashboard_request=Mock(return_value={"outcome": "cancellation-requested"}),
        dashboard_project_image=Mock(return_value=b""),
    )
    server = GatewayHTTPServer(("127.0.0.1", 0), application, "secret", dashboard_path="/operator")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/operator/{action}"
    try:
        for headers, body, status in [
            ({}, {}, 401),
            ({"X-AudiaGentic-Dashboard-Token": "test-token", "Origin": "https://evil.example"}, {}, 401),
            ({"X-AudiaGentic-Dashboard-Token": "test-token"}, {"force": True}, 400),
        ]:
            with pytest.raises(HTTPError) as error:
                # Authentication is rejected before reading a body. Send no
                # body for these probes to avoid Windows resetting a socket
                # with unread bytes instead of delivering the 401 response.
                payload = b"" if status == 401 else json.dumps(body).encode()
                urlopen(Request(endpoint, data=payload, headers=headers), timeout=2)
            assert error.value.code == status
        application.restart_dashboard_gateway.assert_not_called()
        application.cancel_dashboard_request.assert_not_called()
        application.dashboard_project_image.assert_not_called()
        payload = {"restart": b"{}", "cancel-request": b'{"request-id":"req_test"}', "project-image": b'{"project-id":"test","png":"image"}'}[action]
        with urlopen(Request(endpoint, data=payload, headers={"X-AudiaGentic-Dashboard-Token": "test-token"}), timeout=2) as response:
            assert response.status == (202 if action == "restart" else 200)
            assert json.load(response)["ok"]
        if action == "restart":
            application.restart_dashboard_gateway.assert_called_once()
        elif action == "cancel-request":
            application.cancel_dashboard_request.assert_called_once_with("req_test")
        else:
            application.dashboard_project_image.assert_called_once_with("test", "image")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
