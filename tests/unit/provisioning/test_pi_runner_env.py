from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.provisioning.harness.pi.runner import (
    AgentContext,
    _build_run_env,
    launch_rig_if_needed,
)


def _make_ctx(*, rig_pid: int | None, profile_name: str = "qwen3.5-9b-flash") -> AgentContext:
    base = Path("/tmp/agent-test")
    return AgentContext(
        project_root=base,
        agent_runtime=base / "runtime",
        agent_home=base / "home",
        agent_dir=base / "runtime" / "agent",
        agent_bin=base / "bin" / "pi",
        agent_work=base,
        agent_log_dir=base / "logs",
        endpoint="http://127.0.0.1:42001/v1",
        model="qwen3.5-9b-flash",
        model_profile={},
        profile_name=profile_name,
        provider="audiagentic",
        rig_pid=rig_pid,
        manages_rig=rig_pid is not None,
        enable_mcp=False,
    )


# ---------------------------------------------------------------------------
# _build_run_env
# ---------------------------------------------------------------------------

def test_rig_type_is_embedded_when_rig_launched() -> None:
    env = _build_run_env(_make_ctx(rig_pid=12345))
    assert env["AUDIAGENTIC_RIG_TYPE"] == "embedded"


def test_rig_type_is_external_when_no_rig_pid() -> None:
    env = _build_run_env(_make_ctx(rig_pid=None))
    assert env["AUDIAGENTIC_RIG_TYPE"] == "external"


def test_rig_profile_name_in_env() -> None:
    env = _build_run_env(_make_ctx(rig_pid=None, profile_name="qwen3.5-2b-q4_k_s"))
    assert env["AUDIAGENTIC_RIG_PROFILE"] == "qwen3.5-2b-q4_k_s"


def test_pi_model_in_env() -> None:
    env = _build_run_env(_make_ctx(rig_pid=42))
    assert env["AUDIAGENTIC_AG_MODEL"] == "qwen3.5-9b-flash"
    assert env["AUDIAGENTIC_AG_BASE_URL"] == "http://127.0.0.1:42001/v1"


# ---------------------------------------------------------------------------
# launch_rig_if_needed — external profile (no model_file) skips embedded launch
# ---------------------------------------------------------------------------

def test_external_profile_skips_embedded_launch(monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_AG_BASE_URL", raising=False)
    external_profile: dict = {}
    with patch("audiagentic.provisioning.harness.pi.runner.subprocess.run") as mock_run:
        endpoint, model, rig_pid, manages_rig = launch_rig_if_needed("qwen3.5-9b-flash", "qwen3.5-9b-flash", external_profile)
    mock_run.assert_not_called()
    assert rig_pid is None
    assert manages_rig is False


def test_embedded_profile_launches_rig(monkeypatch) -> None:
    import json
    monkeypatch.delenv("AUDIAGENTIC_AG_BASE_URL", raising=False)
    local_profile: dict = {"model_file": "../../models/my.gguf"}
    fake_result = {"base_url": "http://127.0.0.1:9999/v1", "model": "my.gguf", "pid": 42}

    with patch("audiagentic.provisioning.rig.registry.StartupLock") as mock_lock, \
         patch("audiagentic.provisioning.rig.registry.read_rig_state", return_value=None), \
         patch("audiagentic.provisioning.rig.registry.write_rig_state"), \
         patch("audiagentic.provisioning.harness.pi.runner.subprocess.run") as mock_run:
        mock_lock.return_value.__enter__ = lambda s: s
        mock_lock.return_value.__exit__ = lambda s, *a: None
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(fake_result)
        endpoint, model, rig_pid, manages_rig = launch_rig_if_needed("my.gguf", "local-profile", local_profile)

    mock_run.assert_called_once()
    assert rig_pid == 42
    assert manages_rig is True
    assert endpoint == "http://127.0.0.1:9999/v1"
