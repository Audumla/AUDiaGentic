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

Provisioning goes through gateway_docker_harness.py, which wraps AUDiaGentic's
real execution-profile/provider-config APIs — no hand-written config files.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from tests.integration.agents.gateway_docker_harness import (
    HoldableRigHandler as _HoldableRigHandler,
)
from tests.integration.agents.gateway_docker_harness import (
    active_work_entry_path,
    enable_local_openai,
    free_port,
    index_entry_path,
    kill_subprocess,
    service_store_root,
    start_gateway_subprocess,
    start_rig_server,
    stop_rig_server,
    stop_subprocess_gracefully,
    wait_for,
    wait_for_index_phase,
    wait_for_record_state,
    write_execution_profile,
)
from tests.integration.agents.gateway_docker_harness import read_record as _read_record

pytestmark = [
    pytest.mark.integration,
    pytest.mark.opt_in,
    pytest.mark.requires_container,
    pytest.mark.timeout(180),
]

_DOCKER_GATE_ENV = "AUDIAGENTIC_GATEWAY_CRASH_MATRIX_DOCKER"


def _require_docker_gate() -> None:
    if os.environ.get(_DOCKER_GATE_ENV) != "1":
        pytest.skip(f"opt-in Docker gate; set {_DOCKER_GATE_ENV}=1")


@pytest.fixture()
def rig_server():
    server = start_rig_server()
    try:
        yield server
    finally:
        stop_rig_server(server)


def test_crash_while_admitted_but_unclaimed_recovers_as_replay_required(
    tmp_path: Path, rig_server
) -> None:
    """SH07 required scenario: crash after admission before claim. A second
    request queued behind a concurrency=1 slot stays phase=admitted with no
    dispatch owner — killing the service there must recover it as terminal
    interrupted + replay-required=true, never re-enqueued."""
    _require_docker_gate()
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    rig_port = rig_server.server_address[1]
    write_execution_profile(tmp_path, provider_id="local-openai", model_id="audiagentic-rig", max_concurrency=1)
    enable_local_openai(tmp_path, rig_port)

    service_root = tmp_path / "service-state"
    token_path = tmp_path / "gateway.token"
    port = free_port()
    proc = start_gateway_subprocess(service_root, token_path, port)
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    try:

        first = client.submit_execution_request(tmp_path, prompt_body="hold me", mode="async")
        second = client.submit_execution_request(tmp_path, prompt_body="stay queued", mode="async")

        # First occupies the sole concurrency slot (rig holds its response);
        # second must sit admitted-only, never claimed, while the slot is full.
        wait_for_record_state(tmp_path, first["request-id"], {"running"})
        wait_for_index_phase(service_root, second["request-id"], "admitted")
        second_record = _read_record(tmp_path, second["request-id"])
        assert second_record.get("dispatch-owner-epoch") is None

        kill_subprocess(proc)
    finally:
        client.close()
        if proc.poll() is None:
            kill_subprocess(proc)

    # Restart against the SAME service-root and let recovery run.
    token_path2 = tmp_path / "gateway.token"  # token persists across restarts
    port2 = free_port()
    proc2 = start_gateway_subprocess(service_root, token_path2, port2)
    client2 = StandaloneGatewayClient(f"http://127.0.0.1:{port2}", load_auth_token(token_path2))
    try:
        recovered = wait_for_record_state(tmp_path, second["request-id"], {"interrupted"})
        assert recovered["replay-required"] is True
        assert recovered["error"]["code"] == "CON-AGW-102"
        # Never silently re-enqueued: no active dispatch owner, no queue re-entry.
        assert recovered.get("dispatch-owner-epoch") is None
    finally:
        client2.close()
        _HoldableRigHandler.hold.set()
        stop_subprocess_gracefully(proc2)


