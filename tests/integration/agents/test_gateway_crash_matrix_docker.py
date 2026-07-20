"""SH07 production crash matrix: kill a REAL gateway service subprocess at
specific control-plane phases and prove recovery on restart.

Unlike tests/unit/agents/test_agents_gateway_work_index.py and
test_agents_gateway_recovery.py (in-process fault injection calling recovery
functions directly), this suite launches agents_gateway_service_process as an
actual OS process, submits real requests against a local rig HTTP server
(OpenAI-compatible, real network I/O through the local-openai adapter — no
mocked provider call), kills the process (SIGTERM then SIGKILL) at a phase
observed directly from the on-disk control-plane index, and restarts a fresh
service against the same service-root to prove recovery reaches the correct
terminal state. Opt-in Docker gate, mirroring test_gateway_opencode_docker.py.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.integration,
    pytest.mark.opt_in,
    pytest.mark.timeout(180),
]

_DOCKER_GATE_ENV = "AUDIAGENTIC_GATEWAY_CRASH_MATRIX_DOCKER"


def _require_docker_gate() -> None:
    if os.environ.get(_DOCKER_GATE_ENV) != "1":
        pytest.skip(f"opt-in Docker gate; set {_DOCKER_GATE_ENV}=1")


class _HoldableRigHandler(BaseHTTPRequestHandler):
    """Local OpenAI-compatible endpoint that blocks in-flight requests until
    released, so the test can observe a request sitting in a known phase
    (running / claimed) for as long as needed before deciding to kill the
    gateway process."""

    hold: threading.Event = threading.Event()
    request_count = 0
    lock = threading.Lock()

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        with _HoldableRigHandler.lock:
            _HoldableRigHandler.request_count += 1
        # Block here until released (or the whole process is killed out from
        # under this connection) — this is what keeps a real gateway attempt
        # sitting in "running" long enough to observe and kill against.
        _HoldableRigHandler.hold.wait(timeout=30)
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = json.dumps({
            "id": "chatcmpl-crash-matrix", "object": "chat.completion",
            "model": "audiagentic-rig",
            "choices": [{"message": {"role": "assistant", "content": "CRASH_MATRIX_OK"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def rig_server():
    _HoldableRigHandler.hold = threading.Event()
    _HoldableRigHandler.request_count = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HoldableRigHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        _HoldableRigHandler.hold.set()  # unblock anything still hanging
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _write_agent_profile(project_root: Path, *, max_concurrency: int) -> None:
    config_root = project_root / ".audiagentic" / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "agent-profiles.yaml").write_text(
        yaml.safe_dump(
            {
                "contract-version": "v1",
                "profiles": [{
                    "profile_id": "default",
                    "provider_id": "local-openai",
                    "model_id": "audiagentic-rig",
                    "params": {"retry-count": 0, "max-concurrency": max_concurrency, "stream": False},
                    "is_default": True,
                }],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _enable_local_openai(project_root: Path, rig_port: int) -> None:
    from audiagentic.components.providers.services.provider_config import (
        patch_provider_config,
        set_provider_enabled,
    )

    set_provider_enabled(project_root, "local-openai", enabled=True)
    patch_provider_config(
        project_root, "local-openai",
        {
            "install-mode": "external-configured",
            "access-mode": "none",
            "base-url": f"http://127.0.0.1:{rig_port}",
            # The local-openai adapter itself reads api-base-url (see
            # adapters/local_openai/adapter.py:_resolve_base_url); base-url
            # above satisfies the providers.yaml schema field of that name.
            "api-base-url": f"http://127.0.0.1:{rig_port}",
        },
    )


def _free_port() -> int:
    from audiagentic.foundation.system.process import choose_free_port

    return choose_free_port("127.0.0.1")


def _start_gateway_subprocess(service_root: Path, token_path: Path, port: int) -> subprocess.Popen:
    from audiagentic.components.agents.agents_gateway_remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    proc = subprocess.Popen(
        [
            sys.executable, "-m",
            "audiagentic.components.agents.agents_gateway_service_process",
            "--port", str(port),
            "--token-file", str(token_path),
            "--service-root", str(service_root),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    def _probe_ready() -> bool:
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            raise AssertionError(f"gateway subprocess exited early (code {proc.returncode}):\n{out}")
        if not token_path.is_file():
            return False
        client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
        try:
            return client.health().get("state") in {"starting", "running"}
        except Exception:
            return False
        finally:
            client.close()

    # A restart reuses the SAME token file, so its existence alone is not a
    # readiness signal — poll the real health endpoint on THIS port instead.
    _wait_for(_probe_ready, timeout=20, what="gateway subprocess ready")
    return proc


def _kill_subprocess(proc: subprocess.Popen) -> None:
    """Hard-kill the OS process so no in-flight Python cleanup code runs —
    this is a real crash, not a graceful shutdown."""
    try:
        if sys.platform == "win32":
            proc.kill()
        else:
            proc.send_signal(signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait(timeout=10)


def _wait_for(predicate, *, timeout: float, what: str, interval: float = 0.05) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {what}")


def _service_store_root(service_root: Path) -> Path:
    """GatewayServiceHost resolves ManagedServiceStore under service_root/
    machine/agent-llm-gateway/default — that nested path, not service_root
    itself, is what dispatch threads through as the work-index root."""
    return service_root / "machine" / "agent-llm-gateway" / "default"


def _index_entry_path(service_root: Path, request_id: str) -> Path:
    return _service_store_root(service_root) / "active-work" / f"{request_id}.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _wait_for_index_phase(service_root: Path, request_id: str, phase: str, *, timeout: float = 10) -> None:
    path = _index_entry_path(service_root, request_id)
    _wait_for(
        lambda: path.is_file() and _read_json(path).get("phase") == phase,
        timeout=timeout, what=f"work-index phase={phase} for {request_id}",
    )


def _read_record(project_root: Path, request_id: str) -> dict:
    from audiagentic.components.agents.agents_paths import gateway_request_path

    return _read_json(gateway_request_path(project_root, request_id))


def _wait_for_record_state(project_root: Path, request_id: str, states: set[str], *, timeout: float = 10) -> dict:
    box: dict = {}

    def _check() -> bool:
        record = _read_record(project_root, request_id)
        if record.get("state") in states:
            box["record"] = record
            return True
        return False

    _wait_for(_check, timeout=timeout, what=f"request {request_id} state in {states}")
    return box["record"]


def test_crash_while_admitted_but_unclaimed_recovers_as_replay_required(
    tmp_path: Path, rig_server
) -> None:
    """SH07 required scenario: crash after admission before claim. A second
    request queued behind a concurrency=1 slot stays phase=admitted with no
    dispatch owner — killing the service there must recover it as terminal
    interrupted + replay-required=true, never re-enqueued."""
    _require_docker_gate()
    from audiagentic.components.agents.agents_gateway_remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    rig_port = rig_server.server_address[1]
    _write_agent_profile(tmp_path, max_concurrency=1)
    _enable_local_openai(tmp_path, rig_port)

    service_root = tmp_path / "service-state"
    token_path = tmp_path / "gateway.token"
    port = _free_port()
    proc = _start_gateway_subprocess(service_root, token_path, port)
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    try:

        first = client.submit_llm_request(tmp_path, prompt_body="hold me", mode="async")
        second = client.submit_llm_request(tmp_path, prompt_body="stay queued", mode="async")

        # First occupies the sole concurrency slot (rig holds its response);
        # second must sit admitted-only, never claimed, while the slot is full.
        _wait_for_record_state(tmp_path, first["request-id"], {"running"})
        _wait_for_index_phase(service_root, second["request-id"], "admitted")
        second_record = _read_record(tmp_path, second["request-id"])
        assert second_record.get("dispatch-owner-epoch") is None

        _kill_subprocess(proc)
    finally:
        client.close()
        if proc.poll() is None:
            _kill_subprocess(proc)

    # Restart against the SAME service-root and let recovery run.
    token_path2 = tmp_path / "gateway.token"  # token persists across restarts
    port2 = _free_port()
    proc2 = _start_gateway_subprocess(service_root, token_path2, port2)
    client2 = StandaloneGatewayClient(f"http://127.0.0.1:{port2}", load_auth_token(token_path2))
    try:
        recovered = _wait_for_record_state(tmp_path, second["request-id"], {"interrupted"})
        assert recovered["replay-required"] is True
        assert recovered["error"]["code"] == "CON-AGW-102"
        # Never silently re-enqueued: no active dispatch owner, no queue re-entry.
        assert recovered.get("dispatch-owner-epoch") is None
    finally:
        client2.close()
        _HoldableRigHandler.hold.set()
        if proc2.poll() is None:
            proc2.terminate()
            try:
                proc2.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _kill_subprocess(proc2)


def test_crash_while_running_recovers_as_interrupted(tmp_path: Path, rig_server) -> None:
    """Crash after the attempt started (state=running, no attempt evidence
    appended yet since the rig is holding the response) must recover as
    terminal interrupted with the stale-owner error, never left running
    forever and never silently re-dispatched."""
    _require_docker_gate()
    from audiagentic.components.agents.agents_gateway_remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    rig_port = rig_server.server_address[1]
    _write_agent_profile(tmp_path, max_concurrency=1)
    _enable_local_openai(tmp_path, rig_port)

    service_root = tmp_path / "service-state"
    token_path = tmp_path / "gateway.token"
    port = _free_port()
    proc = _start_gateway_subprocess(service_root, token_path, port)
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    request_id = None
    try:
        submitted = client.submit_llm_request(tmp_path, prompt_body="hang here", mode="async")
        request_id = submitted["request-id"]

        _wait_for_record_state(tmp_path, request_id, {"running"})
        _wait_for_index_phase(service_root, request_id, "running")

        _kill_subprocess(proc)
    finally:
        client.close()
        if proc.poll() is None:
            _kill_subprocess(proc)

    port2 = _free_port()
    proc2 = _start_gateway_subprocess(service_root, token_path, port2)
    client2 = StandaloneGatewayClient(f"http://127.0.0.1:{port2}", load_auth_token(token_path))
    try:
        recovered = _wait_for_record_state(tmp_path, request_id, {"interrupted"})
        assert recovered["error"]["code"] == "CON-AGW-084"
        assert _HoldableRigHandler.request_count <= 1  # never double-dispatched
    finally:
        client2.close()
        _HoldableRigHandler.hold.set()
        if proc2.poll() is None:
            proc2.terminate()
            try:
                proc2.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _kill_subprocess(proc2)


def test_cancel_raced_with_recovery_reaches_consistent_terminal_state(
    tmp_path: Path, rig_server
) -> None:
    """A cancel sent while the process is about to die must not corrupt
    recovery: the restarted service still terminalizes the stale running
    request exactly once, and the cancel-requested flag survives."""
    _require_docker_gate()
    from audiagentic.components.agents.agents_gateway_remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    rig_port = rig_server.server_address[1]
    _write_agent_profile(tmp_path, max_concurrency=1)
    _enable_local_openai(tmp_path, rig_port)

    service_root = tmp_path / "service-state"
    token_path = tmp_path / "gateway.token"
    port = _free_port()
    proc = _start_gateway_subprocess(service_root, token_path, port)
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    request_id = None
    try:
        submitted = client.submit_llm_request(tmp_path, prompt_body="hang then cancel", mode="async")
        request_id = submitted["request-id"]
        _wait_for_record_state(tmp_path, request_id, {"running"})

        client.cancel_llm_request(tmp_path, request_id)
        _wait_for(
            lambda: _read_record(tmp_path, request_id).get("cancel-requested") is True,
            timeout=10, what="cancel-requested flag persisted",
        )

        _kill_subprocess(proc)
    finally:
        client.close()
        if proc.poll() is None:
            _kill_subprocess(proc)

    port2 = _free_port()
    proc2 = _start_gateway_subprocess(service_root, token_path, port2)
    client2 = StandaloneGatewayClient(f"http://127.0.0.1:{port2}", load_auth_token(token_path))
    try:
        recovered = _wait_for_record_state(tmp_path, request_id, {"interrupted"})
        assert recovered.get("cancel-requested") is True
        assert _HoldableRigHandler.request_count <= 1  # cancel race never caused a second dispatch
    finally:
        client2.close()
        _HoldableRigHandler.hold.set()
        if proc2.poll() is None:
            proc2.terminate()
            try:
                proc2.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _kill_subprocess(proc2)


def test_malformed_active_work_entry_is_quarantined_not_deleted_on_restart(
    tmp_path: Path, rig_server
) -> None:
    """A corrupted control-plane index entry sitting on disk when the service
    starts must be quarantined for forensic analysis, not silently deleted,
    and must not block recovery of a real, valid entry alongside it."""
    _require_docker_gate()
    from audiagentic.components.agents.agents_gateway_remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    rig_port = rig_server.server_address[1]
    _write_agent_profile(tmp_path, max_concurrency=1)
    _enable_local_openai(tmp_path, rig_port)

    service_root = tmp_path / "service-state"
    token_path = tmp_path / "gateway.token"
    port = _free_port()
    proc = _start_gateway_subprocess(service_root, token_path, port)
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    request_id = None
    try:
        submitted = client.submit_llm_request(tmp_path, prompt_body="hang", mode="async")
        request_id = submitted["request-id"]
        _wait_for_record_state(tmp_path, request_id, {"running"})
        _kill_subprocess(proc)
    finally:
        client.close()
        if proc.poll() is None:
            _kill_subprocess(proc)

    # Plant a corrupted index entry alongside the real one, directly on disk,
    # while the service is down.
    index_dir = _service_store_root(service_root) / "active-work"
    (index_dir / "req_tampered.json").write_text('{"request-id": "req_tampered"}', encoding="utf-8")

    port2 = _free_port()
    proc2 = _start_gateway_subprocess(service_root, token_path, port2)
    client2 = StandaloneGatewayClient(f"http://127.0.0.1:{port2}", load_auth_token(token_path))
    try:
        recovered = _wait_for_record_state(tmp_path, request_id, {"interrupted"})
        assert recovered["error"]["code"] == "CON-AGW-084"

        quarantine_dir = index_dir / "quarantine"
        _wait_for(
            lambda: any(quarantine_dir.glob("req_tampered_*.json")),
            timeout=10, what="tampered entry quarantined",
        )
        assert not (index_dir / "req_tampered.json").exists()
    finally:
        client2.close()
        _HoldableRigHandler.hold.set()
        if proc2.poll() is None:
            proc2.terminate()
            try:
                proc2.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _kill_subprocess(proc2)
