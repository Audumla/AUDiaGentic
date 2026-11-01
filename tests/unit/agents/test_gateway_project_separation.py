"""Per-project running separation (CFG17): two projects, one principal authorized for both.

Application-level scoping only. Requests, idempotency indexes, timelines and the work/context records live
under each project's own root, so identical ids and keys in two projects share nothing, and the shared
ingress resolves a call's root solely from the server's own project map (never from caller input).
OS-level isolation of project code is not claimed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents import agents_paths
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.service import shared_config
from audiagentic.components.agents.gateway.service.shared_ingress import SharedGatewayIngress
from audiagentic.foundation.contracts.errors import AudiaGenticError
from tests.helpers.shared_gateway import declare_project


def _record(prompt: str = "work"):
    return store.build_record(execution_profile_id="default", prompt_body=prompt,
                              context_fingerprint="a" * 64, prompt_digest="b" * 64)


@pytest.fixture
def projects(tmp_path):
    return declare_project(tmp_path / "alpha", "alpha"), declare_project(tmp_path / "beta", "beta")


def test_identical_idempotency_keys_in_two_projects_share_nothing(projects):
    alpha, beta = projects
    first, created_a = store.admit_record(alpha, _record(), idempotency_key="shared:same-key")
    second, created_b = store.admit_record(beta, _record(), idempotency_key="shared:same-key")
    assert created_a and created_b and first["request-id"] != second["request-id"]
    # A replay is answered inside its own project only.
    replay, created = store.admit_record(alpha, _record(), idempotency_key="shared:same-key")
    assert not created and replay["request-id"] == first["request-id"]


def test_a_request_is_not_readable_or_listed_through_another_project(projects):
    alpha, beta = projects
    record, _ = store.admit_record(alpha, _record(), idempotency_key="k")
    assert store.read_record(alpha, record["request-id"])["request-id"] == record["request-id"]
    with pytest.raises(Exception):  # noqa: B017 - the store reports an absent record in its own terms
        store.read_record(beta, record["request-id"])
    assert store.list_records(beta) == []
    assert [item["request-id"] for item in store.list_records(alpha)] == [record["request-id"]]


def test_state_paths_of_two_projects_are_disjoint(projects):
    alpha, beta = projects
    for builder in (agents_paths.gateway_root, agents_paths.agent_work_root):
        a, b = builder(alpha), builder(beta)
        assert a != b and alpha in a.parents and beta in b.parents
    assert agents_paths.gateway_request_path(alpha, "req_x") != agents_paths.gateway_request_path(beta, "req_x")
    assert agents_paths.agent_work_path(alpha, "w") != agents_paths.agent_work_path(beta, "w")
    assert agents_paths.agent_context_path(alpha, "c") != agents_paths.agent_context_path(beta, "c")


def test_cancelling_a_request_id_through_another_project_changes_nothing(projects):
    alpha, beta = projects
    record, _ = store.admit_record(alpha, _record(), idempotency_key="k")
    before = store.read_record(alpha, record["request-id"])
    with pytest.raises(Exception):  # noqa: B017
        store.transition_record(beta, record["request-id"], "cancelled")
    assert store.read_record(alpha, record["request-id"])["state"] == before["state"]


def test_the_ingress_routes_each_call_by_the_server_project_map_only(projects, tmp_path):
    alpha, beta = projects
    token = tmp_path / "token"
    token.write_text("t")
    token.chmod(0o600)
    config = shared_config.SharedGatewayServerConfig(
        server_id="s", port=0, service_root=None, projects={"alpha": alpha.resolve(), "beta": beta.resolve()},
        principals=(shared_config.SharedGatewayPrincipal(
            "operator", token, frozenset({"alpha", "beta"}), frozenset({"read", "submit", "cancel", "session"})),))
    ingress = SharedGatewayIngress(config)
    principal = config.principals[0]

    def call(project, **params):
        body = {"operation": "get_execution_request", "project-id": project, "params": params,
                "protocol-version": 1, "owner-epoch": "e", "lease-id": "l"}
        return ingress.prepare_call(principal, body, client_instance_id="c")

    assert call("alpha", request_id="req_1")[1] == str(alpha.resolve())
    assert call("beta", request_id="req_1")[1] == str(beta.resolve())
    with pytest.raises(AudiaGenticError):
        call("gamma", request_id="req_1")
    # A caller-supplied path is parameter data; it never selects the root.
    assert call("alpha", request_id="req_1", project_root=str(beta))[1] == str(alpha.resolve())


def test_a_project_cannot_set_gateway_settings(projects, monkeypatch, tmp_path):
    """The writer refuses a project-scope gateway section, and the gateway reads machine scopes only.

    A hand-edited project file that carries one still cannot change the gateway: its reader
    (`gateway_setting`) resolves with machine_only=True and never opens the project scope.
    """
    from audiagentic.components.agents.gateway.settings import gateway_setting
    from audiagentic.foundation.config.writer import write_settings_patch

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    alpha, _ = projects
    with pytest.raises(AudiaGenticError):
        write_settings_patch("project", {"gateway": {"port": 9999}}, project_root=alpha)
    (alpha / ".git").mkdir()
    (alpha / ".audiagentic" / "settings.yaml").write_text(
        "schema_version: 1\nproject:\n  id: alpha\ngateway:\n  port: 9999\n  connector: /evil/connector.yaml\n",
        encoding="utf-8")
    monkeypatch.chdir(alpha)
    assert gateway_setting("port") is None
    assert gateway_setting("connector") is None
