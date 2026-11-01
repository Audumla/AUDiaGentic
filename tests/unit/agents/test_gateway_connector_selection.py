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


def _write_connector(tmp_path, **fields):
    token = tmp_path / "token"
    token.write_text("secret-token")
    token.chmod(0o600)
    path = tmp_path / "connector.yaml"
    document = {"schema-version": 1, "mode": "shared", "endpoint": "https://gateway.example",
                "server-id": "shared", "token-file": "token"}
    document.update(fields)
    save_yaml_file(path, document)
    return path


@pytest.fixture
def connector(tmp_path):
    return _write_connector(tmp_path)


@pytest.fixture
def project(tmp_path):
    """A project that declares its id, as a shared connection requires."""
    root = tmp_path / "project"
    (root / ".audiagentic").mkdir(parents=True)
    (root / ".audiagentic" / "settings.yaml").write_text("schema_version: 1\nproject:\n  id: project\n")
    (root / ".git").mkdir()
    return root


def _user_settings(tmp_path):
    from audiagentic.foundation.paths.home import user_config_dir

    return user_config_dir() / "settings.yaml"


def test_connect_writes_one_user_setting_patch_and_no_secret(tmp_path, connector):
    result = management_api.gateway_connect_config(connector)
    assert result == {"implementation": "standalone", "connector": str(connector.resolve())}
    import yaml

    text = _user_settings(tmp_path).read_text()
    assert yaml.safe_load(text)["gateway"] == {"connector": str(connector.resolve()), "implementation": "standalone"}
    assert "secret-token" not in text


def test_connect_rejects_an_invalid_connector_without_writing(tmp_path, connector):
    connector.write_text("schema-version: 1\nmode: other\n")
    with pytest.raises(AudiaGenticError):
        management_api.gateway_connect_config(connector)
    assert not _user_settings(tmp_path).exists()


def test_selected_shared_connector_builds_the_shared_client(tmp_path, connector, project, monkeypatch):
    import ssl

    from audiagentic.components.agents.gateway import remote_client

    ca = tmp_path / "ca.pem"
    ca.write_text("test CA path; SSL construction mocked")
    connector.write_text(connector.read_text() + "ca-file: ca.pem\n")
    management_api.gateway_connect_config(connector)
    constructor = Mock()
    context = Mock()
    monkeypatch.setattr(remote_client, "StandaloneGatewayClient", constructor)
    monkeypatch.setattr(ssl, "create_default_context", context)
    assert client.get_gateway_client(project) is constructor.return_value
    constructor.assert_called_once_with(
        "https://gateway.example", "secret-token", shared_server_id="shared",
        shared_project_id="project", ssl_context=context.return_value,
    )
    context.assert_called_once_with(cafile=str(ca))
    assert client.get_gateway_client(project) is constructor.return_value
    assert constructor.call_count == 1


def test_shared_connection_needs_a_declared_project_id(tmp_path, connector):
    management_api.gateway_connect_config(connector)
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(AudiaGenticError, match="CFG-AGSV-003"):
        client.get_gateway_client(bare)


def test_shared_loopback_http_connector_builds_a_tlsless_client(tmp_path, project, monkeypatch):
    from audiagentic.components.agents.gateway import remote_client

    path = _write_connector(tmp_path, endpoint="http://127.0.0.1:8765")
    management_api.gateway_connect_config(path)
    constructor = Mock()
    monkeypatch.setattr(remote_client, "StandaloneGatewayClient", constructor)
    client.get_gateway_client(project)
    constructor.assert_called_once_with(
        "http://127.0.0.1:8765", "secret-token", shared_server_id="shared",
        shared_project_id="project", ssl_context=None,
    )


def test_plain_connector_needs_no_project_and_no_ids(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import remote_client

    token = tmp_path / "token"
    token.write_text("secret-token")
    token.chmod(0o600)
    path = tmp_path / "plain.yaml"
    save_yaml_file(path, {"schema-version": 1, "mode": "plain", "endpoint": "http://127.0.0.1:9000",
                          "token-file": "token"})
    management_api.gateway_connect_config(path)
    constructor = Mock()
    monkeypatch.setattr(remote_client, "StandaloneGatewayClient", constructor)
    client.get_gateway_client(tmp_path)
    constructor.assert_called_once_with("http://127.0.0.1:9000", "secret-token")


def test_standalone_without_a_connector_fails_with_the_fix(tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text("schema_version: 1\ngateway:\n  implementation: standalone\n")
    import os
    os.environ["AUDIAGENTIC_CONFIG"] = str(settings)
    try:
        with pytest.raises(AudiaGenticError, match="CFG-AGSV-001"):
            client.get_gateway_client(tmp_path)
    finally:
        del os.environ["AUDIAGENTIC_CONFIG"]


def test_standalone_options_no_longer_carry_a_connection(tmp_path):
    for key in ("endpoint", "token-file", "connector-config"):
        with pytest.raises(AudiaGenticError):
            management_api.gateway_set_config(tmp_path, "standalone", {key: "x"})


def test_missing_selected_connector_never_bootstraps(tmp_path, connector, project, monkeypatch):
    from audiagentic.components.agents.gateway.service import bootstrap

    management_api.gateway_connect_config(connector)
    connector.unlink()
    start = Mock(side_effect=AssertionError("discovery forbidden"))
    monkeypatch.setattr(bootstrap, "start_or_attach_gateway", start)
    with pytest.raises(AudiaGenticError):
        client.get_gateway_client(project)
    start.assert_not_called()


def test_shared_root_resolvers_skip_all_local_discovery(tmp_path, connector, project, monkeypatch):
    from pathlib import Path

    from audiagentic.components.agents.gateway import api, store
    from audiagentic.components.agents.gateway.service import bootstrap
    from audiagentic.components.agents.gateway.session import sessions_store

    management_api.gateway_connect_config(connector)
    forbidden = Mock(side_effect=AssertionError("local discovery or runtime touched"))
    monkeypatch.setattr(Path, "iterdir", forbidden)
    monkeypatch.setattr(store, "read_record", forbidden)
    monkeypatch.setattr(sessions_store, "read_session_record", forbidden)
    monkeypatch.setattr(api, "_resolve_workspace_project_root", forbidden)
    monkeypatch.setattr(client, "get_gateway_client", forbidden)
    monkeypatch.setattr(bootstrap, "start_or_attach_gateway", forbidden)
    request_id = "req_remote_" + "0" * 12
    assert client.resolve_request_project_root(project, request_id) is project
    assert client.resolve_session_project_root(project, "ses_remote") is project
    forbidden.assert_not_called()


@pytest.mark.parametrize("mode", ["embedded", "automatic"])
def test_nonshared_root_resolvers_keep_local_routing(tmp_path, connector, monkeypatch, mode):
    from audiagentic.components.agents.gateway import store
    from audiagentic.components.agents.gateway.session import sessions_store

    management_api.gateway_connect_config(connector)
    settings_file = connector.parent / "settings.yaml"
    settings_file.write_text(f"schema_version: 1\ngateway:\n  implementation: {mode}\n", encoding="utf-8")
    monkeypatch.setenv("AUDIAGENTIC_CONFIG", str(settings_file))
    monkeypatch.setattr("audiagentic.components.agents.gateway.workspace_roots.configured_workspace_roots", lambda: [tmp_path.resolve()])
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
