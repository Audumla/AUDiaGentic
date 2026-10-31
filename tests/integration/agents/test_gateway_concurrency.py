"""Real gateway-process FIFO/capacity coverage used by the concurrency image."""
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
    wait_for_index_phase,
    wait_for_record_state,
    write_execution_profile,
)

pytestmark = [pytest.mark.integration, pytest.mark.opt_in,
              pytest.mark.requires_container, pytest.mark.timeout(180)]


@pytest.mark.parametrize("separate_projects", [False, True])
def test_real_gateway_serializes_profile_lane_and_drains_queue(tmp_path: Path, separate_projects):
    if os.environ.get("AUDIAGENTIC_GATEWAY_CONCURRENCY_DOCKER") != "1":
        pytest.skip("run in the gateway concurrency image")
    from audiagentic.components.agents.gateway.remote_client import (
        StandaloneGatewayClient,
        load_auth_token,
    )

    rig = start_rig_server()
    roots = [tmp_path / "first", tmp_path / ("second" if separate_projects else "first")]
    state = tmp_path / "service-state"
    token = tmp_path / "auth.token"
    port = free_port()
    proc = None
    client = None
    try:
        for root in set(roots):
            root.mkdir(parents=True, exist_ok=True)
        # Profiles are machine-global: create the shared lane once, not once
        # per project (which correctly rejects the duplicate profile ID).
        write_execution_profile(roots[0], provider_id="local-openai", model_id="audiagentic-rig",
                                virtual_capacity=1, pending_capacity=2)
        for root in set(roots):
            enable_local_openai(root, rig.server_address[1])
        proc = start_gateway_subprocess(state, token, port)
        client = StandaloneGatewayClient(f"http://127.0.0.1:{port}", load_auth_token(token))
        first = client.submit_execution_request(roots[0], prompt_body="first", mode="async")
        wait_for_record_state(roots[0], first["request-id"], {"running"})
        second = client.submit_execution_request(roots[1], prompt_body="second", mode="async")
        wait_for_index_phase(state, second["request-id"], "admitted")
        # The first real HTTP request remains held, so the second must not
        # acquire a worker or advance beyond admission in either project.
        queued = wait_for_record_state(roots[1], second["request-id"], {"queued"})
        assert queued.get("dispatch-owner-epoch") is None
        HoldableRigHandler.hold.set()
        for root, request in zip(roots, [first, second]):
            completed = wait_for_record_state(root, request["request-id"], {"completed"}, timeout=30)
            assert completed.get("error") is None
    finally:
        HoldableRigHandler.hold.set()
        if client is not None:
            client.close()
        if proc is not None:
            stop_subprocess_gracefully(proc)
        stop_rig_server(rig)
