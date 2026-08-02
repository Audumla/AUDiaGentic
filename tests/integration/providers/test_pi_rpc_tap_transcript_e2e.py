"""AS40 validate-first: exact-version RPC transcript fixture, tapped.

Freezes a real observed transcript from the tapped `pi --mode rpc` stdout
across the sequence AS40's validate_first section requires: initialization
(session/new's get_state/get_available_models), a real prompt turn (agent
start -> incremental message updates -> agent end), and shutdown -- driven
through the real pi-acp bridge with the tee shim installed, using a real
local model via the embedded llama-server rig (the same provisioning
gateway-pi-smoke uses), so no external API key is needed.

Unlike test_pi_rpc_tap_real_binaries.py (which only proves the session/new
handshake, since that alone needs no model), this proves the tap survives a
genuine multi-message conversational turn -- the part of AS40's
acceptance criteria a bare handshake cannot cover.

Docker-gated: provisions a real npm-installed Pi CLI and downloads/loads a
real local GGUF model (see Dockerfile.pi-rpc-tap-e2e). Per this repo's
Docker-test doctrine, this suite is validated by building and running that
image -- never by setting its gate env var on the host.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.opt_in,
    pytest.mark.requires_npm,
    pytest.mark.timeout(900),
]

_DOCKER_GATE_ENV = "AUDIAGENTIC_PI_RPC_TAP_E2E_DOCKER"
_MODEL_PROFILE = "qwen3.5-2b"
_PI_MODEL_REF = "audiagentic/audiagentic-rig"
_PROMPT_TEXT = "Reply with exactly: OK"


def _require_docker_gate() -> None:
    if os.environ.get(_DOCKER_GATE_ENV) != "1":
        pytest.skip(f"opt-in Docker gate; set {_DOCKER_GATE_ENV}=1")


def _write_harness_config(project_root: Path, rig_port: int) -> None:
    config_root = project_root / ".audiagentic" / "config" / "harness"
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "ag.yaml").write_text(
        yaml.safe_dump(
            {
                "harness": {"type": "pi"},
                "rig": {"port": rig_port, "model": _MODEL_PROFILE, "provider": "audiagentic"},
                "mcp": {"enabled": False},
                "smoke": {"timeout": 60},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _send(proc: subprocess.Popen, obj: dict) -> None:
    proc.stdin.write((json.dumps(obj) + "\n").encode())
    proc.stdin.flush()


def test_real_pi_rpc_transcript_through_the_tap_covers_a_full_prompt_turn(
    tmp_path: Path, monkeypatch
) -> None:
    """Real npm-installed Pi CLI + real embedded rig, ACP session driven
    through the tee shim, sends one real prompt and freezes the tapped
    transcript across the initialization/prompt/agent_end sequence."""
    _require_docker_gate()

    from tests.integration.agents.gateway_docker_harness import free_port
    from tests.integration.providers.harness import assert_install_result_ok

    from audiagentic.components.providers.adapters.pi import acp as pi_acp
    from audiagentic.components.providers.adapters.pi.rpc_tap import JsonlTapFrame
    from audiagentic.components.providers.adapters.pi.rpc_tap_receiver import (
        iter_tap_frames,
        open_tap_listener_for_launch,
    )
    from audiagentic.components.providers.services.config.provider_config import (
        patch_provider_config,
    )
    from audiagentic.components.providers.services.lifecycle.lifecycle import install_provider_cli
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.runtime.harness import refresh_materialized_agent_config
    from audiagentic.runtime.harness.provisioning import provision_embedded_rig
    from audiagentic.runtime.rig.service import (
        release_embedded_rig,
        start_or_attach_embedded_rig,
    )

    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(tmp_path))

    rig_port = free_port()
    _write_harness_config(tmp_path, rig_port)

    install_result = install_provider_cli("pi", timeout=900, project_root=tmp_path)
    assert_install_result_ok("pi", install_result)

    harness_runtime = global_harness_runtime()
    provision_embedded_rig(harness_runtime, tmp_path)
    refresh_materialized_agent_config(harness_runtime, project_root=tmp_path)

    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(harness_runtime / "agent"))
    models_json = harness_runtime / "agent" / "models.json"
    assert models_json.is_file(), f"Pi models.json not materialized: {models_json}"

    # Sets the embedded rig model as pi's own default so the ACP session
    # picks it up without needing pi-acp CLI flag support (pi-acp's CLI
    # parses only --terminal-login; --model/--cwd/--session-dir on its own
    # argv are silently ignored -- a pre-existing gap in build_acp_launch's
    # CLI-arg approach, unrelated to AS40, noted but not fixed here).
    patch_provider_config(
        tmp_path,
        "pi",
        {
            "access-mode": "cli",
            "install-mode": "external-configured",
            "default-model": _PI_MODEL_REF,
        },
    )

    launch = start_or_attach_embedded_rig(
        profile_name=_MODEL_PROFILE, rig_port=rig_port, model_id=_PI_MODEL_REF
    )
    try:
        project_root = tmp_path / "project"
        project_root.mkdir()
        request_runtime_root = tmp_path / "runtime"
        acp_launch = pi_acp.build_acp_launch(
            project_root, request_runtime_root=request_runtime_root, enable_rpc_tap=True
        )

        # build_acp_launch isolates PI_CODING_AGENT_DIR to a fresh, empty
        # per-request directory (correct production behavior -- each request
        # gets its own scoped agent dir). It does not carry over the real
        # models.json the install just materialized, so pi's own
        # getAvailableModels() would see zero models and pi-acp would reject
        # session/new with "Authentication required" before ever reaching
        # the real prompt exchange. Seed it the same way
        # agents_gateway_worker._replacement_environment does for the
        # one-shot dispatch path: copy models.json in, nothing else.
        import shutil as _shutil

        isolated_agent_dir = Path(acp_launch.environment["PI_CODING_AGENT_DIR"])
        _shutil.copy2(harness_runtime / "agent" / "models.json", isolated_agent_dir / "models.json")

        listener = open_tap_listener_for_launch(acp_launch.environment)
        frames: list = []

        def _consume() -> None:
            for item in iter_tap_frames(listener):
                frames.append(item)

        consumer = threading.Thread(target=_consume, daemon=True)
        consumer.start()

        env = dict(os.environ)
        env.update(acp_launch.environment)
        proc = subprocess.Popen(
            [acp_launch.executable, *acp_launch.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        threading.Thread(target=lambda: proc.stderr.read(), daemon=True).start()

        try:
            _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1, "clientCapabilities": {}}})
            init_resp = json.loads(proc.stdout.readline())
            assert init_resp["result"]["agentInfo"]["name"] == "pi-acp"

            _send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/new",
                    "params": {"cwd": str(project_root.resolve()), "mcpServers": []},
                },
            )
            session_resp = json.loads(proc.stdout.readline())
            assert "result" in session_resp, json.dumps(session_resp, indent=2)
            session_id = session_resp["result"]["sessionId"]

            _send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "session/prompt",
                    "params": {
                        "sessionId": session_id,
                        "prompt": [{"type": "text", "text": _PROMPT_TEXT}],
                    },
                },
            )
            # ACP streams sessionUpdate notifications (no "id") before the
            # final session/prompt response (id=3) -- drain until we see it.
            prompt_resp = None
            for _ in range(200):
                line = proc.stdout.readline()
                if not line:
                    break
                message = json.loads(line)
                if message.get("id") == 3:
                    prompt_resp = message
                    break
            assert prompt_resp is not None, "session/prompt never resolved"
            assert "result" in prompt_resp, json.dumps(prompt_resp, indent=2)
            assert prompt_resp["result"].get("stopReason") == "end_turn"
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            listener.close()
            consumer.join(timeout=5)
    finally:
        release_embedded_rig(launch)

    frame_types = [f.payload.get("type") for f in frames if isinstance(f, JsonlTapFrame)]
    # The exact-version transcript fixture: real tapped frame types spanning
    # the full initialization -> prompt -> agent_end sequence AS40's
    # validate_first section requires, not inferred/guessed from pi-acp's
    # own (narrower) ACP event vocabulary.
    assert "agent_start" in frame_types, frame_types
    assert "agent_end" in frame_types, frame_types
    assert any(t in frame_types for t in ("message_update", "turn_end")), frame_types


_TOOL_PROMPT_TEXT = (
    "Use your shell tool right now to run exactly this command: "
    "echo AS41_TOOL_TAP_PROOF_9f3a1c. Call the tool -- do not reply with text only."
)


def test_real_pi_rpc_transcript_captures_tool_call_frame_types(
    tmp_path: Path, monkeypatch
) -> None:
    """AS41 follow-up (2026-07-29): drives Pi through a prompt designed to
    trigger a real shell tool call, and logs every distinct tapped frame
    type observed -- not a fixed-vocabulary assertion, since a small local
    model's tool-calling reliability is genuinely uncertain. This is the
    proof-gathering step AS41's own doctrine requires before
    rpc_tap_evidence.py's closed-vocabulary mapper can honestly claim
    tool_execution_* kinds: map only what a real transcript proves, never
    guess from source documentation alone.

    Prints the full set of observed frame types plus one example payload per
    type so a human (or a follow-up session) can extend the mapper from real
    evidence, exactly the same way agent_start/message_update/turn_end/
    agent_end were proven for the base transcript test above.

    AS41 diagnostic hardening (2026-07-30): the original version discarded
    pi-acp's stderr in a fire-and-forget daemon thread, so when the real
    `pi` child exited before the turn resolved (EOF on stdout), the test
    failed with a bare "session/prompt never resolved" and zero signal about
    *why* the child died. This version captures stderr line-by-line and
    surfaces the exit code + stderr in the failure message, and enables the
    shim's stderr-dump-on-crash env var so the real `pi` child's crash
    reason propagates through the shim's stderr into that capture.
    """
    _require_docker_gate()

    from tests.integration.agents.gateway_docker_harness import free_port
    from tests.integration.providers.harness import assert_install_result_ok

    from audiagentic.components.providers.adapters.pi import acp as pi_acp
    from audiagentic.components.providers.adapters.pi.rpc_tap import JsonlTapFrame
    from audiagentic.components.providers.adapters.pi.rpc_tap_receiver import (
        iter_tap_frames,
        open_tap_listener_for_launch,
    )
    from audiagentic.components.providers.services.config.provider_config import (
        patch_provider_config,
    )
    from audiagentic.components.providers.services.lifecycle.lifecycle import install_provider_cli
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.runtime.harness import refresh_materialized_agent_config
    from audiagentic.runtime.harness.provisioning import provision_embedded_rig
    from audiagentic.runtime.rig.service import (
        release_embedded_rig,
        start_or_attach_embedded_rig,
    )

    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(tmp_path))

    rig_port = free_port()
    _write_harness_config(tmp_path, rig_port)

    install_result = install_provider_cli("pi", timeout=900, project_root=tmp_path)
    assert_install_result_ok("pi", install_result)

    harness_runtime = global_harness_runtime()
    provision_embedded_rig(harness_runtime, tmp_path)
    refresh_materialized_agent_config(harness_runtime, project_root=tmp_path)

    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(harness_runtime / "agent"))
    models_json = harness_runtime / "agent" / "models.json"
    assert models_json.is_file(), f"Pi models.json not materialized: {models_json}"

    patch_provider_config(
        tmp_path,
        "pi",
        {
            "access-mode": "cli",
            "install-mode": "external-configured",
            "default-model": _PI_MODEL_REF,
        },
    )

    launch = start_or_attach_embedded_rig(
        profile_name=_MODEL_PROFILE, rig_port=rig_port, model_id=_PI_MODEL_REF
    )
    try:
        project_root = tmp_path / "project"
        project_root.mkdir()
        request_runtime_root = tmp_path / "runtime"
        acp_launch = pi_acp.build_acp_launch(
            project_root, request_runtime_root=request_runtime_root, enable_rpc_tap=True
        )

        import shutil as _shutil

        isolated_agent_dir = Path(acp_launch.environment["PI_CODING_AGENT_DIR"])
        _shutil.copy2(harness_runtime / "agent" / "models.json", isolated_agent_dir / "models.json")

        listener = open_tap_listener_for_launch(acp_launch.environment)
        frames: list = []

        def _consume() -> None:
            for item in iter_tap_frames(listener):
                frames.append(item)

        consumer = threading.Thread(target=_consume, daemon=True)
        consumer.start()

        env = dict(os.environ)
        # AS41 diagnostic: enable the shim's stderr-dump-on-crash so if the
        # real `pi` child dies mid-turn, its stderr reaches our proc.stderr
        # instead of being silently swallowed by the shim.
        env["AUDIAGENTIC_PI_TAP_DUMP_STDERR_ON_CRASH"] = "1"
        env.update(acp_launch.environment)
        proc = subprocess.Popen(
            [acp_launch.executable, *acp_launch.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        # AS41 diagnostic: capture stderr instead of discarding it, so an EOF
        # (child exit before turn completion) carries the crash reason into
        # the assertion message instead of a bare "never resolved".
        stderr_chunks: list[bytes] = []

        def _drain_stderr() -> None:
            try:
                while True:
                    chunk = proc.stderr.readline()
                    if not chunk:
                        break
                    stderr_chunks.append(chunk)
            except OSError:
                pass

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        try:
            _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1, "clientCapabilities": {}}})
            init_resp = json.loads(proc.stdout.readline())
            assert init_resp["result"]["agentInfo"]["name"] == "pi-acp"

            _send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/new",
                    "params": {"cwd": str(project_root.resolve()), "mcpServers": []},
                },
            )
            session_resp = json.loads(proc.stdout.readline())
            assert "result" in session_resp, json.dumps(session_resp, indent=2)
            session_id = session_resp["result"]["sessionId"]

            _send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "session/prompt",
                    "params": {
                        "sessionId": session_id,
                        "prompt": [{"type": "text", "text": _TOOL_PROMPT_TEXT}],
                    },
                },
            )
            # A tool-invoking turn streams far more sessionUpdate notifications
            # (thinking + tool call + tool result + reply) than a plain-text
            # turn; 400 was proven too few empirically (this session, real
            # Docker run); generous bound so we get a conclusive result.
            prompt_resp = None
            for _ in range(4000):
                line = proc.stdout.readline()
                if not line:
                    break
                message = json.loads(line)
                if message.get("id") == 3:
                    prompt_resp = message
                    break
            if prompt_resp is None:
                # AS41 diagnostic: the child exited (EOF) before the turn
                # resolved. Surface the exit code and captured stderr so the
                # failure message is actionable instead of a bare "never
                # resolved" -- this is the exact signal that was missing when
                # the original run burned three Docker cycles blind.
                exit_code = proc.poll()
                stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")
                pytest.fail(
                    f"session/prompt never resolved -- child EOF (exit_code={exit_code}).\n"
                    f"--- captured stderr (pi-acp + shim dump) ---\n{stderr_text}\n"
                    f"--- end stderr ---"
                )
            assert "result" in prompt_resp, json.dumps(prompt_resp, indent=2)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            listener.close()
            consumer.join(timeout=5)
            stderr_thread.join(timeout=5)
    finally:
        release_embedded_rig(launch)

    frame_types = [f.payload.get("type") for f in frames if isinstance(f, JsonlTapFrame)]
    distinct_types = sorted(set(t for t in frame_types if t is not None))
    example_by_type = {}
    for f in frames:
        if not isinstance(f, JsonlTapFrame):
            continue
        t = f.payload.get("type")
        if t is not None and t not in example_by_type:
            example_by_type[t] = f.payload

    print("\n=== AS41 tool-call proof-gathering: observed frame types ===")
    print(json.dumps(distinct_types, indent=2))
    print("=== AS41 tool-call proof-gathering: one example payload per type ===")
    print(json.dumps(example_by_type, indent=2, default=str))
    print("=== end AS41 proof-gathering output ===\n")

    tool_frame_types = [t for t in distinct_types if t and t.startswith("tool_execution")]
    if tool_frame_types:
        print(f"REAL PROOF: tool-call frame types observed: {tool_frame_types}")
    else:
        print(
            "NO tool-call frames observed this run -- the small local model did not "
            "invoke the shell tool for this prompt. Not a test failure (model "
            "tool-calling reliability is out of scope to guarantee here); rerun or "
            "try a larger model profile to gather real proof before extending "
            "rpc_tap_evidence.py's mapper for tool_execution_* kinds."
        )
    # Baseline still holds regardless of tool-call success.
    assert "agent_start" in frame_types, frame_types
    assert "agent_end" in frame_types, frame_types