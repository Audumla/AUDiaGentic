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
    ["drain", "--force"], ["resume", "now"], ["recover"], ["recover", "reason"], ["stop", "extra"],
    ["serve", "config", "a", "extra"],
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


@pytest.fixture
def restart(monkeypatch):
    """Replace the real restart with a recorder; nothing in these tests can touch a service."""
    from audiagentic.components.agents.gateway import management_api

    calls = []

    def fake(project_root):
        calls.append(project_root)
        return {"restarting": {"owner-epoch": "old-epoch-1234"}, "restarted": True,
                "status": {"owner-epoch": "new-epoch-5678", "state": "running"}}

    monkeypatch.setattr(management_api, "gateway_restart", fake)
    return calls


def test_restart_non_interactive_restarts_once_and_reports_both_epochs(restart, capsys):
    assert gateway.dispatch_keyword(["restart", "non-interactive"]) == 0
    assert restart == [Path.cwd()]
    out = capsys.readouterr().out
    assert "old-epoc -> new-epoc" in out and "running" in out


def test_restart_asks_first_and_a_refusal_restarts_nothing(restart, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert gateway.dispatch_keyword(["restart"]) == 1
    assert restart == [] and "Not restarted" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    assert gateway.dispatch_keyword(["restart"]) == 0 and len(restart) == 1


def test_restart_json_output(restart, capsys):
    assert gateway.dispatch_keyword(["restart", "output", "json", "non-interactive"]) == 0
    assert '"restarted": true' in capsys.readouterr().out


@pytest.mark.parametrize("tail", [["restart", "--force"], ["restart", "now"], ["restart", "output", "text"],
                                  ["restart", "non-interactive", "extra"]])
def test_restart_rejects_other_grammar_without_restarting(tail, restart, capsys):
    assert gateway.dispatch_keyword(tail) == 2 and restart == []
    assert "gateway help" in capsys.readouterr().err


def test_restart_reports_a_registered_error_and_fails(monkeypatch, capsys):
    from audiagentic.components.agents.gateway import management_api
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    def fail(_root):
        raise AudiaGenticError(code="CON-MSVC-029", kind="conflict", message="replacement did not become ready")

    monkeypatch.setattr(management_api, "gateway_restart", fail)
    assert gateway.dispatch_keyword(["restart", "non-interactive"]) == 1
    assert "CON-MSVC-029" in capsys.readouterr().err


@pytest.fixture
def lifecycle(monkeypatch):
    """Record every lifecycle call; nothing in these tests can touch a service."""
    from audiagentic.components.agents.gateway import management_api

    calls = []
    for name in ("drain", "resume", "stop", "recover"):
        monkeypatch.setattr(management_api, f"gateway_{name}",
                            lambda *args, _n=name, **kwargs: calls.append((_n, args, kwargs)) or {"ok": _n})
    return calls


@pytest.mark.parametrize("tail,expected", [
    (["drain", "non-interactive"], ("drain", {})),
    (["resume"], ("resume", {})),
    (["stop", "non-interactive"], ("stop", {"force": False})),
    (["stop", "force", "non-interactive"], ("stop", {"force": True})),
    (["recover", "reason", "owner", "hung", "non-interactive"], ("recover", {"reason": "owner hung"})),
])
def test_lifecycle_commands_call_their_adapter_once(tail, expected, lifecycle, capsys):
    assert gateway.dispatch_keyword(tail) == 0
    assert [(name, kwargs) for name, _args, kwargs in lifecycle] == [expected]
    assert expected[0] in capsys.readouterr().out


@pytest.mark.parametrize("command", ["drain", "stop"])
def test_lifecycle_asks_first_and_a_refusal_does_nothing(command, lifecycle, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert gateway.dispatch_keyword([command]) == 1
    assert lifecycle == []
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    assert gateway.dispatch_keyword([command]) == 0 and len(lifecycle) == 1


def test_lifecycle_json_output(lifecycle, capsys):
    assert gateway.dispatch_keyword(["resume", "output", "json"]) == 0
    assert '"ok": "resume"' in capsys.readouterr().out


def test_lifecycle_adapters_attach_only_and_forward_force(monkeypatch):
    from audiagentic.components.agents.gateway import management_api
    from audiagentic.components.agents.gateway.service import bootstrap

    client = Mock()
    attach = Mock(return_value=client)
    monkeypatch.setattr(bootstrap, "attach_existing_gateway", attach)
    monkeypatch.setattr(bootstrap, "start_or_attach_gateway", Mock(side_effect=AssertionError("must not start")))
    management_api.gateway_drain(Path("p"))
    management_api.gateway_resume(Path("p"))
    management_api.gateway_stop(Path("p"), force=True)
    client.service_drain.assert_called_once_with(Path("p"))
    client.service_resume.assert_called_once_with(Path("p"))
    client.service_stop.assert_called_once_with(Path("p"), force=True)
    assert client.close.call_count == 3


def test_recover_is_confirmed_record_only(monkeypatch):
    from audiagentic.components.agents.gateway import management_api
    from audiagentic.components.agents.gateway.service import lifecycle

    recover = Mock(return_value={"recovered": True})
    monkeypatch.setattr(lifecycle, "recover_unprovable_owner", recover)
    assert management_api.gateway_recover(reason="hung") == {"recovered": True}
    recover.assert_called_once_with(confirm=True, reason="hung")


def test_restart_help_is_startup_free_and_mentions_the_operator_rule(capsys):
    assert gateway.dispatch_keyword(["restart", "help"]) == 0
    out = capsys.readouterr().out
    assert "no process is signalled by pid" in out and "explicit operator request" in out