def test_crash_while_running_recovers_as_interrupted(tmp_path: Path, rig_server) -> None:
    """Crash after the attempt started (state=running, no attempt evidence
    appended yet since the rig is holding the response) must recover as
    terminal interrupted with the stale-owner error, never left running
    forever and never silently re-dispatched."""
    _require_docker_gate()
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    rig_port = rig_server.server_address[1]
    write_execution_profile(tmp_path, provider_id="local-openai", model_id="audiagentic-rig", max_concurrency=1)
    enable_local_openai(tmp_path, rig_port)

    service_root = tmp_path / "service-state"
    token_path = tmp_path / "gateway.token"
    port = free_port()
    proc = start_gateway_subprocess(service_root, token_path, port)
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    request_id = None
    try:
        submitted = client.submit_execution_request(tmp_path, prompt_body="hang here", mode="async")
        request_id = submitted["request-id"]

        wait_for_record_state(tmp_path, request_id, {"running"})
        wait_for_index_phase(service_root, request_id, "running")

        kill_subprocess(proc)
    finally:
        client.close()
        if proc.poll() is None:
            kill_subprocess(proc)

    port2 = free_port()
    proc2 = start_gateway_subprocess(service_root, token_path, port2)
    client2 = StandaloneGatewayClient(f"http://127.0.0.1:{port2}", load_auth_token(token_path))
    try:
        recovered = wait_for_record_state(tmp_path, request_id, {"interrupted"})
        assert recovered["error"]["code"] == "CON-AGW-084"
        assert _HoldableRigHandler.request_count <= 1  # never double-dispatched
    finally:
        client2.close()
        _HoldableRigHandler.hold.set()
        stop_subprocess_gracefully(proc2)


def test_cancel_raced_with_recovery_reaches_consistent_terminal_state(
    tmp_path: Path, rig_server
) -> None:
    """A cancel sent while the process is about to die must not corrupt
    recovery: the restarted service still terminalizes the stale running
    request exactly once, and the cancel-requested flag survives."""
    _require_docker_gate()
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    rig_port = rig_server.server_address[1]
    write_execution_profile(tmp_path, provider_id="local-openai", model_id="audiagentic-rig", max_concurrency=1)
    enable_local_openai(tmp_path, rig_port)

    service_root = tmp_path / "service-state"
    token_path = tmp_path / "gateway.token"
    port = free_port()
    proc = start_gateway_subprocess(service_root, token_path, port)
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    request_id = None
    try:
        submitted = client.submit_execution_request(tmp_path, prompt_body="hang then cancel", mode="async")
        request_id = submitted["request-id"]
        wait_for_record_state(tmp_path, request_id, {"running"})

        client.cancel_execution_request(tmp_path, request_id)
        wait_for(
            lambda: _read_record(tmp_path, request_id).get("cancel-requested") is True,
            timeout=10, what="cancel-requested flag persisted",
        )

        kill_subprocess(proc)
    finally:
        client.close()
        if proc.poll() is None:
            kill_subprocess(proc)

    port2 = free_port()
    proc2 = start_gateway_subprocess(service_root, token_path, port2)
    client2 = StandaloneGatewayClient(f"http://127.0.0.1:{port2}", load_auth_token(token_path))
    try:
        recovered = wait_for_record_state(tmp_path, request_id, {"interrupted"})
        assert recovered.get("cancel-requested") is True
        assert _HoldableRigHandler.request_count <= 1  # cancel race never caused a second dispatch
    finally:
        client2.close()
        _HoldableRigHandler.hold.set()
        stop_subprocess_gracefully(proc2)


