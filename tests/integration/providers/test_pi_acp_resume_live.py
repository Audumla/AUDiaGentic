"""AS49 validate-first: real proof that AUDiaGentic's OWN resume code

(`AcpAgentSessionTransport.open_resumed` / `AcpSessionTransport.open_resumed`,
foundation/transports/acp.py) works against the real `pi-acp` bridge.

Unlike an earlier draft of this test (raw hand-rolled JSON-RPC over the
bridge's stdio), this drives the actual product transport classes end-to-end
-- the same classes AS49's resume workflow will call -- through the same
install-then-run Docker pattern this repo's other live-provider recipes use
(install_provider_cli + provision_embedded_rig + patch_provider_config, as in
test_gateway_pi_smoke.py / test_pi_rpc_tap_transcript_e2e.py). A prior version
of this test only proved the bridge's wire protocol, not that AUDiaGentic's
own code correctly drives it -- this version closes that gap.

Proof strategy: rather than asserting on LLM-generated recall text (flaky
with a small local model), this proves resume structurally two ways:
  1. `AcpSessionTransport.supports_resume` is True after `open_resumed()` --
     the real bridge advertised `agent_capabilities.load_session`.
  2. `dropped_between_turns` on the RESUMED transport is > 0 immediately
     after `open_resumed()` returns -- ACP's `session/load` is specified to
     replay prior-turn `session/update` notifications before its response
     arrives; this repo's transport correctly counts (and safely discards,
     since no turn pipeline is active yet) those replayed notifications
     rather than silently losing track of them. A count of zero would mean
     either no replay happened (bridge doesn't truly resume) or our own
     counting broke.
  3. A follow-up prompt() on the resumed transport completes with
     stop_reason == "end_turn" and no error -- the loaded session is
     actually usable for a new turn, not just accepted-then-broken.

The original child process is genuinely killed (SIGKILL via the public
``child_pid`` property, not ``close()``'s polite SDK-unwind path) before the
second transport resumes it, so this proves resume-after-death, not object
reuse within one process.

Docker-gated: provisions a real npm-installed Pi CLI + pi-acp bridge (via
npx, resolved on demand -- see `resolve_system_pi_acp_argv`) and a real local
GGUF model via the embedded llama-server rig. Per this repo's Docker-test
doctrine, this suite is validated by building and running that image --
never by installing pi-acp / the [acp] extra on the host.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
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

_DOCKER_GATE_ENV = "AUDIAGENTIC_PI_ACP_RESUME_E2E_DOCKER"
_MODEL_PROFILE = "qwen3.5-2b"
_PI_MODEL_REF = "audiagentic/audiagentic-rig"
_TURN_1_PROMPT = "Reply with exactly: OK"
_TURN_2_PROMPT = "Reply with exactly: DONE"


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


def test_real_acp_agent_session_transport_resumes_after_real_process_death(
    tmp_path: Path, monkeypatch
) -> None:
    """Drive AcpAgentSessionTransport.open()/open_resumed() against the real
    pi-acp bridge, across a genuine SIGKILL of the original child."""
    _require_docker_gate()

    from tests.integration.agents.gateway_docker_harness import free_port
    from tests.integration.providers.harness import assert_install_result_ok

    from audiagentic.components.providers.adapters.pi import acp as pi_acp
    from audiagentic.components.providers.services.config.provider_config import (
        patch_provider_config,
    )
    from audiagentic.components.providers.services.lifecycle.lifecycle import install_provider_cli
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.foundation.transports.acp import AcpAgentSessionTransport
    from audiagentic.foundation.transports.agent_session import SessionPrompt
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
        # Both transports share request_runtime_root so --session-dir points
        # at the same persisted location -- the whole point of this proof.
        request_runtime_root = tmp_path / "runtime"

        def _build_launch():
            acp_launch = pi_acp.build_acp_launch(
                project_root, request_runtime_root=request_runtime_root
            )
            import shutil as _shutil

            isolated_agent_dir = Path(acp_launch.environment["PI_CODING_AGENT_DIR"])
            isolated_agent_dir.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(harness_runtime / "agent" / "models.json", isolated_agent_dir / "models.json")
            return acp_launch

        async def _run() -> tuple[bool, int, str]:
            # ── Transport #1: real session/new + one real turn ──────────
            transport_1 = AcpAgentSessionTransport(_build_launch(), cwd=project_root)
            open_result = await transport_1.open()
            provider_session_ref = open_result.ag_session_id

            events_1: list = []

            async def _sink_1(obs):
                events_1.append(obs)

            turn_1 = await transport_1.prompt(
                SessionPrompt(turn_id="turn-1", body=_TURN_1_PROMPT), _sink_1
            )
            assert turn_1.stop_reason == "end_turn", turn_1

            # Genuine hard death -- SIGKILL the real child, not close()'s
            # polite SDK-unwind path. Public child_pid property only.
            child_pid = transport_1._inner.child_pid
            assert child_pid is not None
            os.kill(child_pid, signal.SIGKILL)
            await asyncio.sleep(0.5)  # let the OS reap / SDK notice, best-effort

            # ── Transport #2: brand-new object AND brand-new process,
            # resuming the exact provider_session_ref from transport #1 ──
            transport_2 = AcpAgentSessionTransport(
                _build_launch(), cwd=project_root, resume_provider_ref=provider_session_ref,
            )
            await transport_2.open()

            supports_resume = transport_2._inner.supports_resume
            dropped = transport_2._inner.dropped_between_turns

            events_2: list = []

            async def _sink_2(obs):
                events_2.append(obs)

            turn_2 = await transport_2.prompt(
                SessionPrompt(turn_id="turn-2", body=_TURN_2_PROMPT), _sink_2
            )
            resumed_turn_ok = turn_2.stop_reason == "end_turn"

            await transport_2.close()
            return supports_resume, dropped, ("end_turn" if resumed_turn_ok else turn_2.stop_reason)

        supports_resume, dropped_on_resume, turn_2_stop_reason = asyncio.run(_run())
    finally:
        release_embedded_rig(launch)

    assert supports_resume is True, (
        "real pi-acp bridge did not advertise agent_capabilities.load_session "
        "via AcpSessionTransport.supports_resume"
    )
    assert dropped_on_resume > 0, (
        "expected session/load to replay turn 1's session/update notifications "
        "(counted in dropped_between_turns since no turn pipeline is active "
        "during open()); got 0 -- either the bridge did not truly replay, or "
        "notification counting regressed"
    )
    assert turn_2_stop_reason == "end_turn", (
        f"resumed session's follow-up turn did not complete cleanly: {turn_2_stop_reason!r}"
    )
