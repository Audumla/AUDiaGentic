from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.agents import agents_gateway_bootstrap as bootstrap
from audiagentic.components.agents.agents_gateway_service_application import PROTOCOL_VERSION
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_automatic_gateway_declares_one_foundation_managed_service(monkeypatch, tmp_path):
    captured = {}

    class FakeStore:
        def __init__(self, key):
            self.key = key
            self.root = tmp_path / "service"

    class FakeLifecycle:
        def __init__(self, store, hooks):
            captured["store"] = store
            captured["hooks"] = hooks

        def start_or_attach(self, declaration, **kwargs):
            captured["declaration"] = declaration
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                lease=SimpleNamespace(lease_id="lease-a"),
                record=SimpleNamespace(
                    owner_epoch="epoch-a",
                    process=SimpleNamespace(scope="shared-service-host"),
                ),
            )

    class FakeClient:
        def __init__(self, endpoint, token, **kwargs):
            captured["client"] = (endpoint, token, kwargs)

        def adopt_managed_lease(self, lease_id, owner_epoch, *, lifetime_scope):
            captured["adopted"] = (lease_id, owner_epoch, lifetime_scope)

    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_PORT", "9123")
    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(tmp_path / "caller-project"))
    monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "caller-profile")
    monkeypatch.setattr(bootstrap, "ManagedServiceStore", FakeStore)
    monkeypatch.setattr(bootstrap, "ManagedServiceLifecycle", FakeLifecycle)
    monkeypatch.setattr(bootstrap, "StandaloneGatewayClient", FakeClient)
    monkeypatch.setattr(bootstrap, "load_auth_token", lambda path: f"token:{Path(path).name}")

    result = bootstrap.start_or_attach_gateway()

    declaration = captured["declaration"]
    assert isinstance(result, FakeClient)
    assert declaration.protocol_version == PROTOCOL_VERSION
    assert declaration.endpoint.address == "127.0.0.1:9123"
    assert declaration.process.detached is True
    assert declaration.process.command[0]
    assert declaration.process.cwd == captured["store"].root
    assert declaration.process.cwd.is_dir()
    assert declaration.process.env == {
        "AUDIAGENTIC_REPO_ROOT": "",
        "AUDIAGENTIC_COMPONENT_PROFILE": "",
    }
    assert captured["adopted"] == (
        "lease-a", "epoch-a", "shared-service-host"
    )
    assert captured["kwargs"]["lease_ttl_seconds"] == 120.0


@pytest.mark.parametrize("value", ["zero", "0", "65536"])
def test_automatic_gateway_rejects_invalid_port(monkeypatch, value):
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_PORT", value)

    with pytest.raises(AudiaGenticError, match="CFG-AGSV-003"):
        bootstrap.start_or_attach_gateway()
