"""Shared real-provisioning + subprocess-lifecycle helpers for gateway Docker
recipes (crash-matrix, opencode, concurrency).

Modeled directly on tests/integration/providers/harness.py: every helper here
calls AUDiaGentic's own real API (execution-profile creation, provider CLI install,
provider config) instead of hand-writing YAML or assuming host state — the
whole point of these Docker recipes is that they prove the real provisioning
path works, not that a config file with the right shape happens to exist.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tests.integration.providers.harness import (
    assert_health_ok,
    assert_install_result_ok,
    install_provider,
    provider_ids,
)

from audiagentic.components.agents.models.execution_profile_api import (
    create_execution_profile,
)

# ---------------------------------------------------------------------------
# Dynamic provider discovery — never a hardcoded provider list. Mirrors
# tests/integration/providers/harness.py's provider_ids() and
# test_provider_lsp_e2e.py's NATIVE_LSP_PROVIDERS: query AUDiaGentic's own
# descriptor/automation registry for what's actually configured, so this
# suite automatically covers new providers as they gain the relevant
# capability instead of needing a manual list update.
# ---------------------------------------------------------------------------


def npm_installable_provider_ids() -> list[str]:
    """CLI-installable providers whose package manager is npm — the only
    package manager the gateway Docker images provision (base image has
    node/npm; other package managers like brew/vscode/gh-extension are out
    of scope for these images)."""
    return provider_ids(package_manager="npm")


def model_projection_capable_provider_ids() -> list[str]:
    """Providers that declare the "model-projection" automation capability —
    the real, authoritative signal (not a guess) that a provider can accept
    a custom model-source entry, per providers_api.apply_model_sources'
    own selection logic (descriptor.automation_capability("model-projection"))."""
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    return sorted(
        provider_id
        for provider_id, descriptor in all_descriptors().items()
        if descriptor.automation_capability("model-projection") is not None
    )


def gateway_rig_compatible_npm_provider_ids() -> list[str]:
    """Providers this suite can dynamically provision + dispatch through: CLI
    (npm) installable AND model-projection capable (so a local-rig model
    source can actually be routed to them, the same real check
    apply_model_sources performs)."""
    projectable = set(model_projection_capable_provider_ids())
    return [pid for pid in npm_installable_provider_ids() if pid in projectable]


# ---------------------------------------------------------------------------
# Real provisioning — execution profiles, provider config, provider CLI install
# ---------------------------------------------------------------------------


def write_execution_profile(
    project_root: Path,
    *,
    profile_id: str = "default",
    provider_id: str,
    model_id: str,
    virtual_capacity: int = 1,
    pending_capacity: int | None = None,
    retry_count: int = 0,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a project-local execution profile through the real profile API.

    Replaces hand-written split profile files: create_execution_profile validates and
    persists through the same path a real caller would use, so a schema
    drift or validation bug in profile creation is exercised, not bypassed.
    """
    params: dict[str, Any] = {"retry-count": retry_count, "virtual-capacity": virtual_capacity}
    if pending_capacity is not None:
        params["pending-capacity"] = pending_capacity
    if extra_params:
        params.update(extra_params)
    return create_execution_profile(
        project_root,
        {
            "profile_id": profile_id,
            "provider_id": provider_id,
            "model_id": model_id,
            # These gateway-concurrency scenarios intentionally exercise the
            # profile's virtual capacity.  Use a plain instance id so the
            # test does not accidentally inherit capacity from a project or
            # user model-sources declaration.
            "instances": [model_id],
            "is_default": True,
            "params": params,
        },
    )


def enable_local_openai(project_root: Path, rig_port: int) -> None:
    """Real config-only provisioning for local-openai.

    local-openai has no installable CLI (access-mode="none" in its
    descriptor) — there is nothing for install_provider_cli to do here, so
    direct config patching is the real provisioning path for this provider,
    not a shortcut around one.
    """
    from audiagentic.components.providers.services.config.provider_config import (
        patch_provider_config,
        set_provider_enabled,
    )

    set_provider_enabled(project_root, "local-openai", enabled=True)
    patch_provider_config(
        project_root,
        "local-openai",
        {
            "install-mode": "external-configured",
            "access-mode": "none",
            "base-url": f"http://127.0.0.1:{rig_port}",
            "api-base-url": f"http://127.0.0.1:{rig_port}",
        },
    )


def provision_opencode(project_root: Path) -> dict[str, Any]:
    """Real npm-based opencode CLI install, through the same
    install_provider_cli path tests/integration/providers/harness.py uses
    for its clean-room recipe tests.

    install_provider_cli(project_root=...) already seeds the project's
    provider config as enabled on success (services/lifecycle.py), so no
    separate set_provider_enabled call is needed after this.
    """
    result = install_provider("opencode", project_root=project_root)
    assert_install_result_ok("opencode", result)
    assert_health_ok("opencode", result)
    return result


# ---------------------------------------------------------------------------
# Holdable local rig — OpenAI-compatible endpoint with controllable release,
# used to force real concurrent overlap and to observe a request sitting in
# a known phase for as long as needed.
# ---------------------------------------------------------------------------


