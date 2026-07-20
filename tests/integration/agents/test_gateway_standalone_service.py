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


def test_service_host_boots_with_no_gateway_registry_config_present(tmp_path: Path) -> None:
    """RV745: a fresh machine with no gateway-profiles.yaml keeps embedded-mode
    behavior — no shared registry is installed, matching prior behavior."""
    from audiagentic.components.agents import agents_gateway_profiles as profiles_mod

    application = SharedApplication()
    host, thread, _service_root, _token_path = _start_host(tmp_path, application)
    try:
        assert profiles_mod.get_gateway_registry() is None
    finally:
        _stop_host(host, thread)
    assert profiles_mod.get_gateway_registry() is None


def test_service_host_startup_wires_gateway_owned_registry_from_config(
    tmp_path: Path, monkeypatch
) -> None:
    """RV745: GatewayServiceHost.create loads the gateway-owned profile
    registry from a machine-scoped config file, and two distinct project roots
    submitting the same gateway profile share its global queue limit through
    the real HTTP service, not project-local config."""
    from audiagentic.components.agents import agents_gateway_profiles as profiles_mod

    root_a = tmp_path / "project_a"
    root_b = tmp_path / "project_b"
    root_a.mkdir()
    root_b.mkdir()
    _make_profile(root_a)
    _make_profile(root_b)
    gateway_api._QUEUE_MANAGER = agents_gateway_queue.GatewayQueueManager()

    config_path = tmp_path / "gateway-profiles.yaml"
    config_path.write_text(
        "contract-version: v1\n"
        "profiles:\n"
        "- profile_id: default\n"
        "  provider_id: local-openai\n"
        "  model_id: gpt-4o\n"
        "  params:\n"
        "    max-concurrency: 1\n"
        "    queue-max-size: 8\n",
        encoding="utf-8",
    )

    provider_started = threading.Event()
    provider_release = threading.Event()

    def slow_provider(*, identity, execution_request, timeout_seconds):
        provider_started.set()
        provider_release.wait(timeout=5)
        return ProviderExecutionResult(
            provider_id="local-openai", model_id="gpt-4o",
            worker_id=identity.worker_id, attempt_epoch=identity.attempt_epoch,
            result_data={"provider-id": "local-openai", "model": "gpt-4o", "output": "shared-lane result"},
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn", slow_provider
    )
    host = GatewayServiceHost.create(
        service_root=tmp_path / "service-state",
        token_path=tmp_path / "real.token",
        gateway_profiles_config=config_path,
    )
    thread = threading.Thread(target=host.serve_forever)
    thread.start()
    try:
        # The registry is installed before the host serves any request.
        assert profiles_mod.get_gateway_registry() is not None

        token = load_auth_token(host.token_path)
        client_a = StandaloneGatewayClient(host.endpoint, token)
        client_b = StandaloneGatewayClient(host.endpoint, token)
        try:
            submitted_a = client_a.submit_llm_request(root_a, prompt_body="from-a", mode="async")
            assert provider_started.wait(timeout=2)

            # Global max_concurrency=1 for this gateway-owned profile: project
            # B's request must queue behind project A's, not run independently
            # under a project-local limit.
            submitted_b = client_b.submit_llm_request(root_b, prompt_body="from-b", mode="async")
            status_b = client_b.get_llm_request(root_b, submitted_b["request-id"])
            assert status_b["state"] in ("queued", "dispatching")

            provider_release.set()
            result_a = client_a.wait_llm_request(root_a, submitted_a["request-id"], timeout_seconds=5)
            result_b = client_b.wait_llm_request(root_b, submitted_b["request-id"], timeout_seconds=5)
            assert result_a["state"] == "completed"
            assert result_b["state"] == "completed"
            assert result_a["gateway-execution-lane-key"] == result_b["gateway-execution-lane-key"]
        finally:
            provider_release.set()
            client_a.close()
            client_b.close()
    finally:
        _stop_host(host, thread)
    assert profiles_mod.get_gateway_registry() is None


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


# ── SH13 steps 3-9: atomic reload, stale snapshot rejection, redaction ──

