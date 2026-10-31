"""Real Pi provider dispatch through the gateway's full-isolation worker path.

SH16: Pi's provider descriptor (config/providers/pi.yaml) already declares
``execution_isolation_tier: full-isolation`` and ships a real ACP launch
adapter (adapters/pi/acp.py) for live sessions, but one-shot gateway dispatch
(agent_execution submit/run) does not go through that ACP adapter — it goes through
the shared YAML-driven CLI runner (adapters/base_runner.make_cli_runner)
declared in pi.yaml's ``execution:`` block, which invokes the real ``pi``
binary directly (``pi --print --model <model> <prompt>``).

This suite proves that one-shot path end-to-end, with nothing mocked:
  - a real npm-installed Pi CLI (via the same install_provider_cli path every
    other CLI-based provider recipe in this repo uses)
  - a real embedded llama-server rig serving a real local GGUF model — no
    external API keys, no fake HTTP rig
  - dispatched through the gateway's disposable full-isolation worker
    subprocess (agents_gateway_worker.execute_isolated_provider_turn, the
    same mechanism test_gateway_opencode_docker.py exercises for opencode)
  - reaching a genuine "completed" terminal state with real model output.

Provisioning reuses AUDiaGentic's own real APIs throughout: install_provider_cli
for the CLI, and write_execution_profile / patch_provider_config for the
gateway-facing config. The model is a real llama-server that the test-only
tests/helpers/model_server.py downloads and starts (AUDiaGentic never hosts one).
The only hand-authored file here is the harness's own ag.yaml (rig port/model)
— genuine project-authored config with no creation API, the same status as
    the canonical global agents catalog.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
import yaml
from tests.helpers.gateway_settings import use_gateway_settings
from tests.integration.agents.gateway_docker_harness import free_port, write_execution_profile
from tests.integration.providers.harness import assert_install_result_ok

pytestmark = [
    pytest.mark.integration,
    pytest.mark.opt_in,
    pytest.mark.mutates_host,
    pytest.mark.requires_npm,
    pytest.mark.timeout(480),
]

_DOCKER_GATE_ENV = "AUDIAGENTIC_GATEWAY_PI_SMOKE_DOCKER"
# Use the same provisioned model as the passing full-turn RPC transcript
# fixture; the 0.8B model repeatedly kept generating instead of ending turns.
_MODEL_PROFILE = "qwen3.5-2b"
_PI_MODEL_REF = "audiagentic/audiagentic-rig"
_PROMPT = "Reply with exactly: OK"


def _require_docker_gate() -> None:
    if os.environ.get(_DOCKER_GATE_ENV) != "1":
        pytest.skip(f"opt-in Docker gate; set {_DOCKER_GATE_ENV}=1")


def _write_harness_config(project_root: Path, rig_port: int) -> None:
    """Genuine operator-authored harness config — no CRUD API exists for it,
    same status as the canonical global agents catalog."""
    config_root = project_root / ".audiagentic" / "config" / "harness"
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "ag.yaml").write_text(
        yaml.safe_dump(
            {
                "harness": {"type": "pi"},
                "endpoint": {"url": f"http://127.0.0.1:{rig_port}/v1", "model": _MODEL_PROFILE, "provider": "audiagentic"},
                "mcp": {"enabled": False},
                "smoke": {"timeout": 60},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_gateway_dispatches_real_pi_provider_via_full_isolation_worker(
    tmp_path: Path, monkeypatch
) -> None:
    """Real npm-installed Pi CLI + real embedded rig, dispatched through the
    gateway's disposable full-isolation worker subprocess, reaches a genuine
    completed state via the real ``pi --print --model ...`` CLI invocation."""
    _require_docker_gate()

    from tests.helpers.model_server import start_model_server

    from audiagentic.components.agents.gateway.client import (
        get_gateway_client,
        reset_gateway_client,
    )
    from audiagentic.components.providers.services.config.provider_config import (
        patch_provider_config,
    )
    from audiagentic.components.providers.services.lifecycle.lifecycle import install_provider_cli
    from audiagentic.foundation.paths.home import global_harness_runtime
    from audiagentic.runtime.harness import refresh_materialized_agent_config

    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(tmp_path))
    use_gateway_settings(monkeypatch, tmp_path, implementation="embedded")

    rig_port = free_port()
    _write_harness_config(tmp_path, rig_port)

    write_execution_profile(
        tmp_path,
        profile_id="pi-smoke",
        provider_id="pi",
        model_id=_PI_MODEL_REF,
        virtual_capacity=1,
    )

    # Real npm install of the Pi CLI + pi-mcp-adapter + pi-acp, through the
    # same install_provider_cli path test_provider_prompt_launch_e2e.py and
    # tests/integration/providers/harness.py use for their own clean-room
    # recipe tests. The model it talks to is a real llama-server that
    # tests/helpers/model_server.py downloads and starts below (test-only;
    # AUDiaGentic itself never hosts a model).
    # Installation must remain a real lifecycle operation, but a hung npm
    # registry/process must not consume the whole Docker gate.  The image
    # caches Python and model-server assets; it intentionally does not
    # pre-install Pi, so this call continues to exercise clean provider
    # installation.
    install_result = install_provider_cli("pi", timeout=300, project_root=tmp_path)
    assert_install_result_ok("pi", install_result)
    from tests.helpers.pi_smoke import restrict_smoke_pi

    restrict_smoke_pi(tmp_path, monkeypatch)

    harness_runtime = global_harness_runtime()
    refresh_materialized_agent_config(harness_runtime, project_root=tmp_path)
    # Provider lifecycle installs the harness in the system npm prefix.  The
    # runtime intentionally no longer carries a second embedded CLI copy.
    assert shutil.which("pi") is not None, "system Pi executable not resolvable after real install"

    # The gateway's full-isolation worker copies models.json from
    # PI_CODING_AGENT_DIR (agents_gateway_worker._replacement_environment)
    # into its private isolated home — point it at the registry
    # materialize_agent_config just wrote during install, exactly what a
    # real Pi install leaves behind.
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

    # A real GGUF served at the configured port, exposed through /v1/models for the Pi job.
    server = start_model_server(_PI_MODEL_REF, port=rig_port)
    try:
        reset_gateway_client()
        client = get_gateway_client()
        try:
            result = client.run_execution_request(
                tmp_path,
                execution_profile_id="pi-smoke",
                prompt_body=_PROMPT,
            )
            if result.get("state") not in {"completed", "failed", "cancelled", "interrupted"}:
                # Real CPU model generation may outlive the initial caller
                # wait. Continue observing the same ID, never resubmit.
                result = client.wait_execution_request(tmp_path, result["request-id"], timeout_seconds=180)
            assert result.get("wait-outcome") != "timeout", json.dumps(result, indent=2, default=str)
        finally:
            reset_gateway_client()

        assert result["state"] == "completed", json.dumps(result, indent=2, default=str)
        assert result["provider-id"] == "pi"
        assert (result.get("output") or "").strip(), f"pi produced no output: {result}"
    finally:
        server.stop()
