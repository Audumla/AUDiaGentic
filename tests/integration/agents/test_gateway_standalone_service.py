from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from audiagentic.components.agents.configuration.management import (
    create_execution_profile,
)
from audiagentic.components.agents.gateway.application import InProcessGatewayApplication
from audiagentic.components.agents.gateway.client import (
    get_gateway_client,
    reset_gateway_client,
)
from audiagentic.components.agents.gateway.remote_client import (
    StandaloneGatewayClient,
    load_auth_token,
)
from audiagentic.components.agents.gateway.service.contract import PROTOCOL_VERSION
from audiagentic.components.agents.gateway.service.host import GatewayServiceHost
from audiagentic.components.agents.gateway.service.known_projects import record_known_project
from audiagentic.components.providers.providers_api import ProviderExecutionResult
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state
from audiagentic.foundation.system.managed_process import observe_process, signal_owned_process
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.process import choose_free_port


class SharedApplication:
    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.requests: dict[str, dict] = {}
        self.session_records: dict[str, list[dict]] = {}
        self.next_id = 0
        self.run_started = threading.Event()
        self.run_release = threading.Event()
        self.run_completed = threading.Event()

    def submit_execution_request(self, project_root, **kwargs):
        with self.guard:
            self.next_id += 1
            request_id = f"req_{self.next_id}"
            record = {"request-id": request_id, "state": "queued", "root": str(project_root), **kwargs}
            self.requests[request_id] = record
            return dict(record)

    def get_execution_request(self, project_root, request_id):
        return dict(self.requests[request_id])

    def wait_execution_request(self, project_root, request_id, timeout_seconds=None):
        return dict(self.requests[request_id])

    def cancel_execution_request(self, project_root, request_id):
        with self.guard:
            self.requests[request_id]["state"] = "cancel-requested"
            return dict(self.requests[request_id])

    def run_execution_request(self, project_root, **kwargs):
        self.run_started.set()
        self.run_release.wait(timeout=5)
        self.run_completed.set()
        return {"request-id": "req_blocking", "state": "succeeded"}

    def list_execution_requests(self, project_root, **kwargs):
        return [dict(value) for value in self.requests.values()]

    def gateway_overview(self, project_root):
        return {"total_requests": len(self.requests), "project-root": str(project_root)}

    def list_execution_sessions(self, project_root, **kwargs):
        return [dict(value) for value in self.session_records.get(str(project_root), [])]

    def close_execution_session(self, project_root, session_id):
        return {"session-id": session_id, "state": "closed"}


def _start_host(
    tmp_path: Path,
    application: SharedApplication,
):
    service_root = tmp_path / "services"
    token_path = tmp_path / "gateway.token"
    host = GatewayServiceHost.create(
        application=application,  # type: ignore[arg-type]
        service_root=service_root,
        token_path=token_path,
    )
    thread = threading.Thread(target=host.serve_forever, name="test-gateway-service")
    thread.start()
    return host, thread, service_root, token_path


def _stop_host(host: GatewayServiceHost, thread: threading.Thread) -> None:
    host.shutdown()
    thread.join(timeout=5)
    assert not thread.is_alive()
    host.close()