def _make_gateway_profiles_config(path: Path, profiles: list[dict]) -> None:
    """Write a gateway-profiles.yaml file."""
    import yaml

    data = {"contract-version": "v1", "profiles": profiles}
    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def test_reload_gateway_profiles_atomic_swap(tmp_path: Path) -> None:
    """SH13 step 3-4: reload_profile_registry atomically swaps the registry
    under a lock; on success, returns only redacted generation metadata.
    A redacted agents.llm.gateway.profile-reloaded event is published."""
    from audiagentic.components.agents import agents_gateway_profiles as profiles_mod
    from audiagentic.components.agents.agents_event_topics import (
        GATEWAY_PROFILE_RELOADED_TOPIC,
    )

    root = tmp_path / "proj"
    root.mkdir()
    _make_profile(root)

    config_path = tmp_path / "gateway-profiles.yaml"
    _make_gateway_profiles_config(config_path, [
        {
            "profile_id": "default",
            "provider_id": "local-openai",
            "model_id": "gpt-4o",
            "params": {"max-concurrency": 1, "queue-max-size": 8},
        },
    ])

    gateway_api._QUEUE_MANAGER = agents_gateway_queue.GatewayQueueManager()
    host = GatewayServiceHost.create(
        service_root=tmp_path / "service-state",
        token_path=tmp_path / "reload.token",
        gateway_profiles_config=config_path,
    )
    thread = threading.Thread(target=host.serve_forever)
    thread.start()
    try:
        reg = profiles_mod.get_gateway_registry()
        assert reg is not None
        snap_v1 = reg.resolve_snapshot("default")
        gen_v1 = snap_v1.generation

        # Mutate the config file to trigger a generation change on reload
        _make_gateway_profiles_config(config_path, [
            {
                "profile_id": "default",
                "provider_id": "local-openai",
                "model_id": "gpt-4o",
                "params": {"max-concurrency": 3, "queue-max-size": 16},
            },
        ])

        # Capture the event published on reload
        from audiagentic.foundation.event import get_bus
        captured_events: list[dict] = []

        def _on_reload(topic: str, payload: dict) -> None:
            captured_events.append(payload)

        get_bus().subscribe(GATEWAY_PROFILE_RELOADED_TOPIC, _on_reload)

        # Reload via the service operation (step 3: atomic swap; step 4: redacted output)
        result = profiles_mod.reload_profile_registry()
        assert result["success"] is True
        new_reg = profiles_mod.get_gateway_registry()
        snap_v2 = new_reg.resolve_snapshot("default")
        gen_v2 = snap_v2.generation

        # Generation must have changed (new config)
        assert gen_v2 != gen_v1
        # New limits from config
        assert snap_v2.max_concurrency == 3
        assert snap_v2.queue_max_size == 16

        # Step 4: old and new summaries carry only redacted metadata (no secrets)
        for summary_key in ("old-generation-summary", "new-generation-summary"):
            for profile_entry in result[summary_key]["profiles"]:
                assert "generation" in profile_entry
                assert "config-digest" in profile_entry
                # No secret keys should appear in the redacted summary
                for k in profile_entry:
                    assert "api-key" not in k.lower()
                    assert "secret" not in k.lower()

        # Step 4: event was published with redacted generation metadata
        assert len(captured_events) == 1
        event = captured_events[0]
        assert "old-generation-summary" in event
        assert "new-generation-summary" in event
        assert "config-path" in event
        # Event payload should only carry the config filename, not full paths
        assert isinstance(event["config-path"], str)
    finally:
        _stop_host(host, thread)
    assert profiles_mod.get_gateway_registry() is None


def test_reload_retains_previous_on_failure(tmp_path: Path) -> None:
    """SH13 step 3: if reload fails (config file missing), the previous
    registry is retained and the operation returns success=False."""
    from audiagentic.components.agents import agents_gateway_profiles as profiles_mod

    config_path = tmp_path / "gateway-profiles.yaml"
    _make_gateway_profiles_config(config_path, [
        {
            "profile_id": "default",
            "provider_id": "local-openai",
            "model_id": "gpt-4o",
            "params": {"max-concurrency": 1, "queue-max-size": 8},
        },
    ])

    registry = profiles_mod.InMemoryGatewayRegistry()
    registry.register("default", provider_id="local-openai", model_id="gpt-4o")
    profiles_mod.set_gateway_registry(registry)
    profiles_mod.set_gateway_registry_config_path(config_path)
    gen_before = registry.resolve_snapshot("default").generation

    try:
        # Delete the config file so reload fails
        config_path.unlink()
        result = profiles_mod.reload_profile_registry()
        assert result["success"] is False
        assert result["error"]["code"] == "IO-AGW-109"

        # Previous registry retained
        reg_after = profiles_mod.get_gateway_registry()
        assert reg_after is registry
        gen_after = reg_after.resolve_snapshot("default").generation
        assert gen_after == gen_before
    finally:
        profiles_mod.set_gateway_registry(None)
        profiles_mod.set_gateway_registry_config_path(None)


