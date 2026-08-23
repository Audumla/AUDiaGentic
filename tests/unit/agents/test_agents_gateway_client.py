"""SH03 conformance tests for the public in-process gateway client."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway import client as client_module
from audiagentic.components.agents.gateway.client import (
    EmbeddedGatewayClient,
    _resolve_implementation_id,
    get_gateway_client,
    reset_gateway_client,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


class _ApplicationStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def submit_execution_request(self, project_root: Path, **kwargs: object) -> dict[str, object]:
        self.calls.append(("submit", (project_root,), kwargs))
        return {"state": "queued"}

    def get_execution_response(self, project_root: Path, request_id: str) -> str:
        self.calls.append(("response", (project_root, request_id), {}))
        return "complete response"


def test_in_process_client_delegates_to_its_application(tmp_path: Path) -> None:
    application = _ApplicationStub()
    client = EmbeddedGatewayClient(application)  # type: ignore[arg-type]

    assert client.submit_execution_request(tmp_path, prompt_body="hello") == {"state": "queued"}
    assert application.calls == [("submit", (tmp_path,), {"prompt_body": "hello"})]


def test_in_process_client_exposes_full_execution_response(tmp_path: Path) -> None:
    application = _ApplicationStub()
    client = EmbeddedGatewayClient(application)  # type: ignore[arg-type]

    assert client.get_execution_response(tmp_path, "req-1") == "complete response"
    assert application.calls == [("response", (tmp_path, "req-1"), {})]


def test_inbound_adapters_depend_on_public_client_not_core_api() -> None:
    agents_dir = Path(__file__).parents[3] / "src" / "audiagentic" / "components" / "agents"
    for rel in ("mcp/gateway_mcp.py", "gateway/events.py"):
        source = (agents_dir / rel).read_text(encoding="utf-8")
        assert "gateway.api import" not in source
        # GP06: gateway_mcp.py calls through call_gateway_method (which
        # self-heals a dead cached client on NET-AGSV-002) rather than
        # get_gateway_client(...).method(...) directly; either public
        # client.py entry point satisfies the "public client, not core api"
        # boundary this test enforces.
        assert (
            "gateway.client import get_gateway_client" in source
            or "gateway.client import call_gateway_method" in source
        ), rel


def test_inbound_adapters_resolve_gateway_with_project_context() -> None:
    """SH11: a project-selected shared implementation must not be bypassed."""
    agents_dir = Path(__file__).parents[3] / "src" / "audiagentic" / "components" / "agents"
    for rel in ("mcp/gateway_mcp.py", "gateway/events.py"):
        source = (agents_dir / rel).read_text(encoding="utf-8")
        assert "get_gateway_client()." not in source, rel


# ── SH11 Slice B: implementation resolution precedence ───────────────────


@pytest.fixture(autouse=True)
def _force_feature_registry_repopulation():
    """Pre-existing test-infrastructure issue (AS76/TE02 step 10; see
    test_agents_gateway_management_api.py's identical fixture for the full
    explanation). Needed here too since this file resolves implementations
    via the same foundation.features.* registry."""
    from audiagentic.foundation.features.registry import clear

    clear()
    yield


@pytest.fixture(autouse=True)
def _clean_gateway_mode_env():
    saved = os.environ.pop("AUDIAGENTIC_GATEWAY_MODE", None)
    yield
    if saved is not None:
        os.environ["AUDIAGENTIC_GATEWAY_MODE"] = saved
    else:
        os.environ.pop("AUDIAGENTIC_GATEWAY_MODE", None)
    reset_gateway_client()


def test_resolve_no_project_root_no_env_defaults_to_embedded() -> None:
    """Backward compatibility: calling with no project context resolves
    exactly as before SH11 -- the hardcoded embedded fallback."""
    implementation_id, source = _resolve_implementation_id(None)
    assert implementation_id == "embedded"
    assert source == "schema-default"


def test_resolve_env_override_wins_over_everything(tmp_path: Path) -> None:
    os.environ["AUDIAGENTIC_GATEWAY_MODE"] = "standalone"
    implementation_id, source = _resolve_implementation_id(tmp_path)
    assert implementation_id == "standalone"
    assert source == "env-override"


def test_resolve_env_override_aliases_in_process_to_embedded() -> None:
    os.environ["AUDIAGENTIC_GATEWAY_MODE"] = "in-process"
    implementation_id, source = _resolve_implementation_id(None)
    assert implementation_id == "embedded"
    assert source == "env-override"


def test_resolve_project_selected_implementation_without_env(tmp_path: Path) -> None:
    """A project that explicitly selected 'automatic' via component config
    resolves to it when no env override is set -- the real SH11 ask:
    declarative selection instead of only env-var branching."""
    from audiagentic.foundation.features.lifecycle import enable_implementation

    enable_implementation(tmp_path, "agents", "automatic")
    implementation_id, source = _resolve_implementation_id(tmp_path)
    assert implementation_id == "automatic"
    assert source == "component-config"


def test_resolve_project_with_no_explicit_selection_falls_through_to_default(
    tmp_path: Path,
) -> None:
    implementation_id, source = _resolve_implementation_id(tmp_path)
    assert implementation_id == "embedded"
    assert source == "component-config"


# ── SH11 Slice D: embedded coexistence guard ──────────────────────────────


def test_no_live_owner_constructs_embedded_normally(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(client_module, "_has_live_provable_shared_owner", lambda: False)
    client = get_gateway_client(tmp_path)
    assert isinstance(client, EmbeddedGatewayClient)


def test_live_owner_refuses_by_default(tmp_path: Path, monkeypatch) -> None:
    """RV736 A6: refuse is the descriptor default, not warn -- silent
    coexistence beside a shared owner is the exact dual-ownership bug this
    boundary exists to prevent."""
    monkeypatch.setattr(client_module, "_has_live_provable_shared_owner", lambda: True)
    with pytest.raises(AudiaGenticError) as exc_info:
        get_gateway_client(tmp_path)
    assert exc_info.value.code == "CFG-AGSV-005"


def test_live_owner_with_warn_policy_constructs_embedded_anyway(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(client_module, "_has_live_provable_shared_owner", lambda: True)
    monkeypatch.setattr(
        client_module, "_resolve_embedded_coexistence_policy", lambda project_root: "warn"
    )
    client = get_gateway_client(tmp_path)
    assert isinstance(client, EmbeddedGatewayClient)


def test_live_owner_with_env_override_takes_precedence_over_project_config(
    tmp_path: Path,
) -> None:
    from audiagentic.components.agents.gateway.management_api import gateway_set_config

    gateway_set_config(tmp_path, "embedded", {"allow-with-live-shared-owner": "warn"})
    os.environ["AUDIAGENTIC_GATEWAY_EMBEDDED_ALLOW"] = "refuse"
    try:
        policy = client_module._resolve_embedded_coexistence_policy(tmp_path)
        assert policy == "refuse"
    finally:
        del os.environ["AUDIAGENTIC_GATEWAY_EMBEDDED_ALLOW"]


def test_live_owner_with_unknown_policy_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(client_module, "_has_live_provable_shared_owner", lambda: True)
    monkeypatch.setattr(
        client_module, "_resolve_embedded_coexistence_policy", lambda project_root: "bogus"
    )
    with pytest.raises(AudiaGenticError) as exc_info:
        get_gateway_client(tmp_path)
    assert exc_info.value.code == "CFG-AGSV-006"


# ── GP06: call_gateway_method self-healing on NET-AGSV-002 ────────────────


class _FakeClient:
    def __init__(self, *, fail_first: bool, error_code: str = "NET-AGSV-002") -> None:
        self.calls: list[str] = []
        self._fail_first = fail_first
        self._error_code = error_code

    def gateway_overview(self, _project_root: Path) -> dict[str, object]:
        self.calls.append("gateway_overview")
        if self._fail_first and len(self.calls) == 1:
            raise AudiaGenticError(self._error_code, "agents", "gateway service is unavailable", {})
        return {"total_requests": 1}

    def submit_execution_request(self, _project_root: Path, **_kwargs: object) -> dict[str, object]:
        self.calls.append("submit_execution_request")
        if self._fail_first and len(self.calls) == 1:
            raise AudiaGenticError(self._error_code, "agents", "gateway service is unavailable", {})
        return {"state": "queued"}


def test_call_gateway_method_reconnects_and_retries_read_only_after_net_agsv_002(
    tmp_path: Path, monkeypatch
) -> None:
    dead = _FakeClient(fail_first=True)
    live = _FakeClient(fail_first=False)
    sequence = iter([dead, live])
    reset_calls: list[None] = []

    monkeypatch.setattr(client_module, "get_gateway_client", lambda _root: next(sequence))
    monkeypatch.setattr(client_module, "reset_gateway_client", lambda: reset_calls.append(None))

    result = client_module.call_gateway_method("gateway_overview", tmp_path)

    assert result == {"total_requests": 1}
    assert reset_calls == [None]
    assert dead.calls == ["gateway_overview"]
    assert live.calls == ["gateway_overview"]


def test_call_gateway_method_does_not_replay_mutating_call_after_net_agsv_002(
    tmp_path: Path, monkeypatch
) -> None:
    """Reconnecting is always safe; blindly replaying a mutation is not --
    a network failure doesn't prove the original RPC never reached the
    server. The caller must decide whether to retry a mutation, now against
    a live client."""
    dead = _FakeClient(fail_first=True)
    live = _FakeClient(fail_first=False)
    sequence = iter([dead, live])
    reset_calls: list[None] = []

    monkeypatch.setattr(client_module, "get_gateway_client", lambda _root: next(sequence))
    monkeypatch.setattr(client_module, "reset_gateway_client", lambda: reset_calls.append(None))

    with pytest.raises(AudiaGenticError) as exc_info:
        client_module.call_gateway_method("submit_execution_request", tmp_path, prompt_body="hi")

    assert exc_info.value.code == "NET-AGSV-002"
    # The client WAS reconnected (so the caller's next attempt uses a live
    # one) even though this specific call was not replayed.
    assert reset_calls == [None]
    assert dead.calls == ["submit_execution_request"]
    assert live.calls == []


def test_call_gateway_method_propagates_non_network_errors_without_reconnecting(
    tmp_path: Path, monkeypatch
) -> None:
    broken = _FakeClient(fail_first=True, error_code="VAL-AGSV-001")
    reset_calls: list[None] = []

    monkeypatch.setattr(client_module, "get_gateway_client", lambda _root: broken)
    monkeypatch.setattr(client_module, "reset_gateway_client", lambda: reset_calls.append(None))

    with pytest.raises(AudiaGenticError) as exc_info:
        client_module.call_gateway_method("gateway_overview", tmp_path)

    assert exc_info.value.code == "VAL-AGSV-001"
    assert reset_calls == []


def test_default_policy_with_no_project_root_is_refuse() -> None:
    assert client_module._resolve_embedded_coexistence_policy(None) == "refuse"


def test_has_live_provable_shared_owner_false_when_no_record_exists(tmp_path, monkeypatch) -> None:
    """No fabricated ownership claim when the service record simply doesn't
    exist yet -- the common case: no shared gateway has ever run on this
    machine. Exercises the real ManagedServiceStore against an isolated
    runtime root, not a fake."""
    import audiagentic.foundation.system.managed_service as managed_service_module

    monkeypatch.setattr(
        managed_service_module, "global_service_runtime", lambda: tmp_path / "isolated-runtime"
    )
    assert client_module._has_live_provable_shared_owner() is False
