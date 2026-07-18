from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from audiagentic.components.agents import agents_gateway_api as gateway_api
from audiagentic.components.agents import agents_gateway_queue
from audiagentic.components.agents.agents_api import create_profile
from audiagentic.components.agents.agents_gateway_client import (
    get_gateway_client,
    reset_gateway_client,
)
from audiagentic.components.agents.agents_gateway_remote_client import (
    StandaloneGatewayClient,
    load_auth_token,
)
from audiagentic.components.agents.agents_gateway_service_host import GatewayServiceHost
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
        self.next_id = 0
        self.run_started = threading.Event()
        self.run_release = threading.Event()
        self.run_completed = threading.Event()

    def submit_llm_request(self, project_root, **kwargs):
        with self.guard:
            self.next_id += 1
            request_id = f"req_{self.next_id}"
            record = {"request-id": request_id, "state": "queued", "root": str(project_root), **kwargs}
            self.requests[request_id] = record
            return dict(record)

    def get_llm_request(self, project_root, request_id):
        return dict(self.requests[request_id])

    def wait_llm_request(self, project_root, request_id, timeout_seconds=None):
        return dict(self.requests[request_id])

    def cancel_llm_request(self, project_root, request_id):
        with self.guard:
            self.requests[request_id]["state"] = "cancel-requested"
            return dict(self.requests[request_id])

    def run_llm_request(self, project_root, **kwargs):
        self.run_started.set()
        self.run_release.wait(timeout=5)
        self.run_completed.set()
        return {"request-id": "req_blocking", "state": "succeeded"}

    def list_llm_requests(self, project_root, **kwargs):
        return [dict(value) for value in self.requests.values()]

    def gateway_overview(self, project_root):
        return {"total_requests": len(self.requests), "project-root": str(project_root)}

    def list_llm_sessions(self, project_root, **kwargs):
        return []

    def close_llm_session(self, project_root, session_id):
        return {"session-id": session_id, "state": "closed"}


def _start_host(tmp_path: Path, application: SharedApplication):
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


def _make_profile(project_root: Path) -> None:
    create_profile(project_root, {
        "profile_id": "default",
        "provider_id": "local-openai",
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
        submitted = first.submit_llm_request(tmp_path, prompt_body="hello", mode="async")
        observed = second.get_llm_request(tmp_path, submitted["request-id"])
        cancelled = second.cancel_llm_request(tmp_path, submitted["request-id"])

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
                "protocol-version": "gateway-service-v1",
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
                "protocol-version": "gateway-service-v1",
            },
        )["result"]
        response = _raw_post(
            host.endpoint,
            token,
            "/v1/call",
            {
                "protocol-version": "gateway-service-v1",
                "owner-epoch": lease["owner-epoch"],
                "lease-id": lease["lease-id"],
                "operation": "submit_llm_request",
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
            client.run_llm_request(tmp_path, prompt_body="slow")
        assert application.run_started.wait(timeout=3)
        application.run_release.set()
        assert application.run_completed.wait(timeout=3)
    finally:
        application.run_release.set()
        client.close()
        _stop_host(host, thread)


def test_real_gateway_work_survives_submitter_disconnect(tmp_path: Path, monkeypatch) -> None:
    _make_profile(tmp_path)
    gateway_api._QUEUE_MANAGER = agents_gateway_queue.GatewayQueueManager()
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
        "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn", slow_provider
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
        submitted = submitter.submit_llm_request(
            tmp_path, prompt_body="continue after disconnect", mode="async"
        )
        assert provider_started.wait(timeout=2)
        submitter.close()
        assert host.service_store.read().active_lease_count == 0

        provider_release.set()
        result = observer.wait_llm_request(
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

        assert token not in (service_root / "machine" / "agent-llm-gateway" / "default" / "service.json").read_text(encoding="utf-8")
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
    from audiagentic.components.agents.agents_gateway_service_host import GATEWAY_SERVICE_KEY

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
    from audiagentic.components.agents.agents_event_topics import GATEWAY_REQUESTED_TOPIC

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
                "from audiagentic.components.agents.agents_gateway_ingress import publish_gateway_trigger\n"
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
    from audiagentic.components.agents.agents_gateway_service_host import GATEWAY_SERVICE_KEY

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