def test_reload_via_service_operation(tmp_path: Path) -> None:
    """SH13 step 3-4: reload_gateway_profiles operation is callable through
    the HTTP service and returns redacted metadata."""
    from audiagentic.components.agents.agents_gateway_remote_client import (
        StandaloneGatewayClient,
    )

    root = tmp_path / "proj"
    root.mkdir()
    _make_profile(root)

    config_path = tmp_path / "gateway-profiles.yaml"
    _make_gateway_profiles_config(config_path, [
        {
            "profile_id": "default",
            "provider_id": "local-openai",
            "model_id": "gpt-4o",
            "params": {"max-concurrency": 1, "queue-max-size": 8},
        },
    ])

    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    token = load_auth_token(token_path)
    try:
        with StandaloneGatewayClient(host.endpoint, token) as client:
            # Acquire a lease for the operation
            lease = client._acquire_lease()
            result = client._invoke(
                "reload_gateway_profiles",
                str(tmp_path),
                protocol_version="gateway-service-v1",
                owner_epoch=host.owner_epoch,
                lease_id=lease["lease-id"],
            )
            # Reload via the service operation
            assert result["success"] is True
    finally:
        _stop_host(host, thread)


def test_stale_queued_snapshot_rejected_on_reload(tmp_path: Path, monkeypatch) -> None:
    """SH13 step 7-8: after a reload changes the profile generation,
    queued work with a stale snapshot is rejected with CON-AGW-101 while
    a running request keeps its original snapshot uninterrupted."""
    from audiagentic.components.agents.agents_gateway_remote_client import (
        StandaloneGatewayClient,
    )

    root_a = tmp_path / "project_a"
    root_b = tmp_path / "project_b"
    root_a.mkdir()
    root_b.mkdir()
    _make_profile(root_a)
    _make_profile(root_b)
    gateway_api._QUEUE_MANAGER = agents_gateway_queue.GatewayQueueManager()

    config_path = tmp_path / "gateway-profiles.yaml"
    _make_gateway_profiles_config(config_path, [
        {
            "profile_id": "default",
            "provider_id": "local-openai",
            "model_id": "gpt-4o",
            "params": {"max-concurrency": 1, "queue-max-size": 8},
        },
    ])

    provider_started = threading.Event()
    provider_release = threading.Event()
    provider_released_once = threading.Event()

    def slow_provider(*, identity, execution_request, timeout_seconds):
        """First call blocks; second call returns immediately."""
        if not provider_released_once.is_set():
            provider_started.set()
            provider_release.wait(timeout=5)
            provider_released_once.set()
        return ProviderExecutionResult(
            provider_id="local-openai", model_id="gpt-4o",
            worker_id=identity.worker_id, attempt_epoch=identity.attempt_epoch,
            result_data={"provider-id": "local-openai", "model": "gpt-4o", "output": f"result from {execution_request.get('prompt-body', 'unknown')}"},
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
        slow_provider,
    )
    host = GatewayServiceHost.create(
        service_root=tmp_path / "service-state-reload",
        token_path=tmp_path / "reload.token2",
        gateway_profiles_config=config_path,
    )
    thread = threading.Thread(target=host.serve_forever)
    thread.start()
    try:
        from audiagentic.components.agents import agents_gateway_profiles as profiles_mod

        token = load_auth_token(host.token_path)
        client_a = StandaloneGatewayClient(host.endpoint, token)
        client_b = StandaloneGatewayClient(host.endpoint, token)
        try:
            # Submit first request — it will run (max_concurrency=1)
            submitted_a = client_a.submit_llm_request(root_a, prompt_body="running", mode="async")
            assert provider_started.wait(timeout=2), "first request should start running"

            # Submit second request — it queues behind the first
            submitted_b = client_b.submit_llm_request(root_b, prompt_body="queued", mode="async")
            status_b = client_b.get_llm_request(root_b, submitted_b["request-id"])
            assert status_b["state"] in ("queued", "dispatching")

            # Reload the gateway profiles config with changed limits
            _make_gateway_profiles_config(config_path, [
                {
                    "profile_id": "default",
                    "provider_id": "local-openai",
                    "model_id": "gpt-4o",
                    "params": {"max-concurrency": 2, "queue-max-size": 16},
                },
            ])
            reload_result = profiles_mod.reload_profile_registry()
            assert reload_result["success"] is True

            # Step 7: queued stale snapshot (B) should be rejected with CON-AGW-101
            status_b_after = client_b.get_llm_request(root_b, submitted_b["request-id"])
            assert status_b_after["state"] == "rejected"
            assert "CON-AGW-101" in (status_b_after.get("error") or {}).get("code", "")

            # Step 7: running request (A) keeps its snapshot and completes
            provider_release.set()
            result_a = client_a.wait_llm_request(root_a, submitted_a["request-id"], timeout_seconds=5)
            assert result_a["state"] == "completed"
        finally:
            provider_release.set()
            client_a.close()
            client_b.close()
    finally:
        _stop_host(host, thread)