class HoldableRigHandler(BaseHTTPRequestHandler):
    """Local OpenAI-compatible endpoint that blocks in-flight requests until
    released. Tracks concurrent in-flight requests so tests can assert real
    overlap was observed, not just that N requests eventually completed."""

    hold: threading.Event = threading.Event()
    request_count = 0
    active_count = 0
    peak_active_count = 0
    lock = threading.Lock()

    def log_message(self, format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        cls = HoldableRigHandler
        with cls.lock:
            cls.request_count += 1
            cls.active_count += 1
            cls.peak_active_count = max(cls.peak_active_count, cls.active_count)
        try:
            # Blocks here until released (or killed out from under this
            # connection) — this is what lets a test force real overlap
            # between requests, or observe a request sitting "running" long
            # enough to act on before releasing it.
            cls.hold.wait(timeout=30)
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            body = json.dumps(
                {
                    "id": "chatcmpl-gateway-docker",
                    "object": "chat.completion",
                    "model": "audiagentic-rig",
                    "choices": [{"message": {"role": "assistant", "content": "RIG_OK"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            with cls.lock:
                cls.active_count -= 1

    @classmethod
    def reset(cls) -> None:
        cls.hold = threading.Event()
        cls.request_count = 0
        cls.active_count = 0
        cls.peak_active_count = 0


def start_rig_server(*, port: int = 0) -> ThreadingHTTPServer:
    HoldableRigHandler.reset()
    server = ThreadingHTTPServer(("127.0.0.1", port), HoldableRigHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server._agw_thread = thread  # type: ignore[attr-defined]
    return server


def stop_rig_server(server: ThreadingHTTPServer) -> None:
    HoldableRigHandler.hold.set()  # unblock anything still hanging
    server.shutdown()
    thread = getattr(server, "_agw_thread", None)
    if thread is not None:
        thread.join(timeout=5)
    server.server_close()


# ---------------------------------------------------------------------------
# Real gateway service subprocess lifecycle
# ---------------------------------------------------------------------------


def free_port() -> int:
    from audiagentic.foundation.system.process import choose_free_port

    return choose_free_port("127.0.0.1")


def start_gateway_subprocess(
    service_root: Path,
    token_path: Path,
    port: int,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen:
    """Launch the real gateway service as an OS subprocess.

    extra_env merges on top of the current environment (never replaces it) —
    used by crash-matrix scenarios that need a test-only stall hook (SH07
    claim-to-start / terminal-to-cleanup windows) active in the child process
    only, never on the host test runner itself.
    """
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    command = [
        sys.executable,
        "-m",
        "audiagentic.components.agents.gateway.service.process",
        "--port",
        str(port),
        "--token-file",
        str(token_path),
        "--service-root",
        str(service_root),
    ]
    env = None
    if extra_env:
        import os as _os

        env = {**_os.environ, **extra_env}
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    captured_output: list[str] = []
    proc._ag_captured_output = captured_output  # type: ignore[attr-defined]

    def _capture_output() -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            captured_output.append(line.rstrip())

    threading.Thread(target=_capture_output, daemon=True).start()

    def _probe_ready() -> bool:
        if proc.poll() is not None:
            out = "\n".join(captured_output)
            raise AssertionError(
                f"gateway subprocess exited early (code {proc.returncode}):\n{out}"
            )
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
    wait_for(_probe_ready, timeout=20, what="gateway subprocess ready")
    return proc


def kill_subprocess(proc: subprocess.Popen) -> None:
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


def stop_subprocess_gracefully(proc: subprocess.Popen, *, timeout: float = 10) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_subprocess(proc)


def wait_for(predicate, *, timeout: float, what: str, interval: float = 0.05) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {what}")


def service_store_root(service_root: Path) -> Path:
    """GatewayServiceHost resolves ManagedServiceStore under service_root/
    machine/agent-execution-gateway/default — that nested path, not service_root
    itself, is what dispatch threads through as the work-index root."""
    return service_root / "machine" / "agent-execution-gateway" / "default"


def index_entry_path(service_root: Path, request_id: str) -> Path:
    return service_store_root(service_root) / "active-work" / f"{request_id}.json"


def active_work_entry_path(service_root: Path, request_id: str) -> Path:
    """Path 1 active-work entry (SHA-256(request_id)-hashed filename), distinct
    from the Path 2 work-index entry (index_entry_path, req_<id>.json). Both
    live in the same active-work/ directory but with non-colliding name
    schemes — see agents_gateway_store/_admission.py record_active_work and
    agents_gateway_work_index.py write_work_index_entry."""
    import hashlib

    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return service_store_root(service_root) / "active-work" / f"{digest}.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def wait_for_index_phase(
    service_root: Path, request_id: str, phase: str, *, timeout: float = 10
) -> None:
    path = index_entry_path(service_root, request_id)
    wait_for(
        lambda: path.is_file() and read_json(path).get("phase") == phase,
        timeout=timeout,
        what=f"work-index phase={phase} for {request_id}",
    )


def read_record(project_root: Path, request_id: str) -> dict:
    from audiagentic.components.agents.agents_paths import gateway_request_path

    return read_json(gateway_request_path(project_root, request_id))


def wait_for_record_state(
    project_root: Path, request_id: str, states: set[str], *, timeout: float = 10
) -> dict:
    box: dict = {}

    def _check() -> bool:
        record = read_record(project_root, request_id)
        if record.get("state") in states:
            box["record"] = record
            return True
        return False

    wait_for(_check, timeout=timeout, what=f"request {request_id} state in {states}")
    return box["record"]