def _raw_post(endpoint: str, token: str, route: str, body: dict) -> dict:
    request = Request(
        f"{endpoint}{route}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def _raw_get(endpoint: str, route: str) -> tuple[str, bytes]:
    with urlopen(f"{endpoint}{route}", timeout=2) as response:
        return response.headers["Content-Type"], response.read()


def _make_profile(project_root: Path) -> None:
    create_execution_profile(project_root, {
        "profile_id": "default",
        "provider_id": "local-openai",
        "instances": ["gpt-4o"],
        "model_id": "gpt-4o",
        "is_default": True,
        "params": {},
    })
    set_implementation_state(
        project_root, "providers", "local-openai", ImplementationState(enabled=True)
    )


def test_independent_clients_share_one_authenticated_control_plane(tmp_path: Path) -> None:
    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    token = load_auth_token(token_path)
    first = StandaloneGatewayClient(host.endpoint, token)
    second = StandaloneGatewayClient(host.endpoint, token)
    try:
        submitted = first.submit_execution_request(tmp_path, prompt_body="hello", mode="async")
        observed = second.get_execution_request(tmp_path, submitted["request-id"])
        cancelled = second.cancel_execution_request(tmp_path, submitted["request-id"])

        assert observed["request-id"] == submitted["request-id"]
        assert cancelled["state"] == "cancel-requested"
        assert host.service_store.read().active_lease_count == 2
    finally:
        first.close()
        second.close()
        _stop_host(host, thread)
    assert host.service_store.read().state == "stopped"


def test_authenticated_raw_calls_cannot_bypass_protocol_or_lease_authority(
    tmp_path: Path,
) -> None:
    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    token = load_auth_token(token_path)
    try:
        mismatch = _raw_post(
            host.endpoint,
            token,
            "/v1/client-leases/acquire",
            {
                "client-instance-id": "client-raw",
                "ttl-seconds": 60,
                "protocol-version": "gateway-service-v999",
            },
        )
        bypass = _raw_post(
            host.endpoint,
            token,
            "/v1/call",
            {
                "protocol-version": PROTOCOL_VERSION,
                "owner-epoch": host.owner_epoch,
                "lease-id": "lease_missing",
                "operation": "gateway_overview",
                "project-root": str(tmp_path),
                "params": {},
            },
        )

        assert mismatch["error-code"] == "VAL-AGSV-013"
        assert bypass["error-code"] == "CON-AGSV-018"
        assert application.requests == {}
    finally:
        _stop_host(host, thread)


def test_loopback_dashboard_is_public_but_redacted_and_independent_of_browser(
    tmp_path: Path,
) -> None:
    application = SharedApplication()
    host, thread, _service_root, _token_path = _start_host(tmp_path, application)
    try:
        content_type, page = _raw_get(host.endpoint, "/dashboard")
        assert content_type.startswith("text/html")
        assert b"Agent gateway" in page
        assert b"fetch(endpoint)" in page
        assert b'id="state-filter"' in page
        assert b'id="show-closed"' in page
        assert b'id="show-empty"' in page
        # Empty sessions are available only when explicitly requested.  A
        # live runtime handle is not evidence that the session has any task
        # records; it must not bypass the default empty-session filter.
        assert b"showEmpty.checked||hasRequests" in page
        assert b"showClosed.checked||!isClosed(s)||hasRequests" in page
        assert b'id="recent-window"' in page
        assert b"recent-seconds" in page
        assert b"One-shot requests" in page
        assert b"newest first" in page
        assert b"Watchdog monitoring guide" in page
        assert b"stale monitoring marker" in page
        assert b"Open GPT chat" in page

        content_type, snapshot = _raw_get(host.endpoint, "/dashboard/snapshot")
        assert content_type.startswith("application/json")
        payload = json.loads(snapshot)
        assert payload["contract-version"] == "v1"
        assert payload["projects"] == []
        assert payload["requests"] == []
        assert payload["failures"] == []
        assert "prompt" not in json.dumps(payload).lower()
    finally:
        _stop_host(host, thread)


def test_dashboard_recent_window_filters_history_and_supports_query_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
    old = (now - timedelta(seconds=180)).isoformat().replace("+00:00", "Z")
    application = SharedApplication()
    application.requests = {
        "req-running": {
            "request-id": "req-running",
            "state": "running",
            "session-id": "ses-running",
            "execution-profile-id": "default",
            "resolved-provider-id": "gpt-auto-t2",
            "resolved-model-id": "chatgpt",
            "updated-at": fresh,
            "last-activity-at": fresh,
            "activity": {"phase": "tool-progress"},
            "activity-sequence": 42,
            "activity-source": "session-transport",
            "watchdog-state": "active",
        },
        "req-fresh": {
            "request-id": "req-fresh",
            "state": "completed",
            "session-id": "ses-fresh",
            "execution-profile-id": "default",
            "resolved-provider-id": "local-openai",
            "resolved-model-id": "model",
            "updated-at": fresh,
        },
        "req-one-shot": {
            "request-id": "req-one-shot",
            "state": "completed",
            "execution-profile-id": "qwen-mid",
            "resolved-provider-id": "pi",
            "resolved-model-id": "brutus/qwen3.6-27b-0",
            "updated-at": fresh,
        },
        "req-old": {
            "request-id": "req-old",
            "state": "failed",
            "session-id": "ses-old",
            "execution-profile-id": "default",
            "resolved-provider-id": "local-openai",
            "resolved-model-id": "model",
            "updated-at": old,
            "error": {"code": "EXT-TEST", "message": "old"},
        },
    }
    application.session_records[str(project_root)] = [
        {
            "session-id": "ses-running",
            "execution-profile-id": "default",
            "state": "active",
            "live": True,
            "timing": {"updated-at": fresh},
            "activity": {"turn-count": 1},
        },
        {
            "session-id": "ses-fresh",
            "execution-profile-id": "default",
            "state": "closed",
            "timing": {"updated-at": fresh},
            "activity": {"turn-count": 1},
        },
        {
            "session-id": "ses-old",
            "execution-profile-id": "default",
            "state": "closed",
            "timing": {"updated-at": old},
            "activity": {"turn-count": 1},
        },
    ]
    from audiagentic.components.agents.gateway import api as gateway_api

    monkeypatch.setattr(
        gateway_api,
        "list_dashboard_requests",
        lambda _root: list(application.requests.values()),
    )
    monkeypatch.setattr(
        gateway_api,
        "list_execution_sessions",
        lambda _root: list(application.session_records[str(project_root)]),
    )
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_DASHBOARD_RECENT_SECONDS", "60")
    host, thread, _service_root, _token_path = _start_host(tmp_path, application)
    record_known_project(
        host.service_store.root / "known-projects.json", project_root=project_root
    )
    try:
        _content_type, response = _raw_get(host.endpoint, "/dashboard/snapshot")
        payload = json.loads(response)
        assert payload["dashboard"]["recent-window-seconds"] == 60
        assert {row["request-id"] for row in payload["requests"]} == {"req-running", "req-fresh", "req-one-shot"}
        running = next(row for row in payload["requests"] if row["request-id"] == "req-running")
        assert running["state"] == "running"
        assert running["activity"]["phase"] == "tool-progress"
        assert running["activity-type"] == "tool-progress"
        assert running["activity-sequence"] == 42
        assert {row["session-id"] for row in payload["projects"][0]["sessions"]} == {"ses-running", "ses-fresh"}
        assert any(
            row["request-id"] == "req-one-shot" and "session-id" not in row
            for row in payload["projects"][0]["requests"]
        )
        assert payload["failures"] == []

        _content_type, response = _raw_get(
            host.endpoint, "/dashboard/snapshot?recent-seconds=240"
        )
        override = json.loads(response)
        assert override["dashboard"]["recent-window-seconds"] == 240
        assert {row["request-id"] for row in override["requests"]} == {"req-running", "req-fresh", "req-one-shot", "req-old"}
        assert override["dashboard"]["recent-window-source"] == "dashboard"
    finally:
        _stop_host(host, thread)


def test_dashboard_path_is_configurable_without_changing_gateway_rpc_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_DASHBOARD_PATH", "/operations")
    application = SharedApplication()
    host, thread, _service_root, _token_path = _start_host(tmp_path, application)
    try:
        content_type, page = _raw_get(host.endpoint, "/operations")
        assert content_type.startswith("text/html")
        assert b"/operations/snapshot" in page
    finally:
        _stop_host(host, thread)


def test_gateway_operation_runs_durably_and_redacts_private_scope(tmp_path: Path) -> None:
    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    client = StandaloneGatewayClient(host.endpoint, load_auth_token(token_path))
    try:
        created = client.create_gateway_operation(
            tmp_path,
            operation_id="op_standalone_reconcile_001",
            kind="reconcile",
            scope={"project-root": str(tmp_path)},
            correlation_id="corr_standalone",
        )
        deadline = time.monotonic() + 5
        current = created
        while current["state"] in {"accepted", "running"} and time.monotonic() < deadline:
            time.sleep(0.05)
            current = client.get_gateway_operation(tmp_path, "op_standalone_reconcile_001")

        assert current["state"] == "completed"
        assert current["result"] == {
            "blocked": 0,
            "changed": 0,
            "unchanged": 0,
            "unknown-evidence": 0,
            "live": 0,
        }
        assert "scope" not in current
        assert "correlation-id" not in current
    finally:
        client.close()
        _stop_host(host, thread)


@pytest.mark.parametrize(
    ("operation_id", "kind", "scope", "error_code"),
    [
        ("x", "reconcile", {"project-root": "C:/workspace"}, "VAL-AGM-003"),
        ("op_bad_kind_001", "unknown", {}, "VAL-AGSV-027"),
        ("op_unsafe_001", "reconcile", {"prompt-body": "secret"}, "VAL-AGM-005"),
    ],
)
def test_gateway_operation_rejects_invalid_or_unsafe_commands(
    tmp_path: Path,
    operation_id: str,
    kind: str,
    scope: dict,
    error_code: str,
) -> None:
    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    client = StandaloneGatewayClient(host.endpoint, load_auth_token(token_path))
    try:
        with pytest.raises(AudiaGenticError, match=error_code):
            client.create_gateway_operation(
                tmp_path,
                operation_id=operation_id,
                kind=kind,
                scope=scope,
            )
    finally:
        client.close()
        _stop_host(host, thread)


def test_operator_force_stop_exits_the_host_without_handler_deadlock(tmp_path: Path) -> None:
    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    client = StandaloneGatewayClient(host.endpoint, load_auth_token(token_path))
    try:
        stopped = client.service_stop(tmp_path, force=True)
        assert stopped["stopping"] is True
        thread.join(timeout=5)
        assert not thread.is_alive()
    finally:
        client.close()
        host.close()
    assert host.service_store.read().state == "stopped"


@pytest.mark.parametrize(
    "params",
    [
        {"prompt_body": "hello", "metadata": {"idempotency_key": 7}},
        {"prompt_body": "hello", "metadata": {"schema_version": "1"}},
        {"prompt_body": "hello", "timeout_seconds": "later"},
    ],
)
def test_standalone_submission_wire_errors_are_canonical_client_errors(
    tmp_path: Path, params: dict
) -> None:
    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    token = load_auth_token(token_path)
    try:
        lease = _raw_post(
            host.endpoint,
            token,
            "/v1/client-leases/acquire",
            {
                "client-instance-id": "submission-validation",
                "ttl-seconds": 60,
                "protocol-version": PROTOCOL_VERSION,
            },
        )["result"]
        response = _raw_post(
            host.endpoint,
            token,
            "/v1/call",
            {
                "protocol-version": PROTOCOL_VERSION,
                "owner-epoch": lease["owner-epoch"],
                "lease-id": lease["lease-id"],
                "operation": "submit_execution_request",
                "project-root": str(tmp_path),
                "params": params,
            },
        )
        assert response["error-code"] == "VAL-AGW-082"
        assert application.requests == {}
    finally:
        _stop_host(host, thread)


def test_expired_client_lease_reattaches_once_before_domain_call(
    tmp_path: Path,
) -> None:
    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    client = StandaloneGatewayClient(
        host.endpoint, load_auth_token(token_path), lease_ttl_seconds=0.1
    )
    try:
        client.connect()
        original_lease = client._lease_id
        time.sleep(0.15)

        overview = client.gateway_overview(tmp_path)

        assert overview["project-root"] == str(tmp_path)
        assert client._lease_id is not None
        assert client._lease_id != original_lease
        assert host.service_store.read().active_lease_count == 1
    finally:
        client.close()
        _stop_host(host, thread)


def test_spawned_harness_clients_attach_to_same_owner(tmp_path: Path) -> None:
    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    helper = Path(__file__).parents[2] / "helpers" / "gateway_service_client.py"
    clients = [
        subprocess.Popen(
            [sys.executable, str(helper), host.endpoint, str(token_path), str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    try:
        results = []
        for client in clients:
            stdout, stderr = client.communicate(timeout=20)
            assert client.returncode == 0, stderr
            results.append(json.loads(stdout))
        assert len(results) == 4
        assert host.service_store.read().active_lease_count == 0
    finally:
        _stop_host(host, thread)


def test_client_timeout_does_not_cancel_service_owned_work(tmp_path: Path) -> None:
    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    client = StandaloneGatewayClient(host.endpoint, load_auth_token(token_path), request_timeout=0.05)
    try:
        with pytest.raises(AudiaGenticError, match="NET-AGSV-002"):
            client.run_execution_request(tmp_path, prompt_body="slow")
        assert application.run_started.wait(timeout=3)
        application.run_release.set()
        assert application.run_completed.wait(timeout=3)
    finally:
        application.run_release.set()
        client.close()
        _stop_host(host, thread)


def test_real_gateway_work_survives_submitter_disconnect(tmp_path: Path, monkeypatch) -> None:
    _make_profile(tmp_path)
    provider_started = threading.Event()
    provider_release = threading.Event()

    def slow_provider(*, identity, execution_request, timeout_seconds):
        provider_started.set()
        provider_release.wait(timeout=5)
        return ProviderExecutionResult(
            provider_id="local-openai", model_id="gpt-4o",
            worker_id=identity.worker_id, attempt_epoch=identity.attempt_epoch,
            result_data={"provider-id": "local-openai", "model": "gpt-4o", "output": "service-owned result"},
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn", slow_provider
    )
    host = GatewayServiceHost.create(
        service_root=tmp_path / "service-state",
        token_path=tmp_path / "real.token",
    )
    thread = threading.Thread(target=host.serve_forever)
    thread.start()
    token = load_auth_token(host.token_path)
    submitter = StandaloneGatewayClient(host.endpoint, token)
    observer = StandaloneGatewayClient(host.endpoint, token)
    try:
        submitted = submitter.submit_execution_request(
            tmp_path, prompt_body="continue after disconnect", mode="async"
        )
        assert provider_started.wait(timeout=2)
        submitter.close()
        assert host.service_store.read().active_lease_count == 0

        provider_release.set()
        result = observer.wait_execution_request(
            tmp_path, submitted["request-id"], timeout_seconds=5
        )
        assert result["state"] == "completed"
        assert result["output"] == "service-owned result"
    finally:
        provider_release.set()
        submitter.close()
        observer.close()
        _stop_host(host, thread)


def test_unauthenticated_and_malformed_clients_are_rejected_without_token_leak(tmp_path: Path) -> None:
    application = SharedApplication()
    host, thread, service_root, token_path = _start_host(tmp_path, application)
    token = load_auth_token(token_path)
    try:
        request = Request(f"{host.endpoint}/v1/health", headers={"Authorization": "Bearer wrong"})
        with pytest.raises(HTTPError) as unauthenticated:
            urlopen(request, timeout=2)
        assert unauthenticated.value.code == 401
        error = json.loads(unauthenticated.value.read().decode("utf-8"))
        assert error["error-code"] == "VAL-AGSV-005"

        malformed = Request(
            f"{host.endpoint}/v1/call",
            data=b"not-json",
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as invalid:
            urlopen(malformed, timeout=2)
        assert json.loads(invalid.value.read().decode("utf-8"))["error-code"] == "VAL-AGSV-007"

        assert token not in (service_root / "machine" / "agent-execution-gateway" / "default" / "service.json").read_text(encoding="utf-8")
    finally:
        _stop_host(host, thread)


def test_clean_restart_reuses_token_and_rotates_owner_epoch(tmp_path: Path) -> None:
    application = SharedApplication()
    first, first_thread, service_root, token_path = _start_host(tmp_path, application)
    first_epoch = first.owner_epoch
    token = load_auth_token(token_path)
    _stop_host(first, first_thread)

    second = GatewayServiceHost.create(
        application=application,  # type: ignore[arg-type]
        service_root=service_root,
        token_path=token_path,
    )
    second_thread = threading.Thread(target=second.serve_forever)
    second_thread.start()
    try:
        assert second.owner_epoch != first_epoch
        assert load_auth_token(token_path) == token
        with StandaloneGatewayClient(second.endpoint, token) as client:
            assert client.health()["owner-epoch"] == second.owner_epoch
    finally:
        _stop_host(second, second_thread)


def test_host_background_operation_completes_after_readiness(tmp_path: Path) -> None:
    from audiagentic.components.agents.gateway.operations import (
        GatewayOperationsApplication,
        ManagementCommand,
        ManagementOperationKind,
        ManagementOperationStore,
    )
    request_id = "req_host_ready_archive"
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
    request_dir.mkdir(parents=True)
    (request_dir / "record.json").write_text('{"state":"completed"}', encoding="utf-8")
    application = InProcessGatewayApplication()
    host, thread, _service_root, _token = _start_host(tmp_path, application)  # type: ignore[arg-type]
    try:
        op = GatewayOperationsApplication(ManagementOperationStore(host.service_store.root))
        op.create_operation(ManagementCommand(operation_id="op_ready_archive", kind=ManagementOperationKind.RECONCILE, scope={"project-root": str(tmp_path), "dry-run": True}))
        deadline = time.monotonic() + 3.5
        while time.monotonic() < deadline and ManagementOperationStore(host.service_store.root).read("op_ready_archive")["state"] != "completed":
            time.sleep(0.05)
        final = ManagementOperationStore(host.service_store.root).read("op_ready_archive")
        assert final["state"] == "completed", final
    finally:
        _stop_host(host, thread)


def test_host_startup_scan_executes_operation_persisted_before_start(tmp_path: Path) -> None:
    from audiagentic.components.agents.gateway.operations import (
        GatewayOperationsApplication,
        ManagementCommand,
        ManagementOperationKind,
        ManagementOperationStore,
    )
    request_id = "req_startup_archive"
    request_dir = tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / request_id
    request_dir.mkdir(parents=True)
    (request_dir / "record.json").write_text('{"state":"completed"}', encoding="utf-8")
    service_root = tmp_path / "services"
    store = ManagementOperationStore(service_root / "machine" / "agent-execution-gateway" / "default")
    GatewayOperationsApplication(store).create_operation(ManagementCommand(operation_id="op_startup_archive", kind=ManagementOperationKind.RECONCILE, scope={"project-root": str(tmp_path), "dry-run": True}))
    host, thread, _service_root, _token = _start_host(tmp_path, InProcessGatewayApplication())  # type: ignore[arg-type]
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and store.read("op_startup_archive")["state"] != "completed":
            time.sleep(0.05)
        assert store.read("op_startup_archive")["state"] == "completed"
    finally:
        _stop_host(host, thread)


def test_restart_preserves_durable_request_history_exactly(tmp_path: Path) -> None:
    """SH11 rollback rehearsal: restart changes owner epoch, not request history."""
    from audiagentic.components.agents.gateway import store as request_store

    application = SharedApplication()
    project_root = tmp_path / "project"
    project_root.mkdir()
    durable = request_store.build_record(execution_profile_id="default", prompt_body="history")
    durable["state"] = "completed"
    durable["output"] = "stable"
    request_store.write_record(project_root, durable)
    first, first_thread, service_root, token_path = _start_host(tmp_path, application)
    before = request_store.read_record(project_root, durable["request-id"])
    _stop_host(first, first_thread)
    second = GatewayServiceHost.create(application=application, service_root=service_root, token_path=token_path)
    second_thread = threading.Thread(target=second.serve_forever)
    second_thread.start()
    try:
        after = request_store.read_record(project_root, durable["request-id"])
        assert after == before
    finally:
        _stop_host(second, second_thread)


def test_explicit_composition_mode_selects_standalone_without_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_MODE", "standalone")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_ENDPOINT", host.endpoint)
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_TOKEN_FILE", str(token_path))
    reset_gateway_client()
    try:
        client = get_gateway_client()
        assert isinstance(client, StandaloneGatewayClient)
        assert client.gateway_overview(tmp_path)["project-root"] == str(tmp_path)
    finally:
        reset_gateway_client()
        _stop_host(host, thread)


def test_service_process_crash_allows_deterministic_explicit_restart(tmp_path: Path) -> None:
    from audiagentic.components.agents.gateway.service.host import GATEWAY_SERVICE_KEY

    port = choose_free_port("127.0.0.1")
    endpoint = f"http://127.0.0.1:{port}"
    token_path = tmp_path / "process.token"
    command = [
        sys.executable,
        "-m",
        "audiagentic.launcher",
        "gateway",
        "serve",
        "--port",
        str(port),
        "--token-file",
        str(token_path),
    ]

    def start() -> subprocess.Popen:
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def await_health(process: subprocess.Popen) -> dict:
        deadline = time.monotonic() + 10
        last_error = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"gateway service exited early: {process.returncode}")
            if token_path.exists():
                try:
                    return StandaloneGatewayClient(
                        endpoint, load_auth_token(token_path), request_timeout=0.2
                    ).health()
                except AudiaGenticError as exc:
                    last_error = exc
            time.sleep(0.05)
        raise AssertionError(f"gateway service did not become healthy: {last_error}")

    first = start()
    second = None
    try:
        first_health = await_health(first)
        first_record = ManagedServiceStore(GATEWAY_SERVICE_KEY).read()
        assert first_record.process is not None
        signal_owned_process(
            first_record.process,
            observe_process(first_record.process),
            force=True,
        )
        # A Windows virtual-environment launcher can remain after the owned
        # interpreter has exited. It is not the service identity published in
        # the durable record, so reap that test-only wrapper separately.
        if first.poll() is None:
            first.kill()
        first.wait(timeout=5)

        second = start()
        second_health = await_health(second)

        assert second_health["owner-epoch"] != first_health["owner-epoch"]
        assert second.pid != first.pid
        second_record = ManagedServiceStore(GATEWAY_SERVICE_KEY).read()
        assert second_record.process is not None
        assert observe_process(second_record.process) is not None
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=5)
        if second is not None and second.poll() is None:
            second.kill()
            second.wait(timeout=5)


# ── SH09/SH10: durable ingress through a live host; idle self-shutdown ──


def test_spooled_trigger_is_admitted_by_running_service(tmp_path: Path) -> None:
    """A trigger published while the service is DOWN is durably admitted once
    the service starts, carrying spool-derived idempotency and correlation."""
    from audiagentic.components.agents.gateway.event_topics import GATEWAY_REQUESTED_TOPIC

    application = SharedApplication()
    service_root = tmp_path / "services"
    # Publish from a genuinely separate OS process — the SH09 validation is
    # cross-process durable admission, not same-process convenience.
    import subprocess
    import sys

    publisher = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from pathlib import Path\n"
                "from audiagentic.components.agents.gateway.ingress import publish_gateway_trigger\n"
                f"event_id = publish_gateway_trigger({GATEWAY_REQUESTED_TOPIC!r}, "
                f"{{'project-root': {str(tmp_path / 'proj')!r}, 'prompt-body': 'spooled hello'}}, "
                f"metadata={{'correlation_id': 'corr-spool'}}, service_root=Path({str(service_root)!r}))\n"
                "print(event_id)"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    event_id = publisher.stdout.strip()
    assert event_id

    host, thread, _service_root, _token_path = _start_host(tmp_path, application)
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not application.requests:
            time.sleep(0.05)
        assert application.requests, "spooled trigger was not admitted"
        record = next(iter(application.requests.values()))
        assert record["prompt_body"] == "spooled hello"
        assert record["metadata"]["idempotency_key"] == f"gateway-spool:{event_id}"
        assert record["metadata"]["correlation_id"] == "corr-spool"
    finally:
        _stop_host(host, thread)


def test_idle_grace_self_shutdown_retires_record(tmp_path: Path, monkeypatch) -> None:
    """With an idle grace configured, a quiescent service with no leases
    drains and exits by itself; close() retires the record to 'stopped'."""
    from audiagentic.components.agents.gateway.service.host import GATEWAY_SERVICE_KEY

    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_IDLE_GRACE_SECONDS", "0.1")
    application = SharedApplication()
    host, thread, service_root, _token_path = _start_host(tmp_path, application)
    # Integration override: tighten the sweep cadence so the test is fast.
    host.lifecycle._check_interval = 0.05  # type: ignore[union-attr]
    try:
        thread.join(timeout=10.0)
        assert not thread.is_alive(), "service did not self-shutdown after idle grace"
        assert host.lifecycle.exit_reason == "idle-grace-elapsed"  # type: ignore[union-attr]
    finally:
        host.close()
    store = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=service_root)
    assert store.read().state == "stopped"
