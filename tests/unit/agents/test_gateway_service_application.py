from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.agents_gateway_service_application import (
    GatewayServiceApplication,
)
from audiagentic.components.agents.agents_gateway_service_contract import PROTOCOL_VERSION
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey


class Application:
    def submit_llm_request(self, project_root, **kwargs):
        return {"operation": "submit", "root": str(project_root), **kwargs}

    def get_llm_request(self, project_root, request_id):
        return {"operation": "get", "request-id": request_id}

    def wait_llm_request(self, project_root, request_id, timeout_seconds=None):
        return {"operation": "wait", "request-id": request_id, "timeout": timeout_seconds}

    def cancel_llm_request(self, project_root, request_id):
        return {"operation": "cancel", "request-id": request_id}

    def run_llm_request(self, project_root, **kwargs):
        return {"operation": "run", **kwargs}

    def list_llm_requests(self, project_root, **kwargs):
        return [{"operation": "list", **kwargs}]

    def gateway_overview(self, project_root):
        return {"operation": "overview"}

    def list_llm_sessions(self, project_root, **kwargs):
        return [{"operation": "sessions", **kwargs}]

    def close_llm_session(self, project_root, session_id):
        return {"operation": "close", "session-id": session_id}


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


def test_closed_operation_router_calls_public_application(tmp_path: Path) -> None:
    service = _service(tmp_path)
    authorization = _authorization(service)

    assert service.invoke(
        "submit_llm_request",
        str(tmp_path),
        {"prompt_body": "hello"},
        **authorization,
    ) == {
        "operation": "submit", "root": str(tmp_path), "prompt_body": "hello",
        "_dispatch_owner_epoch": "epoch-unit",
    }
    assert service.invoke(
        "wait_llm_request",
        str(tmp_path),
        {"request_id": "req_1", "timeout_seconds": 3},
        **authorization,
    )["timeout"] == 3

    submitted = service.invoke(
        "submit_llm_request",
        str(tmp_path),
        {"prompt_body": "hello", "component_profile": "client-profile"},
        **authorization,
    )
    assert submitted["component_profile"] == "client-profile"


def test_closed_operation_router_rejects_unknown_or_missing_parameters(tmp_path: Path) -> None:
    service = _service(tmp_path)
    authorization = _authorization(service)

    with pytest.raises(AudiaGenticError, match="VAL-AGSV-001"):
        service.invoke("unknown", str(tmp_path), {}, **authorization)
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-002"):
        service.invoke("get_llm_request", str(tmp_path), {}, **authorization)
    with pytest.raises(AudiaGenticError, match="VAL-AGSV-022"):
        service.invoke(
            "submit_llm_request",
            str(tmp_path),
            {"prompt_body": "hello", "surprise": True},
            **authorization,
        )
    with pytest.raises(AudiaGenticError, match="VAL-AGW-069"):
        service.invoke(
            "submit_llm_request",
            str(tmp_path),
            {"prompt_body": "hello", "metadata": {"schema_version": 999}},
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