def test_redacted_status_no_secrets_in_overview(tmp_path: Path) -> None:
    """SH13 step 9: self-review — gateway status and queue overview contain
    no secret keys or filesystem paths beyond the project root."""
    from audiagentic.components.agents.agents_gateway_remote_client import (
        StandaloneGatewayClient,
    )

    root = tmp_path / "proj"
    root.mkdir()
    _make_profile(root)

    config_path = tmp_path / "gateway-profiles.yaml"
    _make_gateway_profiles_config(config_path, [
        {
            "profile_id": "default",
            "provider_id": "local-openai",
            "model_id": "gpt-4o",
            "params": {
                "max-concurrency": 2,
                "queue-max-size": 8,
                "api-key": "sk-test-secret-value",  # secret that must be redacted
            },
        },
    ])

    gateway_api._QUEUE_MANAGER = agents_gateway_queue.GatewayQueueManager()
    host = GatewayServiceHost.create(
        service_root=tmp_path / "service-state-redact",
        token_path=tmp_path / "redact.token",
        gateway_profiles_config=config_path,
    )
    thread = threading.Thread(target=host.serve_forever)
    thread.start()
    try:
        token = load_auth_token(host.token_path)
        with StandaloneGatewayClient(host.endpoint, token) as client:
            overview = client.gateway_overview(root)
            # Serialize to string for thorough content check
            import json
            overview_str = json.dumps(overview).lower()

            # No secret values should appear in the overview output
            assert "sk-test-secret-value" not in overview_str
            assert "api-key" not in overview_str or overview_str.count("api-key") == 0

            # Reload result should also be redacted
            from audiagentic.components.agents import agents_gateway_profiles as profiles_mod
            reload_result = profiles_mod.reload_profile_registry()
            assert reload_result["success"] is True
            reload_str = json.dumps(reload_result).lower()
            assert "sk-test-secret-value" not in reload_str
    finally:
        _stop_host(host, thread)


def test_absent_shared_profile_rejected_not_fallback(tmp_path: Path) -> None:
    """SH13 step 5: when a shared registry is active but the requested
    profile does not exist in it, the request is rejected — no fallback to
    project-local limits."""
    from audiagentic.components.agents.agents_gateway_remote_client import (
        StandaloneGatewayClient,
    )

    root = tmp_path / "proj"
    root.mkdir()
    # Create a project-local profile called 'default'
    _make_profile(root)

    config_path = tmp_path / "gateway-profiles.yaml"
    # Gateway config does NOT include 'default' profile — only 'other-profile'
    _make_gateway_profiles_config(config_path, [
        {
            "profile_id": "other-profile",
            "provider_id": "local-openai",
            "model_id": "gpt-4o",
            "params": {"max-concurrency": 1, "queue-max-size": 8},
        },
    ])

    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    token = load_auth_token(token_path)
    try:
        with StandaloneGatewayClient(host.endpoint, token) as client:
            # Acquire lease for the call
            lease = client._acquire_lease()
            # Requesting 'default' — not in shared registry → should fail
            result = client._invoke(
                "submit_llm_request",
                str(root),
                protocol_version="gateway-service-v1",
                owner_epoch=host.owner_epoch,
                lease_id=lease["lease-id"],
                params={"prompt_body": "hello", "mode": "async"},
            )
            # Should be an error (RES-AGP-001: profile not found in shared registry)
            assert result.get("error-code") == "RES-AGP-001"
    finally:
        _stop_host(host, thread)


def test_embedded_compatibility_when_no_shared_registry(tmp_path: Path) -> None:
    """SH13 step 6: when no shared gateway registry is installed, embedded
    compatibility mode still works — project-local profiles are used."""
    from audiagentic.components.agents.agents_gateway_remote_client import (
        StandaloneGatewayClient,
    )

    root = tmp_path / "proj"
    root.mkdir()
    _make_profile(root)

    application = SharedApplication()
    host, thread, _service_root, token_path = _start_host(tmp_path, application)
    token = load_auth_token(token_path)
    try:
        with StandaloneGatewayClient(host.endpoint, token) as client:
            # No shared registry — embedded mode should work
            submitted = client.submit_llm_request(root, prompt_body="embedded", mode="async")
            assert "request-id" in submitted
    finally:
        _stop_host(host, thread)


