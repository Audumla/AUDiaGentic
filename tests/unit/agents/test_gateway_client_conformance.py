"""SH11 Slice D: conformance matrix.

Proves the same logical gateway operation produces the same canonical
result shape regardless of which client implementation answers it --
the actual property "declarative switching" needs to be safe. `automatic`
is not given its own fake here: `start_or_attach_gateway()` returns a
`StandaloneGatewayClient` (see gateway/service/bootstrap.py), so standalone's
conformance already covers it structurally; a live automatic-mode proof
needs a real spawned service and belongs in the Docker/integration suite,
not here.
"""
from __future__ import annotations

import json
import time
from typing import Any

import pytest

from audiagentic.components.agents.gateway import remote_client as agents_gateway_remote_client
from audiagentic.components.agents.gateway.client import EmbeddedGatewayClient
from audiagentic.components.agents.gateway.remote_client import StandaloneGatewayClient


class _FakeApplication:
    """Backs EmbeddedGatewayClient with a canned canonical response per operation."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((name, args, kwargs))
        return self._responses[name]

    def submit_execution_request(self, project_root, **kwargs):
        return self._record("submit_execution_request", project_root, **kwargs)

    def get_execution_request(self, project_root, request_id):
        return self._record("get_execution_request", project_root, request_id=request_id)

    def cancel_execution_request(self, project_root, request_id):
        return self._record("cancel_execution_request", project_root, request_id=request_id)

    def open_agent_context(self, project_root, agent_id, title=None):
        return self._record("open_agent_context", project_root, agent_id, title)

    def get_agent_context(self, project_root, context_id):
        return self._record("get_agent_context", project_root, context_id)

    def list_agent_contexts(self, project_root):
        return self._record("list_agent_contexts", project_root)

    def close_agent_context(self, project_root, context_id):
        return self._record("close_agent_context", project_root, context_id)

    def submit_agent_work(self, project_root, context_id, message, **kwargs):
        return self._record("submit_agent_work", project_root, context_id, message, **kwargs)

    def get_agent_work(self, project_root, work_id):
        return self._record("get_agent_work", project_root, work_id)

    def list_agent_work(self, project_root):
        return self._record("list_agent_work", project_root)

    def add_agent_work_message(self, project_root, work_id, message):
        return self._record("add_agent_work_message", project_root, work_id, message)

    def cancel_agent_work(self, project_root, work_id):
        return self._record("cancel_agent_work", project_root, work_id)

    def read_agent_work_output(self, project_root, work_id):
        return self._record("read_agent_work_output", project_root, work_id)


class _FakeHttpResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps({"ok": True, "result": self._payload}).encode("utf-8")


def _standalone_client_with_canned_response(monkeypatch, payload: dict[str, Any]) -> StandaloneGatewayClient:
    """A StandaloneGatewayClient whose lease is pre-seeded (matching this
    file's neighbor test_gateway_remote_client.py's own pattern for
    bypassing the connect/health handshake) and whose HTTP transport
    returns exactly `payload` as the operation result."""
    client = StandaloneGatewayClient("http://127.0.0.1:9000", "token")
    client._lease_id = "lease-conformance"
    client._owner_epoch = "epoch-conformance"
    client._renew_at = time.monotonic() + 60
    monkeypatch.setattr(
        agents_gateway_remote_client, "urlopen", lambda *a, **k: _FakeHttpResponse(payload)
    )
    return client


_CANONICAL_SUBMIT_RESULT = {
    "request-id": "req_conformance123",
    "state": "queued",
    "session-id": None,
    "metadata": {},
}
_CANONICAL_STATUS_RESULT = {
    "request-id": "req_conformance123",
    "state": "completed",
    "output": "ok",
}
_CANONICAL_CANCEL_RESULT = {
    "request-id": "req_conformance123",
    "state": "cancelled",
}

_CANONICAL_WORK_RESULT = {"work_id": "work_1", "state": "active"}


@pytest.mark.parametrize(
    "operation, canonical_result, call_kwargs",
    [
        ("submit_execution_request", _CANONICAL_SUBMIT_RESULT, {"prompt_body": "hello"}),
        ("get_execution_request", _CANONICAL_STATUS_RESULT, {"request_id": "req_conformance123"}),
        ("cancel_execution_request", _CANONICAL_CANCEL_RESULT, {"request_id": "req_conformance123"}),
        ("get_agent_work", _CANONICAL_WORK_RESULT, {"work_id": "work_1"}),
        ("cancel_agent_work", {**_CANONICAL_WORK_RESULT, "state": "cancelled"}, {"work_id": "work_1"}),
        ("read_agent_work_output", {"work_id": "work_1", "events": []}, {"work_id": "work_1"}),
    ],
)
def test_embedded_and_standalone_produce_the_same_canonical_result(
    monkeypatch, tmp_path, operation, canonical_result, call_kwargs
):
    """The load-bearing conformance assertion: identical logical inputs
    produce an identical canonical output shape across implementations."""
    fake_app = _FakeApplication({operation: canonical_result})
    embedded = EmbeddedGatewayClient(fake_app)  # type: ignore[arg-type]
    standalone = _standalone_client_with_canned_response(monkeypatch, canonical_result)

    embedded_result = getattr(embedded, operation)(tmp_path, **call_kwargs)
    standalone_result = getattr(standalone, operation)(tmp_path, **call_kwargs)

    assert embedded_result == canonical_result
    assert standalone_result == canonical_result
    assert embedded_result == standalone_result


def test_automatic_mode_returns_a_standalone_client_not_a_third_implementation():
    """Confirms automatic's conformance is covered by standalone's, rather
    than needing its own separate fake here -- see this module's docstring."""
    import inspect

    from audiagentic.components.agents.gateway.service.bootstrap import start_or_attach_gateway

    return_annotation = inspect.signature(start_or_attach_gateway).return_annotation
    assert return_annotation in ("StandaloneGatewayClient", StandaloneGatewayClient)


def test_both_implementations_satisfy_the_same_protocol_method_set():
    """Structural conformance: the same method names, not just the same
    return shapes for the three sampled operations above."""
    from audiagentic.components.agents.gateway.client import GatewayClient

    protocol_methods = {
        name for name in dir(GatewayClient) if not name.startswith("_")
    }
    embedded_methods = {name for name in dir(EmbeddedGatewayClient) if not name.startswith("_")}
    standalone_methods = {name for name in dir(StandaloneGatewayClient) if not name.startswith("_")}
    assert protocol_methods <= embedded_methods
    assert protocol_methods <= standalone_methods