def test_malformed_active_work_entry_is_quarantined_not_deleted_on_restart(
    tmp_path: Path, rig_server
) -> None:
    """A corrupted control-plane index entry sitting on disk when the service
    starts must be quarantined for forensic analysis, not silently deleted,
    and must not block recovery of a real, valid entry alongside it."""
    _require_docker_gate()
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    rig_port = rig_server.server_address[1]
    write_execution_profile(tmp_path, provider_id="local-openai", model_id="audiagentic-rig", max_concurrency=1)
    enable_local_openai(tmp_path, rig_port)

    service_root = tmp_path / "service-state"
    token_path = tmp_path / "gateway.token"
    port = free_port()
    proc = start_gateway_subprocess(service_root, token_path, port)
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    request_id = None
    try:
        submitted = client.submit_execution_request(tmp_path, prompt_body="hang", mode="async")
        request_id = submitted["request-id"]
        wait_for_record_state(tmp_path, request_id, {"running"})
        kill_subprocess(proc)
    finally:
        client.close()
        if proc.poll() is None:
            kill_subprocess(proc)

    # Plant a corrupted index entry alongside the real one, directly on disk,
    # while the service is down.
    index_dir = service_store_root(service_root) / "active-work"
    (index_dir / "req_tampered.json").write_text('{"request-id": "req_tampered"}', encoding="utf-8")

    port2 = free_port()
    proc2 = start_gateway_subprocess(service_root, token_path, port2)
    client2 = StandaloneGatewayClient(f"http://127.0.0.1:{port2}", load_auth_token(token_path))
    try:
        recovered = wait_for_record_state(tmp_path, request_id, {"interrupted"})
        assert recovered["error"]["code"] == "CON-AGW-084"

        quarantine_dir = index_dir / "quarantine"
        wait_for(
            lambda: any(quarantine_dir.glob("req_tampered_*.json")),
            timeout=10, what="tampered entry quarantined",
        )
        assert not (index_dir / "req_tampered.json").exists()
    finally:
        client2.close()
        _HoldableRigHandler.hold.set()
        stop_subprocess_gracefully(proc2)


# ---------------------------------------------------------------------------
# SH07 2026-07-20 closure pass: the two remaining narrow-timing-window
# scenarios (claim-before-start, terminal-before-cleanup) are, by
# construction, a single in-process gap between two adjacent synchronous
# store calls with no I/O in between -- too narrow to hit reliably from an
# external OS-level kill without deliberately widening the window. Both
# scenarios below activate a test-only stall hook (agents_gateway_queue.
# _test_stall_claim_to_start / agents_gateway_store._transitions.
# _test_stall_terminal_to_cleanup) via an env var passed ONLY to the child
# gateway subprocess (never the host test runner or the restarted process),
# so the real production code path executes unmodified except for an
# explicit, observable, opt-in sleep between the same two calls a real crash
# would land between. The env var defaults to unset/no-op everywhere else,
# including the four scenarios above and the concurrency suite.
# ---------------------------------------------------------------------------

_ENV_STALL_CLAIM_TO_START = "AUDIAGENTIC_GATEWAY_TEST_STALL_CLAIM_TO_START_MS"
_ENV_STALL_TERMINAL_TO_CLEANUP = "AUDIAGENTIC_GATEWAY_TEST_STALL_TERMINAL_TO_CLEANUP_MS"


def test_crash_after_claim_before_start_recovers_as_replay_required(
    tmp_path: Path, rig_server
) -> None:
    """SH07 required scenario: crash after dispatch claim but before the
    attempt starts. The stall hook widens this single-thread gap (claim_
    dispatch has already returned and written work-index phase=claimed with
    a real owner epoch; start_owned_attempt has not yet run) long enough for
    a real SIGKILL to land inside it. Recovery must terminalize as
    interrupted + replay-required=true (never left claimed forever, never
    silently resumed as if it had started)."""
    _require_docker_gate()
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    rig_port = rig_server.server_address[1]
    write_execution_profile(tmp_path, provider_id="local-openai", model_id="audiagentic-rig", max_concurrency=1)
    enable_local_openai(tmp_path, rig_port)

    service_root = tmp_path / "service-state"
    token_path = tmp_path / "gateway.token"
    port = free_port()
    proc = start_gateway_subprocess(
        service_root, token_path, port,
        extra_env={_ENV_STALL_CLAIM_TO_START: "8000"},
    )
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    request_id = None
    try:
        submitted = client.submit_execution_request(tmp_path, prompt_body="claim then stall", mode="async")
        request_id = submitted["request-id"]

        # Observed directly from the on-disk control-plane index: claimed
        # phase means claim_dispatch committed (owner epoch persisted) and
        # the stall hook is now sleeping before start_owned_attempt runs.
        wait_for_index_phase(service_root, request_id, "claimed")
        claimed_record = _read_record(tmp_path, request_id)
        assert claimed_record["state"] == "queued"  # start_owned_attempt has not run yet
        assert claimed_record.get("dispatch-owner-epoch") is not None  # claim DID commit

        kill_subprocess(proc)
    finally:
        client.close()
        if proc.poll() is None:
            kill_subprocess(proc)

    # Restart WITHOUT the stall hook -- a normal recovery pass.
    port2 = free_port()
    proc2 = start_gateway_subprocess(service_root, token_path, port2)
    client2 = StandaloneGatewayClient(f"http://127.0.0.1:{port2}", load_auth_token(token_path))
    try:
        recovered = wait_for_record_state(tmp_path, request_id, {"interrupted"})
        assert recovered["replay-required"] is True
        assert recovered["error"]["code"] == "CON-AGW-102"
        assert _HoldableRigHandler.request_count == 0  # never dispatched to the provider at all
    finally:
        client2.close()
        _HoldableRigHandler.hold.set()
        stop_subprocess_gracefully(proc2)


