"""CFG14-17 end-to-end gate: generated setup -> validate -> serve -> authenticated request.

Hermetic: temporary projects and directories, an isolated settings home, an in-process server on an
ephemeral loopback port and a fake domain application. Nothing touches a live gateway. The measured
counts are asserted: no hand-edited file for the first project, and exactly one edit (one root line)
for the second.
"""
from __future__ import annotations

import itertools
import threading
from pathlib import Path

import pytest
import yaml

from audiagentic.components.agents.gateway import client as gateway_client
from audiagentic.components.agents.gateway import management_api
from audiagentic.components.agents.gateway.service import shared_config
from audiagentic.components.agents.gateway.service.application import GatewayServiceApplication
from audiagentic.components.agents.gateway.service.contract import PROTOCOL_VERSION
from audiagentic.components.agents.gateway.service.http_transport import GatewayHTTPServer
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey


_RUNS = itertools.count()


class Domain:
    def __init__(self):
        self.reads: list[Path] = []

    def get_execution_request(self, root, request_id, **kwargs):
        self.reads.append(Path(root))
        return {"request_id": request_id, "lifecycle": "active", "activity_seq": 0, "root": str(root)}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    gateway_client.reset_gateway_client()
    yield
    gateway_client.reset_gateway_client()


def _project(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    return root


def _serve(directory: Path, domain: Domain, tmp_path: Path):
    """Load the generated server.yaml as `gateway serve` does, on an ephemeral port, in-process."""
    config = shared_config.load_shared_server_config(directory / "server.yaml")
    state = tmp_path / f"service-state-{next(_RUNS)}"
    store = ManagedServiceStore(ServiceKey("gateway", "e2e"), root=state)
    record = store.create(protocol_version=PROTOCOL_VERSION, owner_epoch="epoch-one")
    store.transition("running", expected_revision=record.revision, expected_epoch=record.owner_epoch)
    server = GatewayHTTPServer(("127.0.0.1", 0), GatewayServiceApplication(domain, store), "local-only",
                               shared_config=config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # The generated endpoint uses the fixed default port; the test points it at the ephemeral one.
    connector = directory / "connector.yaml"
    document = yaml.safe_load(connector.read_text())
    document["endpoint"] = f"http://127.0.0.1:{server.server_port}"
    connector.write_text(yaml.safe_dump(document))
    return server, thread


def _stop(server, thread):
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


def test_generated_setup_serves_an_authenticated_request_and_a_second_project(tmp_path):
    first, second = _project(tmp_path, "alpha"), _project(tmp_path, "beta")
    directory = tmp_path / "gateway"

    # One command, no hand-edited file: init, then validate.
    result = management_api.gateway_init(directory=directory, project=first)
    assert result["state"] == "created" and result["binding"] == "bound"
    validated = management_api.gateway_validate_deployment("server", directory / "server.yaml")
    assert validated["projects"] == {"alpha": str(first.resolve())}
    management_api.gateway_validate_deployment("connector", directory / "connector.yaml", first)

    domain = Domain()
    server, thread = _serve(directory, domain, tmp_path)
    try:
        client = gateway_client.get_gateway_client(first)
        assert client.get_execution_request(first, "req-one")["request_id"] == "req-one"
        assert domain.reads == [first.resolve()]
    finally:
        _stop(server, thread)
        gateway_client.reset_gateway_client()

    # Second project: declare its id once and add exactly one root line (the only hand edit).
    from audiagentic.foundation.config.writer import write_settings_patch
    write_settings_patch("project", {"project": {"id": "beta"}}, project_root=second)
    document = yaml.safe_load((directory / "server.yaml").read_text())
    document["projects"].append(str(second))
    (directory / "server.yaml").write_text(yaml.safe_dump(document, sort_keys=False))
    both = management_api.gateway_validate_deployment("server", directory / "server.yaml")
    assert set(both["projects"]) == {"alpha", "beta"}

    domain = Domain()
    server, thread = _serve(directory, domain, tmp_path)
    try:
        client_a = gateway_client.get_gateway_client(first)
        assert client_a.get_execution_request(first, "req-a")["root"] == str(first.resolve())
        gateway_client.reset_gateway_client()
        client_b = gateway_client.get_gateway_client(second)
        # Each project is routed to its own root by its own declared id; the one connector serves both.
        assert client_b.get_execution_request(second, "req-b")["root"] == str(second.resolve())
        assert domain.reads == [first.resolve(), second.resolve()]
    finally:
        _stop(server, thread)
        gateway_client.reset_gateway_client()


def test_a_principal_narrowed_to_one_project_cannot_reach_the_other(tmp_path):
    first, second = _project(tmp_path, "alpha"), _project(tmp_path, "beta")
    directory = tmp_path / "gateway"
    management_api.gateway_init(directory=directory, project=first)
    from audiagentic.foundation.config.writer import write_settings_patch
    write_settings_patch("project", {"project": {"id": "beta"}}, project_root=second)
    document = yaml.safe_load((directory / "server.yaml").read_text())
    document["projects"].append(str(second))
    document["principals"]["operator"]["projects"] = ["alpha"]
    (directory / "server.yaml").write_text(yaml.safe_dump(document, sort_keys=False))
    domain = Domain()
    server, thread = _serve(directory, domain, tmp_path)
    try:
        assert gateway_client.get_gateway_client(first).get_execution_request(first, "req")["root"]
        gateway_client.reset_gateway_client()
        with pytest.raises(AudiaGenticError):
            gateway_client.get_gateway_client(second).get_execution_request(second, "req")
        assert domain.reads == [first.resolve()]
    finally:
        _stop(server, thread)
        gateway_client.reset_gateway_client()


def test_a_restart_with_the_generated_files_keeps_working(tmp_path):
    project = _project(tmp_path, "alpha")
    directory = tmp_path / "gateway"
    management_api.gateway_init(directory=directory, project=project)
    for attempt in range(2):
        domain = Domain()
        server, thread = _serve(directory, domain, tmp_path / f"run{attempt}")
        try:
            client = gateway_client.get_gateway_client(project)
            assert client.get_execution_request(project, "req")["root"] == str(project.resolve())
        finally:
            _stop(server, thread)
            gateway_client.reset_gateway_client()
