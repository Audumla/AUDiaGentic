"""``gateway init``: generated setup, idempotence, refusals, binding and secrecy (CFG15-A)."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
import yaml

from audiagentic.commands import gateway as cli
from audiagentic.components.agents.gateway import management_api
from audiagentic.components.agents.gateway.service import shared_config
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "My_Project"
    (root / ".git").mkdir(parents=True)
    return root


@pytest.fixture
def target(tmp_path):
    return tmp_path / "gateway"


def _user_gateway_settings(tmp_path) -> dict:
    path = tmp_path / "xdg-config" / "audiagentic" / "settings.yaml"
    return (yaml.safe_load(path.read_text()) or {}).get("gateway", {}) if path.is_file() else {}


def test_fresh_init_creates_a_valid_private_setup(project, target, tmp_path):
    result = management_api.gateway_init(directory=target, project=project)
    assert result["state"] == "created" and result["project-id-written"] and result["binding"] == "bound"
    token = target / "credentials" / "operator.token"
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert stat.S_IMODE((target / "credentials").stat().st_mode) == 0o700
    server = shared_config.load_shared_server_config(target / "server.yaml")
    connector = shared_config.load_shared_connector_config(target / "connector.yaml")
    assert server.projects == {"my_project": project.resolve()}
    assert connector.server_id == server.server_id and server.server_id.startswith("gw-") and len(server.server_id) == 19
    assert connector.endpoint == "http://127.0.0.1:8765" and connector.mode == "shared"
    document = yaml.safe_load((target / "server.yaml").read_text())
    assert document["projects"] == [str(project.resolve())]
    assert "projects" not in document["principals"]["operator"]  # omitted: all served projects and actions
    assert "my_project" in (project / ".audiagentic" / "settings.yaml").read_text()
    assert _user_gateway_settings(tmp_path) == {"connector": str(target / "connector.yaml")}
    assert token.read_text().strip() not in repr(result)


def test_dry_run_writes_nothing_and_generates_no_credential(project, target, tmp_path):
    result = management_api.gateway_init(directory=target, project=project, dry_run=True)
    assert result["state"] == "dry-run" and result["project-id-would-write"] is True
    assert not target.exists() and not (project / ".audiagentic").exists()
    assert _user_gateway_settings(tmp_path) == {}


def test_repeat_init_is_a_no_op_that_keeps_identity_and_token(project, target):
    first = management_api.gateway_init(directory=target, project=project)
    token = (target / "credentials" / "operator.token").read_bytes()
    second = management_api.gateway_init(directory=target, project=project)
    assert second["state"] == "already-initialized" and second["server-id"] == first["server-id"]
    assert second["binding"] == "same" and not second["project-id-written"]
    assert (target / "credentials" / "operator.token").read_bytes() == token


@pytest.mark.parametrize("missing", ["server.yaml", "connector.yaml", "credentials/operator.token"])
def test_partial_setup_is_refused_and_nothing_is_changed(project, target, missing):
    management_api.gateway_init(directory=target, project=project)
    (target / missing).unlink()
    before = {p.name: p.read_bytes() for p in target.rglob("*") if p.is_file()}
    with pytest.raises(AudiaGenticError, match="partial"):
        management_api.gateway_init(directory=target, project=project)
    assert {p.name: p.read_bytes() for p in target.rglob("*") if p.is_file()} == before


def test_inconsistent_existing_files_are_refused(project, target):
    management_api.gateway_init(directory=target, project=project)
    connector = yaml.safe_load((target / "connector.yaml").read_text())
    connector["server-id"] = "other"
    (target / "connector.yaml").write_text(yaml.safe_dump(connector))
    with pytest.raises(AudiaGenticError):
        management_api.gateway_init(directory=target, project=project)


def test_existing_declared_id_is_preserved_and_must_be_valid(project, target):
    (project / ".audiagentic").mkdir()
    (project / ".audiagentic" / "settings.yaml").write_text("schema_version: 1\nproject:\n  id: team-app\n")
    result = management_api.gateway_init(directory=target, project=project)
    assert result["project-id"] == "team-app" and not result["project-id-written"]
    other = project.parent / "Bad"
    (other / ".git").mkdir(parents=True)
    (other / ".audiagentic").mkdir()
    (other / ".audiagentic" / "settings.yaml").write_text("schema_version: 1\nproject:\n  id: Team.App\n")
    with pytest.raises(AudiaGenticError, match="valid gateway id"):
        management_api.gateway_init(directory=project.parent / "g2", project=other)


def test_a_directory_that_is_not_a_project_is_refused(tmp_path, target):
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(AudiaGenticError, match="needs a project"):
        management_api.gateway_init(directory=target, project=bare)
    assert not target.exists()


def test_existing_other_binding_is_kept_and_a_conflicting_implementation_is_reported(project, target, tmp_path):
    settings = tmp_path / "xdg-config" / "audiagentic" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    settings.write_text("schema_version: 1\ngateway:\n  connector: /elsewhere/connector.yaml\n  implementation: standalone\n")
    result = management_api.gateway_init(directory=target, project=project)
    assert result["binding"] == "kept" and "gateway connect config" in result["binding-note"]
    assert _user_gateway_settings(tmp_path)["connector"] == "/elsewhere/connector.yaml"
    settings.write_text("schema_version: 1\ngateway:\n  implementation: embedded\n")
    result = management_api.gateway_init(directory=tmp_path / "g3", project=project)
    assert result["binding"] == "conflict" and _user_gateway_settings(tmp_path) == {"implementation": "embedded"}


def test_failed_validation_removes_only_what_this_run_created(project, target, monkeypatch):
    def broken(*_a, **_k):
        raise AudiaGenticError("VAL-AGSV-006", "validation", "forced")

    monkeypatch.setattr(shared_config, "load_shared_connector_config", broken)
    with pytest.raises(AudiaGenticError, match="forced"):
        management_api.gateway_init(directory=target, project=project)
    assert not any(p.is_file() for p in target.rglob("*"))


@pytest.mark.parametrize("tokens,ok", [
    ([], True), (["dry-run"], True), (["dir", "x", "project", "y", "dry-run"], True),
    (["dir"], False), (["dir", "a", "dir", "b"], False), (["--dir", "a"], False), (["dry-run", "dry-run"], False),
    (["other"], False),
])
def test_cli_grammar(tokens, ok, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(management_api, "gateway_init", lambda **kw: calls.append(kw) or {
        "state": "created", "directory": "d", "files": [], "project-id": "p", "project-root": "r",
        "project-id-written": False, "binding": "bound", "binding-note": "n"})
    code = cli.dispatch_keyword(["init", *tokens])
    assert (code == 0) == ok and bool(calls) == ok
    if not ok:
        assert code == 2 and "init syntax" in capsys.readouterr().err


def test_cli_prints_the_next_command_and_never_a_token(project, target, capsys):
    assert cli.dispatch_keyword(["init", "dir", str(target), "project", str(project)]) == 0
    out = capsys.readouterr().out
    assert "gateway serve config" in out and "binding: bound" in out
    assert (target / "credentials" / "operator.token").read_text().strip() not in out


def test_cli_reports_registered_errors(tmp_path, capsys):
    bare = tmp_path / "bare"
    bare.mkdir()
    assert cli.dispatch_keyword(["init", "dir", str(tmp_path / "g"), "project", str(bare)]) == 1
    assert "needs a project" in capsys.readouterr().err


def test_init_help_is_pure(capsys):
    assert cli.dispatch_keyword(["init", "help"]) == 0
    assert "gateway init [dir PATH]" in capsys.readouterr().out


def test_serve_without_arguments_uses_the_default_setup(project, monkeypatch, capsys):
    from unittest.mock import Mock

    assert cli.dispatch_keyword(["serve"]) == 1
    assert "gateway init" in capsys.readouterr().err
    management_api.gateway_init(project=project)
    serve = Mock(return_value=0)
    monkeypatch.setattr(cli, "cmd_gateway", serve)
    monkeypatch.chdir(project)
    assert cli.dispatch_keyword(["serve"]) == 0
    assert "serving" in capsys.readouterr().out
    assert serve.call_args.args[0].shared_config.projects == {"my_project": project.resolve()}


def test_init_next_command_is_plain_serve_for_the_default_directory(project, capsys):
    assert cli.dispatch_keyword(["init", "project", str(project)]) == 0
    assert "next: audiagentic gateway serve\n" in capsys.readouterr().out


def test_validate_catches_a_port_mismatch_of_the_generated_pair_without_rewriting(project):
    management_api.gateway_init(project=project)
    from audiagentic.components.agents.gateway.service.init_setup import default_directory

    directory = default_directory()
    connector = yaml.safe_load((directory / "connector.yaml").read_text())
    connector["endpoint"] = "http://127.0.0.1:9999"
    (directory / "connector.yaml").write_text(yaml.safe_dump(connector))
    before = (directory / "server.yaml").read_bytes(), (directory / "connector.yaml").read_bytes()
    for role in ("server", "connector"):
        with pytest.raises(AudiaGenticError, match="CFG-AGSV-009"):
            management_api.gateway_validate_deployment(role, directory / f"{role}.yaml", project)
    assert ((directory / "server.yaml").read_bytes(), (directory / "connector.yaml").read_bytes()) == before


def test_a_remote_connector_is_not_compared_with_an_unrelated_local_server(project, tmp_path):
    management_api.gateway_init(project=project)
    remote = tmp_path / "remote.yaml"
    token = tmp_path / "t"
    token.write_text("x")
    token.chmod(0o600)
    remote.write_text(yaml.safe_dump({"schema-version": 1, "mode": "shared", "endpoint": "http://127.0.0.1:9999",
                                      "server-id": "someone-else", "token-file": str(token)}))
    assert management_api.gateway_validate_deployment("connector", remote, project)["mode"] == "shared"


def test_status_reports_the_bound_connector_and_distinguishes_failures(project, monkeypatch):
    with pytest.raises(AudiaGenticError, match="CFG-AGSV-001"):
        management_api.gateway_connection_status(project)  # configuration: nothing bound
    management_api.gateway_init(project=project)
    monkeypatch.setattr(management_api, "gateway_connector_health", lambda path, root: {"state": "running"})
    report = management_api.gateway_connection_status(project)
    assert report["mode"] == "shared" and report["health"] == {"state": "running"}
    assert report["server-id"].startswith("gw-") and "operator.token" not in repr(report)
