from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.runtime.harness.pi.runner import AgentContext, _build_run_env, launch_rig_if_needed
from audiagentic.runtime.rig.embedded.launch import load_rig_model

RIG_PROFILE, RIG_MODEL_ID = load_rig_model()


def _make_ctx(
    *,
    rig_pid: int | None,
    profile_name: str = RIG_PROFILE,
    manages_rig: bool | None = None,
) -> AgentContext:
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
        model=RIG_MODEL_ID,
        model_profile={},
        profile_name=profile_name,
        provider="audiagentic",
        rig_pid=rig_pid,
        manages_rig=rig_pid is not None if manages_rig is None else manages_rig,
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


def test_rig_type_is_embedded_when_reusing_existing_rig() -> None:
    env = _build_run_env(_make_ctx(rig_pid=None, manages_rig=True))
    assert env["AUDIAGENTIC_RIG_TYPE"] == "embedded"


def test_rig_profile_name_in_env() -> None:
    env = _build_run_env(_make_ctx(rig_pid=None, profile_name=RIG_PROFILE))
    assert env["AUDIAGENTIC_RIG_PROFILE"] == RIG_PROFILE


def test_pi_model_in_env() -> None:
    env = _build_run_env(_make_ctx(rig_pid=42))
    assert env["AUDIAGENTIC_AG_MODEL"] == RIG_MODEL_ID
    assert env["AUDIAGENTIC_AG_BASE_URL"] == "http://127.0.0.1:42001/v1"


# ---------------------------------------------------------------------------
# launch_rig_if_needed — external profile (no model_file) skips embedded launch
# ---------------------------------------------------------------------------

def test_external_profile_skips_embedded_launch(monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_AG_BASE_URL", raising=False)
    external_profile: dict = {}
    with patch("audiagentic.runtime.harness.pi.runner.smoke.subprocess.run") as mock_run:
        endpoint, model, rig_pid, manages_rig = launch_rig_if_needed(RIG_MODEL_ID, RIG_PROFILE, external_profile, 9999)
    mock_run.assert_not_called()
    assert rig_pid is None
    assert manages_rig is False


def test_embedded_profile_launches_rig(monkeypatch) -> None:
    import json
    monkeypatch.delenv("AUDIAGENTIC_AG_BASE_URL", raising=False)
    local_profile: dict = {"model_file": "../../models/my.gguf"}
    fake_result = {"base_url": "http://127.0.0.1:9999/v1", "model": "my.gguf", "pid": 42}

    with patch("audiagentic.runtime.rig.registry.StartupLock") as mock_lock, \
         patch("audiagentic.runtime.rig.registry.ensure_rig_state", return_value=None), \
         patch("audiagentic.runtime.rig.registry.write_rig_state"), \
         patch("audiagentic.runtime.rig.registry.reap_orphan_rigs"), \
         patch("audiagentic.runtime.harness.pi.runner.rig.subprocess.run") as mock_run:
        mock_lock.return_value.__enter__ = lambda s: s
        mock_lock.return_value.__exit__ = lambda s, *a: None
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(fake_result)
        endpoint, model, rig_pid, manages_rig = launch_rig_if_needed("my.gguf", "local-profile", local_profile, 9999)

    mock_run.assert_called_once()
    assert rig_pid == 42
    assert manages_rig is True


def test_rig_model_id_resolves_to_embedded_profile(monkeypatch) -> None:
    import json
    monkeypatch.delenv("AUDIAGENTIC_AG_BASE_URL", raising=False)
    local_profile: dict = {"model_file": "../../models/my.gguf"}
    fake_result = {"base_url": "http://127.0.0.1:9999/v1", "model": "my.gguf", "pid": 42}

    with patch("audiagentic.runtime.rig.registry.StartupLock") as mock_lock, \
         patch("audiagentic.runtime.rig.registry.ensure_rig_state", return_value=None), \
         patch("audiagentic.runtime.rig.registry.write_rig_state"), \
         patch("audiagentic.runtime.rig.registry.reap_orphan_rigs"), \
         patch("audiagentic.runtime.harness.pi.runner.rig.subprocess.run") as mock_run:
        mock_lock.return_value.__enter__ = lambda s: s
        mock_lock.return_value.__exit__ = lambda s, *a: None
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(fake_result)
        endpoint, model, rig_pid, manages_rig = launch_rig_if_needed(RIG_MODEL_ID, RIG_PROFILE, local_profile, 9999)

    mock_run.assert_called_once()
    assert endpoint == "http://127.0.0.1:9999/v1"
    assert model == RIG_MODEL_ID
    assert rig_pid == 42
    assert manages_rig is True
    assert endpoint == "http://127.0.0.1:9999/v1"


def test_embedded_profile_reuses_adopted_rig(monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_AG_BASE_URL", raising=False)
    local_profile: dict = {"model_file": "../../models/my.gguf"}
    adopted = {
        "pid": 99,
        "port": 9999,
        "endpoint": "http://127.0.0.1:9999/v1",
        "model": "local-profile",
    }

    with patch("audiagentic.runtime.rig.registry.StartupLock") as mock_lock, \
         patch("audiagentic.runtime.rig.registry.ensure_rig_state", return_value=adopted), \
         patch("audiagentic.runtime.rig.registry.reap_orphan_rigs") as mock_reap, \
         patch("audiagentic.runtime.harness.pi.runner.rig.subprocess.run") as mock_run:
        mock_lock.return_value.__enter__ = lambda s: s
        mock_lock.return_value.__exit__ = lambda s, *a: None
        endpoint, model, rig_pid, manages_rig = launch_rig_if_needed(
            "my.gguf", "local-profile", local_profile, 9999
        )

    mock_run.assert_not_called()
    mock_reap.assert_not_called()
    assert endpoint == "http://127.0.0.1:9999/v1"
    assert model == RIG_MODEL_ID
    assert rig_pid is None
    assert manages_rig is True

