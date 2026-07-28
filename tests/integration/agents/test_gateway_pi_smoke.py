"""Real Pi provider dispatch through the gateway's full-isolation worker path.

SH16: Pi's provider descriptor (config/providers/pi.yaml) already declares
``execution_isolation_tier: full-isolation`` and ships a real ACP launch
adapter (adapters/pi/acp.py) for live sessions, but one-shot gateway dispatch
(agent_llm submit/run) does not go through that ACP adapter — it goes through
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
for the CLI (which also seeds the embedded rig binary + model assets when
AUDIAGENTIC_DOCKER_TESTS / pytest is detected — see
runtime/harness/pi/install/__init__.py:_should_provision_embedded_rig), and
write_agent_profile / patch_provider_config for the gateway-facing config.
The only hand-authored file here is the harness's own ag.yaml (rig port/model)
— genuine project-authored config with no creation API, the same status as
gateway-profiles.yaml in gateway_docker_harness.py.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
import yaml
from tests.integration.agents.gateway_docker_harness import free_port, write_agent_profile
from tests.integration.providers.harness import assert_install_result_ok

pytestmark = [
    pytest.mark.integration,
    pytest.mark.opt_in,
    pytest.mark.requires_npm,
    pytest.mark.timeout(900),
]

_DOCKER_GATE_ENV = "AUDIAGENTIC_GATEWAY_PI_SMOKE_DOCKER"
_MODEL_PROFILE = "qwen3.5-0.8b"
_PI_MODEL_REF = "audiagentic/audiagentic-rig"
_PROMPT = "Reply with exactly: OK"


def _require_docker_gate() -> None:
    if os.environ.get(_DOCKER_GATE_ENV) != "1":
        pytest.skip(f"opt-in Docker gate; set {_DOCKER_GATE_ENV}=1")


def _write_harness_config(project_root: Path, rig_port: int) -> None:
    """Genuine operator-authored harness config — no CRUD API exists for it,
    same status as gateway_docker_harness.write_gateway_profiles_config."""
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


def test_gateway_dispatches_real_pi_provider_via_full_isolation_worker(
    tmp_path: Path, monkeypatch
) -> None:
    """Real npm-installed Pi CLI + real embedded rig, dispatched through the
    gateway's disposable full-isolation worker subprocess, reaches a genuine
    completed state via the real ``pi --print --model ...`` CLI invocation."""
    _require_docker_gate()

    from audiagentic.components.agents.agents_gateway_client import (
        get_gateway_client,
        reset_gateway_client,
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
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_MODE", "in-process")

    rig_port = free_port()
    _write_harness_config(tmp_path, rig_port)

    write_agent_profile(
        tmp_path,
        profile_id="pi-smoke",
        provider_id="pi",
        model_id=_PI_MODEL_REF,
        max_concurrency=1,
    )

    # Real npm install of the Pi CLI + pi-mcp-adapter + pi-acp, through the
    # same install_provider_cli path test_provider_prompt_launch_e2e.py and
    # tests/integration/providers/harness.py use for their own clean-room
    # recipe tests. Under AUDIAGENTIC_DOCKER_TESTS=1 (or plain pytest, per
    # _should_provision_embedded_rig) this also downloads real llama-server
    # binaries and seeds/downloads a real local GGUF model — see
    # runtime/harness/pi/install/__init__.py.
    install_result = install_provider_cli("pi", timeout=900, project_root=tmp_path)
    assert_install_result_ok("pi", install_result)

    harness_runtime = global_harness_runtime()
    provision_embedded_rig(harness_runtime, tmp_path)
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

    rig_bin_dir = harness_runtime / "rig" / "bin"
    assert rig_bin_dir.is_dir(), f"Embedded rig bin dir missing after real install: {rig_bin_dir}"

    # The managed-service path is the only shared-rig launch authority. This
    # loads the real GGUF and exposes it through /v1/models for the Pi job.
    launch = start_or_attach_embedded_rig(
        profile_name=_MODEL_PROFILE,
        rig_port=rig_port,
        model_id=_PI_MODEL_REF,
    )
    try:
        reset_gateway_client()
        client = get_gateway_client()
        try:
            result = client.run_llm_request(
                tmp_path,
                agent_profile_id="pi-smoke",
                prompt_body=_PROMPT,
                timeout_seconds=180,
            )
            result = client.wait_llm_request(
                tmp_path,
                result["request-id"],
                timeout_seconds=180,
            )
        finally:
            reset_gateway_client()

        assert result["state"] == "completed", json.dumps(result, indent=2, default=str)
        assert result["provider-id"] == "pi"
        assert (result.get("output") or "").strip(), f"pi produced no output: {result}"
    finally:
        release_embedded_rig(launch)
