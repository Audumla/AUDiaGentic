from __future__ import annotations

import json
import time
from urllib.error import URLError

import pytest

from audiagentic.components.agents.gateway import remote_client as agents_gateway_remote_client
from audiagentic.components.agents.gateway.client import (
    get_gateway_client,
    reset_gateway_client,
)
from audiagentic.components.agents.gateway.remote_client import StandaloneGatewayClient
from audiagentic.components.agents.gateway.service import bootstrap as agents_gateway_bootstrap
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_remote_client_rejects_non_loopback_or_credential_bearing_endpoint() -> None:
    for endpoint in (
        "http://0.0.0.0:9000",
        "https://127.0.0.1:9000",
        "http://user@127.0.0.1:9000",
        "http://127.0.0.1:9000/path",
        "http://127.0.0.1:not-a-port",
    ):
        with pytest.raises(AudiaGenticError, match="VAL-AGSV-016"):
            StandaloneGatewayClient(endpoint, "token")


def test_protocol_mismatch_is_rejected_before_lease_acquisition(monkeypatch) -> None:
    client = StandaloneGatewayClient("http://127.0.0.1:9000", "token")
    monkeypatch.setattr(
        client,
        "health",
        lambda: {"protocol-version": "future", "owner-epoch": "epoch-a"},
    )

    with pytest.raises(AudiaGenticError, match="VAL-AGSV-013"):
        client.connect()


def test_standalone_mode_requires_explicit_endpoint_and_token_file(monkeypatch) -> None:
    reset_gateway_client()
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_MODE", "standalone")
    monkeypatch.delenv("AUDIAGENTIC_GATEWAY_ENDPOINT", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_GATEWAY_TOKEN_FILE", raising=False)

    with pytest.raises(AudiaGenticError, match="CFG-AGSV-001"):
        get_gateway_client()
    reset_gateway_client()


def test_unknown_gateway_mode_has_no_silent_fallback(monkeypatch) -> None:
    reset_gateway_client()
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_MODE", "future")

    with pytest.raises(AudiaGenticError, match="CFG-AGSV-002"):
        get_gateway_client()
    reset_gateway_client()


def test_automatic_mode_uses_gateway_bootstrap(monkeypatch) -> None:

    marker = object()
    reset_gateway_client()
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_MODE", "automatic")
    monkeypatch.setattr(agents_gateway_bootstrap, "start_or_attach_gateway", lambda: marker)

    assert get_gateway_client() is marker
    reset_gateway_client()


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps({
            "ok": True,
            "result": {"protocol-version": "gateway-service-v1", "owner-epoch": "epoch-a"},
        }).encode("utf-8")


def test_health_has_one_bounded_network_retry(monkeypatch) -> None:
    calls = 0

    def flaky_urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise URLError("transient")
        return _Response()

    monkeypatch.setattr(agents_gateway_remote_client, "urlopen", flaky_urlopen)
    monkeypatch.setattr(agents_gateway_remote_client.time, "sleep", lambda _value: None)
    client = StandaloneGatewayClient("http://127.0.0.1:9000", "token")

    assert client.health()["owner-epoch"] == "epoch-a"
    assert calls == 2


def test_domain_mutation_is_not_network_retried(monkeypatch, tmp_path) -> None:
    calls = 0

    def unavailable(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise URLError("unavailable")

    monkeypatch.setattr(agents_gateway_remote_client, "urlopen", unavailable)
    client = StandaloneGatewayClient("http://127.0.0.1:9000", "token")
    client._lease_id = "lease-test"
    client._owner_epoch = "epoch-test"
    client._renew_at = time.monotonic() + 10

    with pytest.raises(AudiaGenticError, match="NET-AGSV-002"):
        client.gateway_overview(tmp_path)
    assert calls == 1


def test_managed_lease_is_adopted_without_second_acquisition(monkeypatch) -> None:
    client = StandaloneGatewayClient("http://127.0.0.1:9000", "token")
    monkeypatch.setattr(
        client,
        "health",
        lambda: {"protocol-version": "gateway-service-v1", "owner-epoch": "epoch-a"},
    )

    client.adopt_managed_lease(
        "lease-a", "epoch-a", lifetime_scope="shared-service-host"
    )

    assert client.connect()["owner-epoch"] == "epoch-a"
    assert client._lease_id == "lease-a"


def test_submit_forwards_calling_component_profile(monkeypatch, tmp_path) -> None:
    client = StandaloneGatewayClient("http://127.0.0.1:9000", "token")
    captured: dict = {}
    monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "calling-profile")
    monkeypatch.setattr(
        client,
        "_call",
        lambda operation, root, params, **_kwargs: captured.update(
            operation=operation, root=root, params=params
        ) or {"state": "queued"},
    )

    assert client.submit_execution_request(tmp_path, prompt_body="hello") == {"state": "queued"}
    assert captured["params"]["component_profile"] == "calling-profile"
