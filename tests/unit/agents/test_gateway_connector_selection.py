"""Owner-backed SH37 connector selection and client wiring."""
from unittest.mock import Mock

import pytest

from audiagentic.components.agents.gateway import client, management_api
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features import registry, state
from audiagentic.foundation.io import save_yaml_file


def _settings_file(root):
    from audiagentic.foundation.config.settings import user_project_settings_path

    return user_project_settings_path(root)


@pytest.fixture(autouse=True)
def clean_client(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    client.reset_gateway_client()
    registry.clear()
    for key in ("MODE", "ENDPOINT", "TOKEN_FILE"):
        monkeypatch.delenv("AUDIAGENTIC_GATEWAY_" + key, raising=False)
    yield
    client.reset_gateway_client()


@pytest.fixture
def connector(tmp_path):
    token = tmp_path / "token"
    token.write_text("secret-token")
    token.chmod(0o600)
    path = tmp_path / "connector.yaml"
    save_yaml_file(path, {
        "schema-version": 1, "endpoint": "https://gateway.example",
        "server-id": "shared", "project-id": "project", "token-file": "token",
    })
    return path


def test_connect_atomic_selection_preserves_other_configuration(tmp_path, connector, monkeypatch):
    original = {
        "options": {"unrelated": True}, "features": {"language:x": {"enabled": True}},
        "implementations": {
            "automatic": {"enabled": True, "options": {"startup-timeout-seconds": 42}},
            "standalone": {"enabled": False, "options": {"endpoint": "http://127.0.0.1:1", "token-file": "old"},
                           "features": {"mcp:retained": {"enabled": True}}},
        },
    }
    state.set_component_state(tmp_path, "agents", original)
    state.set_component_state(tmp_path, "planning", {"options": {"untouched": True}})
    planning = state.get_component_state(tmp_path, "planning")
    real_write = state.set_component_state
    writes = Mock(wraps=real_write)
    monkeypatch.setattr(state, "set_component_state", writes)
    management_api.gateway_connect_config(tmp_path, connector)
    assert writes.call_count == 1
    result = state.get_component_state(tmp_path, "agents")
    assert result["options"] == original["options"]
    assert result["features"] == original["features"]
    assert result["implementations"]["automatic"] == {
        "enabled": False, "options": {"startup-timeout-seconds": 42},
    }
    assert result["implementations"]["standalone"] == {
        "enabled": True, "options": {"connector-config": str(connector.resolve())},
        "features": {"mcp:retained": {"enabled": True}},
    }
    assert registry.resolve_active_implementation(tmp_path, "agents") == "standalone"
    assert state.get_component_state(tmp_path, "planning") == planning
    assert "secret-token" not in _settings_file(tmp_path).read_text()


def test_selected_connector_builds_shared_tls_client(tmp_path, connector, monkeypatch):
    import ssl

    from audiagentic.components.agents.gateway import remote_client

    ca = tmp_path / "ca.pem"
    ca.write_text("test CA path; SSL construction mocked")
    connector.write_text(connector.read_text() + "ca-file: ca.pem\n")
    management_api.gateway_connect_config(tmp_path, connector)
    constructor = Mock()
    context = Mock()
    monkeypatch.setattr(remote_client, "StandaloneGatewayClient", constructor)
    monkeypatch.setattr(ssl, "create_default_context", context)
    monkeypatch.setattr(client, "resolve_request_project_root", Mock(side_effect=AssertionError("sibling resolver")))
    assert client.get_gateway_client(tmp_path) is constructor.return_value
    constructor.assert_called_once_with(
        "https://gateway.example", "secret-token", shared_server_id="shared",
        shared_project_id="project", ssl_context=context.return_value,
    )
    context.assert_called_once_with(cafile=str(ca))
    assert client.get_gateway_client(tmp_path) is constructor.return_value
    assert constructor.call_count == 1


def test_local_standalone_options_remain_supported(tmp_path, connector, monkeypatch):
    from audiagentic.components.agents.gateway import remote_client
    management_api.gateway_set_config(tmp_path, "standalone", {
        "endpoint": "http://127.0.0.1:9000", "token-file": str(connector.parent / "token"),
    })
    management_api.gateway_select_implementation(tmp_path, "standalone")
    constructor = Mock()
    monkeypatch.setattr(remote_client, "StandaloneGatewayClient", constructor)
    client.get_gateway_client(tmp_path)
    constructor.assert_called_once_with("http://127.0.0.1:9000", "secret-token")


@pytest.mark.parametrize("invalid", ["relative", "mixed", "missing", "malformed"])
def test_invalid_connector_never_changes_selection(tmp_path, connector, invalid):
    management_api.gateway_select_implementation(tmp_path, "automatic")
    before = _settings_file(tmp_path).read_bytes()
    options = {"connector-config": str(connector)}
    if invalid == "relative":
        options["connector-config"] = "connector.yaml"
    elif invalid == "mixed":
        options["endpoint"] = "http://127.0.0.1:1"
    elif invalid == "missing":
        connector.unlink()
    else:
        connector.write_text("schema-version: 100")
    with pytest.raises(AudiaGenticError):
        management_api.gateway_set_config(tmp_path, "standalone", options)
    assert _settings_file(tmp_path).read_bytes() == before


def test_missing_selected_connector_never_bootstraps(tmp_path, connector, monkeypatch):
    from audiagentic.components.agents.gateway.service import bootstrap
    management_api.gateway_connect_config(tmp_path, connector)
    connector.unlink()
    start = Mock(side_effect=AssertionError("discovery forbidden"))
    monkeypatch.setattr(bootstrap, "start_or_attach_gateway", start)
    with pytest.raises(AudiaGenticError):
        client.get_gateway_client(tmp_path)
    start.assert_not_called()


@pytest.mark.parametrize("partial_override", [None, "ENDPOINT", "TOKEN_FILE"])
def test_shared_root_resolvers_skip_all_local_discovery(tmp_path, connector, monkeypatch, partial_override):
    from pathlib import Path

    from audiagentic.components.agents.gateway import api, store
    from audiagentic.components.agents.gateway.service import bootstrap, shared_config
    from audiagentic.components.agents.gateway.session import sessions_store

    management_api.gateway_connect_config(tmp_path, connector)
    # Routing must not even load connector contents; getclient validates them.
    connector.unlink()
    if partial_override:
        monkeypatch.setenv("AUDIAGENTIC_GATEWAY_" + partial_override, "explicit-partial")
    forbidden = Mock(side_effect=AssertionError("local discovery or runtime touched"))
    monkeypatch.setattr(Path, "iterdir", forbidden)
    monkeypatch.setattr(store, "read_record", forbidden)
    monkeypatch.setattr(sessions_store, "read_session_record", forbidden)
    monkeypatch.setattr(api, "_resolve_workspace_project_root", forbidden)
    monkeypatch.setattr(client, "get_gateway_client", forbidden)
    monkeypatch.setattr(bootstrap, "start_or_attach_gateway", forbidden)
    monkeypatch.setattr(shared_config, "load_shared_connector_config", forbidden)
    request_id = "req_remote_" + "0" * 12
    assert client.resolve_request_project_root(tmp_path, request_id) is tmp_path
    assert client.resolve_session_project_root(tmp_path, "ses_remote") is tmp_path
    forbidden.assert_not_called()


@pytest.mark.parametrize("mode,local_override", [("embedded", False), ("automatic", False), ("standalone", True)])
def test_nonshared_root_resolvers_keep_local_routing(tmp_path, connector, monkeypatch, mode, local_override):
    from audiagentic.components.agents.gateway import store
    from audiagentic.components.agents.gateway.session import sessions_store

    management_api.gateway_connect_config(tmp_path, connector)
    settings_file = connector.parent / "settings.yaml"  # machine-scope gateway section, outside the project
    settings_file.write_text(f"schema_version: 1\ngateway:\n  implementation: {mode}\n", encoding="utf-8")
    monkeypatch.setenv("AUDIAGENTIC_CONFIG", str(settings_file))
    if local_override:
        monkeypatch.setenv("AUDIAGENTIC_GATEWAY_ENDPOINT", "http://127.0.0.1:9000")
        monkeypatch.setenv("AUDIAGENTIC_GATEWAY_TOKEN_FILE", str(connector.parent / "token"))
    monkeypatch.setenv("AUDIAGENTIC_WORKSPACE_ROOTS", str(tmp_path))
    request = Mock(return_value={})
    session = Mock(return_value={})
    monkeypatch.setattr(store, "read_record", request)
    monkeypatch.setattr(sessions_store, "read_session_record", session)
    assert not client._uses_shared_connector(tmp_path)
    request_id = "req_local_" + "0" * 12
    assert client.resolve_request_project_root(tmp_path, request_id) == tmp_path
    assert client.resolve_session_project_root(tmp_path, "ses_local") == tmp_path
    request.assert_called_once_with(tmp_path, request_id)
    session.assert_called_once_with(tmp_path.resolve(), "ses_local")
