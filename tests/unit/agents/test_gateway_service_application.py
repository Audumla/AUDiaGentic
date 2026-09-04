from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.service.application import (
    GatewayServiceApplication,
)
from audiagentic.components.agents.gateway.service.contract import PROTOCOL_VERSION
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey


class Application:
    def submit_execution_request(self, project_root, **kwargs):
        return {"operation": "submit", "root": str(project_root), **kwargs}

    def get_execution_request(self, project_root, request_id):
        return {"operation": "get", "request-id": request_id}

    def wait_execution_request(self, project_root, request_id, timeout_seconds=None):
        return {"operation": "wait", "request-id": request_id, "timeout": timeout_seconds}

    def cancel_execution_request(self, project_root, request_id):
        return {"operation": "cancel", "request-id": request_id}

    def run_execution_request(self, project_root, **kwargs):
        return {"operation": "run", **kwargs}

    def list_execution_requests(self, project_root, **kwargs):
        return [{"operation": "list", **kwargs}]

    def gateway_overview(self, project_root):
        return {"operation": "overview"}

    def list_execution_sessions(self, project_root, **kwargs):
        return [{"operation": "sessions", **kwargs}]

    def close_execution_session(self, project_root, session_id):
        return {"operation": "close", "session-id": session_id}

    def control_execution_session(self, project_root, session_id, **kwargs):
        return {"operation": "control", "session-id": session_id, **kwargs}

    def resume_execution_session(self, project_root, source_session_id, **kwargs):
        return {"operation": "resume", "source-session-id": source_session_id, **kwargs}


def _service(tmp_path: Path) -> GatewayServiceApplication:
    store = ManagedServiceStore(ServiceKey("gateway", "unit"), root=tmp_path)
    created = store.create(protocol_version="gateway-service-v1", owner_epoch="epoch-unit")
    store.transition(
        "running", expected_revision=created.revision, expected_epoch=created.owner_epoch
    )
    return GatewayServiceApplication(Application(), store)  # type: ignore[arg-type]


def _authorization(service: GatewayServiceApplication) -> dict[str, str]:
    lease = service.acquire_client(
        "client-a", ttl_seconds=60, protocol_version=PROTOCOL_VERSION
    )
    return {
        "protocol_version": PROTOCOL_VERSION,
        "owner_epoch": lease["owner-epoch"],
        "lease_id": lease["lease-id"],
    }


def test_dashboard_action_token_survives_service_application_restart(tmp_path: Path) -> None:
    first = _service(tmp_path)
    token = first.dashboard_action_token
    assert len(token) >= 32
    assert (first._service_store.root / "dashboard-action.token").read_text(encoding="utf-8") == token

    second = GatewayServiceApplication(Application(), first._service_store)  # type: ignore[arg-type]
    assert second.dashboard_action_token == token


def test_closed_operation_router_calls_public_application(tmp_path: Path) -> None:
    service = _service(tmp_path)
    authorization = _authorization(service)

    assert service.invoke(
        "submit_execution_request",
        str(tmp_path),
        {"prompt_body": "hello"},
        **authorization,
    ) == {
        "operation": "submit", "root": str(tmp_path), "prompt_body": "hello",
        "_dispatch_owner_epoch": "epoch-unit",
        "_dispatch_service_root": str(service._service_store.root),
    }
    assert service.invoke(
        "wait_execution_request",
        str(tmp_path),
        {"request_id": "req_1", "timeout_seconds": 3},
        **authorization,
    )["timeout"] == 3

    submitted = service.invoke(
        "submit_execution_request",
        str(tmp_path),
        {
            "prompt_body": "hello",
            "component_profile": "client-profile",
            "workspace_name": "Workspace Name",
        },
        **authorization,
    )
    assert submitted["component_profile"] == "client-profile"
    assert submitted["workspace_name"] == "Workspace Name"

    seeded = service.invoke(
        "submit_execution_request",
        str(tmp_path),
        {
            "prompt_body": "continue",
            "provider_chat_url": "https://chatgpt.com/g/g-p-project/c/conversation-1",
        },
        **authorization,
    )
    assert seeded["provider_chat_url"].endswith("/c/conversation-1")

    resumed = service.invoke(
        "resume_execution_session",
        str(tmp_path),
        {
            "source_session_id": "ses_old",
            "control_id": "ctl_1",
            "context_id": "ctx-1",
            "agent_definition_id": "agent-a",
            "agent_definition_digest": "a" * 64,
            "role_ids": ["reviewer"],
            "role_set_digest": "r" * 64,
            "execution_profile_digest": "p" * 64,
            "effective_capability_digest": "c" * 64,
        },
        **authorization,
    )
    assert resumed == {
        "operation": "resume",
        "source-session-id": "ses_old",
        "control_id": "ctl_1",
        "context_id": "ctx-1",
        "agent_definition_id": "agent-a",
        "agent_definition_digest": "a" * 64,
        "role_ids": ["reviewer"],
        "role_set_digest": "r" * 64,
        "execution_profile_digest": "p" * 64,
        "effective_capability_digest": "c" * 64,
        "model_id": None,
    }

    controlled = service.invoke(
        "control_execution_session",
        str(tmp_path),
        {"session_id": "ses_1", "turn_id": "req_1", "action": "cancel-turn", "control_id": "ctl_1"},
        **authorization,
    )
    assert controlled == {
        "operation": "control",
        "session-id": "ses_1",
        "turn_id": "req_1",
        "action": "cancel-turn",
        "control_id": "ctl_1",
        "payload": None,
    }


