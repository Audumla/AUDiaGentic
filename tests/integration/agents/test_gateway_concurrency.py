"""Real concurrent load against a real gateway subprocess and a real local
rig — the coverage gap crash-matrix/opencode don't fill.

Every other gateway Docker suite either focuses on crash recovery
(test_gateway_crash_matrix_docker.py) or a single real-CLI happy path
(test_gateway_opencode_docker.py). Neither proves the gateway's actual
concurrency guarantees under real overlapping requests: virtual-capacity
genuinely bounding simultaneous dispatch, two different projects sharing one
gateway-owned profile lane (SH07 Slice 0 / SH13), pending-capacity rejection,
and reload-vs-in-flight-load races. Those guarantees are proven today only
against an in-process fake (tests/integration/agents/test_gateway_standalone_service.py)
— this suite proves them against a real OS subprocess and a real HTTP rig.

Uses HoldableRigHandler's peak-concurrency tracking (gateway_docker_harness.py)
to force and observe genuine overlap, rather than asserting on timing luck.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from tests.integration.agents.gateway_docker_harness import (
    HoldableRigHandler,
    enable_local_openai,
    free_port,
    start_gateway_subprocess,
    start_rig_server,
    stop_rig_server,
    stop_subprocess_gracefully,
    wait_for,
    wait_for_record_state,
    write_execution_profile,
    write_gateway_profiles_config,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.opt_in,
    pytest.mark.requires_container,
    pytest.mark.timeout(180),
]

_DOCKER_GATE_ENV = "AUDIAGENTIC_GATEWAY_CONCURRENCY_DOCKER"


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


def _start_service(
    tmp_path: Path,
    *,
    gateway_profiles: list[dict],
    name: str = "service-state",
) -> tuple:
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    gw_config_path = tmp_path / "gateway-profiles.yaml"
    write_gateway_profiles_config(gw_config_path, gateway_profiles)

    service_root = tmp_path / name
    token_path = tmp_path / f"{name}.token"
    port = free_port()
    proc = start_gateway_subprocess(
        service_root, token_path, port, gateway_profiles_config=gw_config_path
    )
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    return proc, client, service_root, token_path, gw_config_path


def test_real_concurrent_saturation_bounds_at_virtual_capacity(
    tmp_path: Path, rig_server
) -> None:
    """virtual-capacity=2, 3 submitted: exactly 2 genuinely overlap in-flight
    (never more), the 3rd stays queued until a slot frees, and all 3
    eventually complete."""
    _require_docker_gate()
    rig_port = rig_server.server_address[1]
    write_execution_profile(tmp_path, provider_id="local-openai", model_id="audiagentic-rig", virtual_capacity=1)
    enable_local_openai(tmp_path, rig_port)

    proc, client, service_root, token_path, _ = _start_service(
        tmp_path,
        gateway_profiles=[{
            "profile_id": "default", "provider_id": "local-openai", "model_id": "audiagentic-rig",
            "params": {"virtual-capacity": 2, "pending-capacity": 8},
        }],
    )
    try:
        first = client.submit_execution_request(tmp_path, prompt_body="one", mode="async")
        second = client.submit_execution_request(tmp_path, prompt_body="two", mode="async")
        third = client.submit_execution_request(tmp_path, prompt_body="three", mode="async")

        # Both concurrency slots must fill before the rig releases anything —
        # this is the actual proof of real overlap, not a timing guess.
        try:
            wait_for(
                lambda: HoldableRigHandler.active_count == 2,
                timeout=10, what="two requests genuinely in-flight simultaneously",
            )
        except AssertionError as exc:
            output = getattr(proc, "_ag_captured_output", [])
            raise AssertionError(f"{exc}; gateway output: {' | '.join(output[-20:])}") from exc
        # The third must still be queued, not dispatched, while both slots are full.
        third_status = client.get_execution_request(tmp_path, third["request-id"])
        assert third_status["state"] == "queued"

        HoldableRigHandler.hold.set()

        for req in (first, second, third):
            recovered = wait_for_record_state(tmp_path, req["request-id"], {"completed"}, timeout=20)
            assert recovered["state"] == "completed"

        assert HoldableRigHandler.peak_active_count == 2, (
            f"expected exactly 2 concurrent in-flight requests (virtual-capacity=2), "
            f"observed peak={HoldableRigHandler.peak_active_count}"
        )
    finally:
        client.close()
        stop_subprocess_gracefully(proc)


def test_cross_project_sharing_enforces_global_limit(tmp_path: Path, rig_server) -> None:
    """SH07 Slice 0 / SH13: two DIFFERENT project roots submitting against
    the SAME gateway-owned profile share one physical lane — the global
    virtual-capacity is enforced across both projects combined, not per
    project. Proven here against a real subprocess for the first time (the
    existing coverage in test_gateway_standalone_service.py is in-process)."""
    _require_docker_gate()
    rig_port = rig_server.server_address[1]
    root_a = tmp_path / "project_a"
    root_b = tmp_path / "project_b"
    root_a.mkdir()
    root_b.mkdir()
    for root in (root_a, root_b):
        write_execution_profile(root, provider_id="local-openai", model_id="audiagentic-rig", virtual_capacity=1)
        enable_local_openai(root, rig_port)

    proc, client, service_root, token_path, _ = _start_service(
        tmp_path,
        gateway_profiles=[{
            "profile_id": "default", "provider_id": "local-openai", "model_id": "audiagentic-rig",
            "params": {"virtual-capacity": 1, "pending-capacity": 8},
        }],
    )
    try:
        from_a = client.submit_execution_request(root_a, prompt_body="from project a", mode="async")
        from_b = client.submit_execution_request(root_b, prompt_body="from project b", mode="async")

        # Only one slot exists globally — exactly one of the two projects'
        # requests can be running at a time, never both.
        wait_for(
            lambda: HoldableRigHandler.active_count == 1,
            timeout=10, what="exactly one cross-project request running",
        )
        import time
        time.sleep(0.5)  # give the second project's request every chance to (wrongly) also start
        assert HoldableRigHandler.active_count == 1, "a second project's request started concurrently"

        HoldableRigHandler.hold.set()

        for root, req in ((root_a, from_a), (root_b, from_b)):
            recovered = wait_for_record_state(root, req["request-id"], {"completed"}, timeout=20)
            assert recovered["state"] == "completed"

        assert HoldableRigHandler.peak_active_count == 1
    finally:
        client.close()
        stop_subprocess_gracefully(proc)


def test_pending_capacity_exceeded_is_rejected_not_silently_dropped(
    tmp_path: Path, rig_server
) -> None:
    """Negative path: once the queue is genuinely full, a further submission
    is rejected synchronously with VAL-AGW-025 — it does not silently
    disappear and does not block the requests already admitted."""
    _require_docker_gate()
    rig_port = rig_server.server_address[1]
    write_execution_profile(tmp_path, provider_id="local-openai", model_id="audiagentic-rig", virtual_capacity=1)
    enable_local_openai(tmp_path, rig_port)

    proc, client, service_root, token_path, _ = _start_service(
        tmp_path,
        gateway_profiles=[{
            "profile_id": "default", "provider_id": "local-openai", "model_id": "audiagentic-rig",
            "params": {"virtual-capacity": 1, "pending-capacity": 1},
        }],
    )
    try:
        running = client.submit_execution_request(tmp_path, prompt_body="running", mode="async")
        wait_for(
            lambda: HoldableRigHandler.active_count == 1,
            timeout=10, what="first request occupies the sole concurrency slot",
        )
        queued = client.submit_execution_request(tmp_path, prompt_body="queued", mode="async")
        assert client.get_execution_request(tmp_path, queued["request-id"])["state"] == "queued"

        overflow = client.submit_execution_request(tmp_path, prompt_body="overflow", mode="async")
        assert overflow["state"] == "rejected", overflow
        assert overflow["error"]["code"] == "VAL-AGW-025"

        HoldableRigHandler.hold.set()
        for req in (running, queued):
            recovered = wait_for_record_state(tmp_path, req["request-id"], {"completed"}, timeout=20)
            assert recovered["state"] == "completed"
    finally:
        client.close()
        stop_subprocess_gracefully(proc)


def test_reload_racing_concurrent_load_rejects_stale_keeps_running_intact(
    tmp_path: Path, rig_server
) -> None:
    """Negative/consistency path, real-subprocess version of the in-process
    reload-vs-concurrent-load coverage in test_gateway_standalone_service.py:
    reloading the gateway-owned profile registry while requests are
    genuinely in flight must reject the queued stale one (CON-AGW-101) once
    its dispatch is attempted, and must not disturb the request already
    running under its original snapshot."""
    _require_docker_gate()
    rig_port = rig_server.server_address[1]
    write_execution_profile(tmp_path, provider_id="local-openai", model_id="audiagentic-rig", virtual_capacity=1)
    enable_local_openai(tmp_path, rig_port)

    gw_config_path = tmp_path / "gateway-profiles.yaml"
    write_gateway_profiles_config(gw_config_path, [{
        "profile_id": "default", "provider_id": "local-openai", "model_id": "audiagentic-rig",
        "params": {"virtual-capacity": 1, "pending-capacity": 8},
    }])

    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    service_root = tmp_path / "service-state"
    token_path = tmp_path / "gateway.token"
    port = free_port()
    proc = start_gateway_subprocess(service_root, token_path, port, gateway_profiles_config=gw_config_path)
    client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token_path))
    try:
        running = client.submit_execution_request(tmp_path, prompt_body="running", mode="async")
        wait_for(
            lambda: HoldableRigHandler.active_count == 1,
            timeout=10, what="request occupies the sole concurrency slot",
        )
        queued = client.submit_execution_request(tmp_path, prompt_body="queued", mode="async")
        assert client.get_execution_request(tmp_path, queued["request-id"])["state"] == "queued"

        # Mutate the config and reload through the real HTTP service operation.
        write_gateway_profiles_config(gw_config_path, [{
            "profile_id": "default", "provider_id": "local-openai", "model_id": "audiagentic-rig",
            "params": {"virtual-capacity": 2, "pending-capacity": 16},
        }])
        reload_result = client._call("reload_gateway_profiles", tmp_path, {})
        assert reload_result["success"] is True

        # Release the running request first — staleness is validated lazily,
        # right before dispatch, not proactively at reload time, so the
        # queued entry only gets checked once a slot frees for it.
        HoldableRigHandler.hold.set()
        recovered_running = wait_for_record_state(tmp_path, running["request-id"], {"completed"}, timeout=20)
        assert recovered_running["state"] == "completed"

        recovered_queued = wait_for_record_state(tmp_path, queued["request-id"], {"rejected"}, timeout=20)
        assert recovered_queued["error"]["code"] == "CON-AGW-101"
    finally:
        client.close()
        stop_subprocess_gracefully(proc)


def test_cancel_racing_concurrent_dispatch_does_not_disturb_others(
    tmp_path: Path, rig_server
) -> None:
    """Negative path: cancelling one of several concurrently in-flight/queued
    requests terminates only that one — the others complete normally."""
    _require_docker_gate()
    rig_port = rig_server.server_address[1]
    write_execution_profile(tmp_path, provider_id="local-openai", model_id="audiagentic-rig", virtual_capacity=1)
    enable_local_openai(tmp_path, rig_port)

    proc, client, service_root, token_path, _ = _start_service(
        tmp_path,
        gateway_profiles=[{
            "profile_id": "default", "provider_id": "local-openai", "model_id": "audiagentic-rig",
            "params": {"virtual-capacity": 2, "pending-capacity": 8},
        }],
    )
    try:
        first = client.submit_execution_request(tmp_path, prompt_body="keep-running-1", mode="async")
        second = client.submit_execution_request(tmp_path, prompt_body="keep-running-2", mode="async")
        to_cancel = client.submit_execution_request(tmp_path, prompt_body="cancel-me", mode="async")

        wait_for(
            lambda: HoldableRigHandler.active_count == 2,
            timeout=10, what="both concurrency slots occupied, third queued",
        )
        assert client.get_execution_request(tmp_path, to_cancel["request-id"])["state"] == "queued"

        client.cancel_execution_request(tmp_path, to_cancel["request-id"])
        HoldableRigHandler.hold.set()

        cancelled = wait_for_record_state(
            tmp_path, to_cancel["request-id"], {"cancelled", "rejected"}, timeout=20,
        )
        assert cancelled["state"] in {"cancelled", "rejected"}

        for req in (first, second):
            recovered = wait_for_record_state(tmp_path, req["request-id"], {"completed"}, timeout=20)
            assert recovered["state"] == "completed"
    finally:
        client.close()
        stop_subprocess_gracefully(proc)