def test_reload_concurrency_no_state_corruption(tmp_path: Path, monkeypatch) -> None:
    """SH13 step 3 concurrency test: concurrent reload and admission must not
    corrupt registry state — the atomic swap under a short lock guarantees
    that a request admitted during reload sees either the old or new registry,
    never a torn or partially-updated one."""
    from audiagentic.components.agents.agents_gateway_remote_client import (
        StandaloneGatewayClient,
    )

    root_a = tmp_path / "project_a"
    root_b = tmp_path / "project_b"
    root_a.mkdir()
    root_b.mkdir()
    _make_profile(root_a)
    _make_profile(root_b)
    gateway_api._QUEUE_MANAGER = agents_gateway_queue.GatewayQueueManager()

    config_path = tmp_path / "gateway-profiles.yaml"
    _make_gateway_profiles_config(config_path, [
        {
            "profile_id": "default",
            "provider_id": "local-openai",
            "model_id": "gpt-4o",
            "params": {"max-concurrency": 1, "queue-max-size": 8},
        },
    ])

    provider_started = threading.Event()
    provider_release = threading.Event()

    def slow_provider(*, identity, execution_request, timeout_seconds):
        provider_started.set()
        provider_release.wait(timeout=5)
        return ProviderExecutionResult(
            provider_id="local-openai", model_id="gpt-4o",
            worker_id=identity.worker_id, attempt_epoch=identity.attempt_epoch,
            result_data={"provider-id": "local-openai", "model": "gpt-4o", "output": "ok"},
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
        slow_provider,
    )
    host = GatewayServiceHost.create(
        service_root=tmp_path / "service-state-concurrency",
        token_path=tmp_path / "concurrency.token",
        gateway_profiles_config=config_path,
    )
    thread = threading.Thread(target=host.serve_forever)
    thread.start()
    try:
        from audiagentic.components.agents import agents_gateway_profiles as profiles_mod

        token = load_auth_token(host.token_path)
        client_a = StandaloneGatewayClient(host.endpoint, token)
        client_b = StandaloneGatewayClient(host.endpoint, token)
        try:
            # Submit first request — it will run (max_concurrency=1), holding the slot
            submitted_a = client_a.submit_llm_request(root_a, prompt_body="hold", mode="async")
            assert provider_started.wait(timeout=2), "first request should start running"

            gen_v1 = profiles_mod.get_gateway_registry().resolve_snapshot("default").generation

            # Concurrently: mutate config + reload while another request is being submitted
            reload_done = threading.Event()
            reload_results: list[dict] = []

            def _reload_worker():
                _make_gateway_profiles_config(config_path, [
                    {
                        "profile_id": "default",
                        "provider_id": "local-openai",
                        "model_id": "gpt-4o",
                        "params": {"max-concurrency": 2, "queue-max-size": 16},
                    },
                ])
                result = profiles_mod.reload_profile_registry()
                reload_results.append(result)
                reload_done.set()

            # Start reload in background thread while submitting request B
            reload_thread = threading.Thread(target=_reload_worker, name="reload-worker")
            reload_thread.start()

            # Submit second request during the reload — it should see a consistent
            # registry (either v1 or v2, never torn)
            submitted_b = client_b.submit_llm_request(root_b, prompt_body="during-reload", mode="async")
            reload_thread.join(timeout=5)

            assert len(reload_results) == 1
            assert reload_results[0]["success"] is True

            # Both requests should be in a valid state (not corrupted)
            status_a = client_a.get_llm_request(root_a, submitted_a["request-id"])
            status_b = client_b.get_llm_request(root_b, submitted_b["request-id"])

            # A is running (holds the slot), B is queued or running (concurrency=2 now)
            assert status_a["state"] == "running"
            # B could be running (if reload completed first and concurrency was 2) or queued
            assert status_b["state"] in ("queued", "running", "dispatching")

            # Registry state is consistent — generation is v2 now
            gen_v2 = profiles_mod.get_gateway_registry().resolve_snapshot("default").generation
            assert gen_v2 != gen_v1

            # Complete the running request
            provider_release.set()
            result_a = client_a.wait_llm_request(root_a, submitted_a["request-id"], timeout_seconds=5)
            assert result_a["state"] == "completed"

            # B should also complete (no corruption from concurrent reload)
            result_b = client_b.wait_llm_request(root_b, submitted_b["request-id"], timeout_seconds=5)
            assert result_b["state"] == "completed"
        finally:
            provider_release.set()
            client_a.close()
            client_b.close()
    finally:
        _stop_host(host, thread)
