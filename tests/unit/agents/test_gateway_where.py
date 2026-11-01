"""``gateway where`` and deployment-aware ``gateway validate`` (CFG15-B): offline, never a token."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from audiagentic.components.agents.gateway import management_api
from audiagentic.foundation.contracts.errors import AudiaGenticError
from tests.helpers.shared_gateway import declare_project


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "app"
    (root / ".git").mkdir(parents=True)
    return root


def test_where_with_nothing_set_up_reports_status_and_does_not_fail(project, tmp_path):
    report = management_api.gateway_where(project=project)
    assert report["directory"].startswith(str(tmp_path / "xdg-config"))
    assert report["files"] == {"server.yaml": "missing", "connector.yaml": "missing",
                               "credentials/operator.token": "missing"}
    assert report["connection"]["connector"] is None
    assert report["project"]["id"] is None and "gateway init" in report["project"]["note"]


def test_where_after_init_shows_binding_roots_and_never_the_token(project):
    init = management_api.gateway_init(project=project)
    report = management_api.gateway_where(project=project)
    assert report["files"]["server.yaml"] == "valid" and report["files"]["connector.yaml"] == "valid"
    assert report["served-projects"] == {"app": str(project.resolve())}
    assert report["connection"]["is-generated-default"] is True
    assert report["connection"]["mode"] == "shared" and report["connection"]["endpoint"] == "http://127.0.0.1:8765"
    assert report["connection"]["server-id"] == init["server-id"] == report["server-id"]
    assert report["connection"]["source"].startswith("user")
    assert report["implementation"]["value"] == "standalone"
    assert report["project"]["id"] == "app" and report["project"]["source"].startswith("project")
    token = (Path(report["directory"]) / "credentials" / "operator.token").read_text().strip()
    assert token not in repr(report)


def test_where_reports_an_invalid_document_instead_of_raising(project):
    management_api.gateway_init(project=project)
    directory = Path(management_api.gateway_where(project=project)["directory"])
    (directory / "connector.yaml").write_text("schema-version: 1\nmode: other\n")
    report = management_api.gateway_where(project=project)
    assert report["files"]["connector.yaml"].startswith("invalid")
    assert report["connection"]["status"].startswith("invalid")


def test_validate_server_resolves_roots_ids_and_grants(project, tmp_path):
    management_api.gateway_init(project=project)
    directory = Path(management_api.gateway_where(project=project)["directory"])
    result = management_api.gateway_validate_deployment("server", directory / "server.yaml")
    assert result["projects"] == {"app": str(project.resolve())} and result["principals"] == ["operator"]
    document = yaml.safe_load((directory / "server.yaml").read_text())
    document["principals"]["operator"]["projects"] = ["unknown"]
    (directory / "server.yaml").write_text(yaml.safe_dump(document))
    with pytest.raises(AudiaGenticError):
        management_api.gateway_validate_deployment("server", directory / "server.yaml")


def test_validate_server_with_omitted_roots_uses_the_given_project(project, tmp_path):
    management_api.gateway_init(project=project)
    directory = Path(management_api.gateway_where(project=project)["directory"])
    document = yaml.safe_load((directory / "server.yaml").read_text())
    del document["projects"]
    (directory / "server.yaml").write_text(yaml.safe_dump(document))
    result = management_api.gateway_validate_deployment("server", directory / "server.yaml", project)
    assert list(result["projects"]) == ["app"]
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(AudiaGenticError):
        management_api.gateway_validate_deployment("server", directory / "server.yaml", bare)


def test_validate_shared_connector_needs_a_declared_project_id(project, tmp_path):
    management_api.gateway_init(project=project)
    directory = Path(management_api.gateway_where(project=project)["directory"])
    ok = management_api.gateway_validate_deployment("connector", directory / "connector.yaml", project)
    assert ok["mode"] == "shared" and ok["project-id"] == "app"
    undeclared = tmp_path / "other"
    (undeclared / ".git").mkdir(parents=True)
    with pytest.raises(AudiaGenticError, match="CFG-AGSV-003"):
        management_api.gateway_validate_deployment("connector", directory / "connector.yaml", undeclared)
    declare_project(undeclared, "other")
    assert management_api.gateway_validate_deployment("connector", directory / "connector.yaml", undeclared)