def test_closed_operation_router_rejects_unknown_or_missing_parameters(tmp_path: Path) -> None:
    service = _service(tmp_path)
    authorization = _authorization(service)

    with pytest.raises(AudiaGenticError, match="VAL-AGSV-001"):
        service.invoke("unknown", str(tmp_path), {}, **authorization)
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-002"):
        service.invoke("get_execution_request", str(tmp_path), {}, **authorization)
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-022"):
        service.invoke(
            "submit_execution_request",
            str(tmp_path),
            {"prompt_body": "hello", "surprise": True},
            **authorization,
        )
    with pytest.raises(AudiaGenticError, match="VAL-AGW-069"):
        service.invoke(
            "submit_execution_request",
            str(tmp_path),
            {"prompt_body": "hello", "metadata": {"schema_version": 999}},
            **authorization,
        )


def test_submission_discards_retired_null_timeout_fields(tmp_path: Path) -> None:
    service = _service(tmp_path)
    authorization = _authorization(service)

    result = service.invoke(
        "submit_execution_request",
        str(tmp_path),
        {
            "prompt_body": "hello",
            "timeout_seconds": None,
            "session_idle_timeout_seconds": None,
            "session_max_lifetime_seconds": None,
        },
        **authorization,
    )

    assert "timeout_seconds" not in result
    assert "session_idle_timeout_seconds" not in result
    assert "session_max_lifetime_seconds" not in result


def test_submission_rejects_non_null_retired_timeout_fields(tmp_path: Path) -> None:
    service = _service(tmp_path)
    authorization = _authorization(service)

    with pytest.raises(AudiaGenticError, match="VAL-AGSV-022"):
        service.invoke(
            "submit_execution_request",
            str(tmp_path),
            {"prompt_body": "hello", "timeout_seconds": 30},
            **authorization,
        )


def test_service_application_owns_client_lease_mutations(tmp_path: Path) -> None:
    service = _service(tmp_path)

    lease = service.acquire_client(
        "client-a", ttl_seconds=60, protocol_version=PROTOCOL_VERSION
    )
    renewed = service.renew_client(
        lease["lease-id"], ttl_seconds=60, owner_epoch=lease["owner-epoch"],
        protocol_version=PROTOCOL_VERSION,
    )
    released = service.release_client(
        lease["lease-id"], owner_epoch=lease["owner-epoch"],
        protocol_version=PROTOCOL_VERSION,
    )

    assert renewed["lease-id"] == lease["lease-id"]
    assert released["state"] == "released"


def test_domain_calls_require_matching_protocol_and_active_lease(tmp_path: Path) -> None:
    service = _service(tmp_path)
    authorization = _authorization(service)

    with pytest.raises(AudiaGenticError, match="VAL-AGSV-013"):
        service.invoke(
            "gateway_overview",
            str(tmp_path),
            {},
            **{**authorization, "protocol_version": "gateway-service-v999"},
        )

    service.release_client(
        authorization["lease_id"],
        owner_epoch=authorization["owner_epoch"],
        protocol_version=PROTOCOL_VERSION,
    )
    with pytest.raises(AudiaGenticError, match="CON-AGSV-018"):
        service.invoke("gateway_overview", str(tmp_path), {}, **authorization)


def test_gateway_operations_are_closed_durable_service_operations(tmp_path: Path) -> None:
    service = _service(tmp_path)
    authorization = _authorization(service)

    created = service.invoke(
        "create_gateway_operation",
        str(tmp_path),
        {
            "operation_id": "op_001",
            "kind": "reconcile",
            "scope": {"project-id": "project-a", "dry-run": True},
            "correlation_id": "corr_1",
        },
        **authorization,
    )
    repeated = service.invoke(
        "create_gateway_operation",
        str(tmp_path),
        {
            "operation_id": "op_001",
            "kind": "reconcile",
            "scope": {"project-id": "project-a", "dry-run": True},
            "correlation_id": "corr_1",
        },
        **authorization,
    )

    assert created["state"] == "accepted"
    assert repeated == created
    assert service.invoke(
        "get_gateway_operation", str(tmp_path), {"operation_id": "op_001"}, **authorization
    )["operation-id"] == "op_001"

    with pytest.raises(AudiaGenticError, match="VAL-AGSV-027"):
        service.invoke(
            "create_gateway_operation",
            str(tmp_path),
            {"operation_id": "op_bad", "kind": "unsupported", "scope": {}},
            **authorization,
        )


def test_drain_rejects_work_even_through_a_preexisting_lease(tmp_path: Path) -> None:
    service = _service(tmp_path)
    authorization = _authorization(service)
    record = service._service_store.read()
    service._service_store.transition(
        "draining", expected_revision=record.revision, expected_epoch=record.owner_epoch
    )

    with pytest.raises(AudiaGenticError, match="CON-AGSV-029"):
        service.invoke(
            "submit_execution_request", str(tmp_path), {"prompt_body": "must not start"}, **authorization
        )

    assert service.invoke("gateway_overview", str(tmp_path), {}, **authorization) == {
        "operation": "overview"
    }


def test_resume_refuses_while_gateway_operation_is_active(tmp_path: Path) -> None:
    service = _service(tmp_path)
    authorization = _authorization(service)
    service.invoke(
        "create_gateway_operation",
        str(tmp_path),
        {"operation_id": "op_002", "kind": "reconcile", "scope": {}},
        **authorization,
    )

    with pytest.raises(AudiaGenticError, match="CON-AGSV-030"):
        service.invoke("service_resume", str(tmp_path), {}, **authorization)
