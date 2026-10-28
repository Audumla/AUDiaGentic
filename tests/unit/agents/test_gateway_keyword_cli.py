"""SH37 keyword routes and startup-free help contracts."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from audiagentic.commands import gateway


@pytest.mark.parametrize("tail", [[], ["help"], ["serve", "help"], ["status", "help"], ["connect", "help"]])
def test_help_subprocess_has_no_runtime_imports(tail):
    script = '''
import importlib.abc
import sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("audiagentic.runtime", "audiagentic.components", "audiagentic.commands.bootstrap", "playwright", "selenium")):
            raise AssertionError("startup import: " + fullname)
sys.meta_path.insert(0, Guard())
from audiagentic.launcher import main
raise SystemExit(main(["gateway", *sys.argv[1:]]))
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3] / "src")
    result = subprocess.run([sys.executable, "-c", script, *tail], capture_output=True, text=True, env=env, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "config FILE" in result.stdout
    assert not result.stderr


@pytest.mark.parametrize("tail", [
    ["serve", "--host", "127.0.0.1"], ["status"], ["stop", "--force"],
    ["drain"], ["resume"], ["recover"], ["serve", "config", "a", "extra"],
    ["status", "config", "a", "output", "text"],
    ["connect", "config", "a", "project", ".", "dry-run", "non-interactive"],
])
def test_reject_retired_and_invalid_grammar(tail, capsys):
    assert gateway.dispatch_keyword(tail) == 2
    assert "gateway help" in capsys.readouterr().err


@pytest.fixture
def owners(monkeypatch):
    config = SimpleNamespace(endpoint="https://example.test", server_id="server", project_id="project", token_file=Path("token"), ca_file=None)
    loader = Mock(return_value=config)
    module = SimpleNamespace(load_shared_connector_config=loader, load_shared_server_config=loader)
    monkeypatch.setitem(sys.modules, "audiagentic.components.agents.gateway.service.shared_config", module)
    client = Mock()
    client.health.return_value = {"healthy": True}
    factory = Mock(return_value=client)
    monkeypatch.setattr(gateway, "_shared_client", factory)
    return config, loader, client, factory


def test_status_only_health(owners, capsys):
    _, _, client, _ = owners
    assert gateway.dispatch_keyword(["status", "config", "connector.yaml", "output", "json"]) == 0
    assert '"healthy": true' in capsys.readouterr().out
    assert client.method_calls == [("health", (), {}), ("close", (), {})]


def test_connect_dry_run(owners, tmp_path, capsys):
    _, _, client, _ = owners
    assert gateway.dispatch_keyword(["connect", "config", "connector.yaml", "project", str(tmp_path), "dry-run"]) == 0
    assert "No binding written" in capsys.readouterr().out
    assert client.method_calls == [("health", (), {}), ("close", (), {})]


def test_health_failure_closes_client(owners):
    _, _, client, _ = owners
    client.health.side_effect = RuntimeError("failure")
    with pytest.raises(RuntimeError, match="failure"):
        gateway.dispatch_keyword(["status", "config", "connector.yaml"])
    client.close.assert_called_once()


def test_serve_delegates_shared_config(owners, monkeypatch):
    config, _, _, _ = owners
    serve = Mock(return_value=0)
    monkeypatch.setattr(gateway, "cmd_gateway", serve)
    assert gateway.dispatch_keyword(["serve", "config", "server.yaml"]) == 0
    assert serve.call_args.args[0].shared_config is config


def test_registered_error_uses_print_error(owners, capsys):
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.launcher import main
    owners[2].health.side_effect = AudiaGenticError("VAL-AGSV-006", "validation", "invalid config")
    assert main(["gateway", "status", "config", "connector.yaml"]) == 1
    assert "invalid config" in capsys.readouterr().err


def test_shared_client_uses_token_loader_identity_and_ca(monkeypatch):
    token = Mock(return_value="private-token")
    constructor = Mock()
    monkeypatch.setitem(sys.modules, "audiagentic.components.agents.gateway.remote_client", SimpleNamespace(StandaloneGatewayClient=constructor, load_auth_token=token))
    import ssl
    context = Mock()
    monkeypatch.setattr(ssl, "create_default_context", context)
    cfg = SimpleNamespace(endpoint="https://example.test", server_id="server", project_id="project", token_file=Path("token"), ca_file=Path("ca.pem"))
    gateway._shared_client(cfg)
    token.assert_called_once_with(cfg.token_file)
    context.assert_called_once_with(cafile="ca.pem")
    constructor.assert_called_once_with(cfg.endpoint, "private-token", shared_server_id="server", shared_project_id="project", ssl_context=context.return_value)


def test_connect_persists_after_handshake(owners, tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import management_api
    events = []
    owners[2].health.side_effect = lambda: events.append("health") or {"healthy": True}
    writer = Mock(side_effect=lambda *args: events.append("write"))
    monkeypatch.setattr(management_api, "gateway_connect_config", writer)
    assert gateway.dispatch_keyword(["connect", "config", "connector.yaml", "project", str(tmp_path), "non-interactive"]) == 0
    assert events == ["health", "write"]
    writer.assert_called_once_with(tmp_path.resolve(), Path("connector.yaml").resolve())


@pytest.mark.parametrize("answer,expected", [("yes", 0), ("no", 1)])
def test_connect_confirmation(owners, tmp_path, monkeypatch, answer, expected):
    from audiagentic.components.agents.gateway import management_api
    writer = Mock()
    monkeypatch.setattr(management_api, "gateway_connect_config", writer)
    monkeypatch.setattr("builtins.input", lambda *_: answer)
    assert gateway.dispatch_keyword(["connect", "config", "connector.yaml", "project", str(tmp_path)]) == expected
    assert writer.call_count == (expected == 0)


def test_connect_handshake_failure_never_writes(owners, tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import management_api
    writer = Mock()
    monkeypatch.setattr(management_api, "gateway_connect_config", writer)
    owners[2].health.side_effect = RuntimeError("identity mismatch")
    with pytest.raises(RuntimeError):
        gateway.dispatch_keyword(["connect", "config", "connector.yaml", "project", str(tmp_path), "non-interactive"])
    writer.assert_not_called()
    owners[2].close.assert_called_once()
