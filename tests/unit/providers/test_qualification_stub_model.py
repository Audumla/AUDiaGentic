"""The local stub model used by disposable qualification probes: loopback only, deterministic, gate-held, counts only."""
from __future__ import annotations

import http.client
import json
import threading

from audiagentic.components.providers.services.qualification.probes.stub_model import StubModel


def _post(stub: StubModel, path: str = "/v1/responses", body: dict | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", int(stub.base_url.rsplit(":", 1)[1].split("/")[0]), timeout=10)
    connection.request("POST", path, json.dumps(body or {"input": [1, 2, 3]}), {"content-type": "application/json"})
    return connection, connection.getresponse()


def _events(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith("data: ")]


def test_it_binds_loopback_on_an_os_port_and_replies_deterministically_by_ordinal():
    stub = StubModel().start()
    try:
        assert stub.base_url.startswith("http://127.0.0.1:") and stub.base_url.endswith("/v1")
        connection, response = _post(stub)
        events = _events(response)
        assert response.status == 200 and events[0]["type"] == "response.created"
        assert events[-1]["type"] == "response.completed"
        assert "STUB-REPLY-1" in json.dumps(events[-1])
        assert [event["sequence_number"] for event in events] == list(range(len(events)))
        connection.close()
        _post(stub)[1].read()
        assert stub.requests == 2 and stub.input_items == [3, 3]
    finally:
        stub.stop()


def test_the_gate_holds_a_response_open_until_released_without_sleeps():
    stub = StubModel().start()
    try:
        stub.hold()
        result: dict = {}

        def call() -> None:
            connection, response = _post(stub)
            result["events"] = _events(response)
            connection.close()

        worker = threading.Thread(target=call)
        worker.start()
        assert stub.wait_for_requests(1, 10)  # the request arrived and is being held
        worker.join(timeout=0.3)
        assert worker.is_alive() and "events" not in result  # still open: a deterministic busy window
        stub.release()
        worker.join(timeout=10)
        assert result["events"][-1]["type"] == "response.completed"
    finally:
        stub.stop()


def test_any_other_request_is_recorded_so_a_probe_can_fail_closed():
    stub = StubModel().start()
    try:
        _post(stub, "/v1/other")[1].read()
        connection = http.client.HTTPConnection("127.0.0.1", int(stub.base_url.rsplit(":", 1)[1].split("/")[0]), timeout=10)
        connection.request("GET", "/v1/models")
        connection.getresponse().read()
        assert stub.unexpected == ["POST /v1/other", "GET /v1/models"] and stub.requests == 0
    finally:
        stub.stop()


def test_the_config_points_only_at_the_stub_and_needs_no_sign_in(tmp_path):
    stub = StubModel().start()
    try:
        stub.write_config(tmp_path, tmp_path / "ws")
        text = (tmp_path / "config.toml").read_text()
        assert stub.base_url in text and "requires_openai_auth = false" in text and 'model_provider = "stub"' in text
        assert "api.openai.com" not in text and "http://127.0.0.1:" in text
    finally:
        stub.stop()