def test_crash_after_terminal_before_index_cleanup_preserves_terminal_result(
    tmp_path: Path, rig_server
) -> None:
    """SH07 required scenario: crash after the terminal record write but
    before best-effort control-plane index cleanup. The stall hook widens
    this single-thread gap (transition_owned_terminal has already durably
    written state=completed; clear_stale_terminal_index/clear_active_work
    have not yet run) long enough for a real SIGKILL to land inside it.
    Recovery on restart must find the leftover index/active-work entries
    pointing at an already-terminal request and sweep them without ever
    re-terminalizing, overwriting, or duplicating the completed result."""
    _require_docker_gate()
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    rig_port = rig_server.server_address[1]
    # Unlike the other scenarios, this one wants the rig to answer immediately
    # so the request reaches a terminal state on its own -- release the hold
    # up front instead of using it to stall the request.
    _HoldableRigHandler.hold.set()
    write_execution_profile(tmp_path, provider_id="local-openai", model_id="audiagentic-rig", max_concurrency=1)
    enable_local_openai(tmp_path, rig_port)

    service_root = tmp_path / "service-state"
    token_path = tmp_path / "gateway.token"
    port = free_port()
    proc = start_gateway_subprocess(
        service_root, token_path, port,
        extra_env={_ENV_STALL_TERMINAL_TO_CLEANUP: "8000"},
    )
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    request_id = None
    pre_crash_record = None
    try:
        submitted = client.submit_execution_request(tmp_path, prompt_body="complete then stall", mode="async")
        request_id = submitted["request-id"]

        # Caught mid-stall: the terminal write already landed, but cleanup
        # (stalled 8s) has not run, so both leftover entries are still on disk.
        pre_crash_record = wait_for_record_state(tmp_path, request_id, {"completed"})
        assert active_work_entry_path(service_root, request_id).exists()
        assert index_entry_path(service_root, request_id).exists()

        kill_subprocess(proc)
    finally:
        client.close()
        if proc.poll() is None:
            kill_subprocess(proc)

    # Restart WITHOUT the stall hook -- a normal recovery pass.
    port2 = free_port()
    proc2 = start_gateway_subprocess(service_root, token_path, port2)
    client2 = StandaloneGatewayClient(f"http://127.0.0.1:{port2}", load_auth_token(token_path))
    try:
        # Never re-terminalized: same finished-at, same output, no error.
        wait_for(
            lambda: not active_work_entry_path(service_root, request_id).exists()
            and not index_entry_path(service_root, request_id).exists(),
            timeout=10, what="leftover terminal entries swept by recovery",
        )
        post_recovery_record = _read_record(tmp_path, request_id)
        assert post_recovery_record["state"] == "completed"
        assert post_recovery_record["finished-at"] == pre_crash_record["finished-at"]
        assert post_recovery_record.get("output") == pre_crash_record.get("output")
        assert "error" not in post_recovery_record or post_recovery_record["error"] is None
    finally:
        client2.close()
        _HoldableRigHandler.hold.set()
        stop_subprocess_gracefully(proc2)
