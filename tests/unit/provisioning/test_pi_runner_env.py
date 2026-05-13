from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.provisioning.harness.pi.runner import (
    PiContext,
    _build_run_env,
    launch_rig_if_needed,
)


def _make_ctx(*, rig_pid: int | None, profile_name: str = "qwen3.5-9b-flash") -> PiContext:
    base = Path("/tmp/pi-test")
    return PiContext(
        project_root=base,
        pi_runtime=base / "runtime",
        pi_home=base / "home",
        pi_agent_dir=base / "runtime" / "agent",
        pi_bin=base / "bin" / "pi",
        pi_work=base,
        pi_log_dir=base / "logs",
        endpoint="http://127.0.0.1:42001/v1",
        model="qwen3.5-9b-flash",
        model_profile={},
        profile_name=profile_name,
        provider="audiagentic",
        rig_pid=rig_pid,
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
    assert env["AUDIAGENTIC_PI_MODEL"] == "qwen3.5-9b-flash"
    assert env["AUDIAGENTIC_PI_BASE_URL"] == "http://127.0.0.1:42001/v1"


# ---------------------------------------------------------------------------
# launch_rig_if_needed — external profile (no model_file) skips embedded launch
# ---------------------------------------------------------------------------

def test_external_profile_skips_embedded_launch(monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_PI_BASE_URL", raising=False)
    external_profile: dict = {}
    with patch("audiagentic.provisioning.harness.pi.runner.subprocess.run") as mock_run:
        endpoint, model, rig_pid = launch_rig_if_needed("qwen3.5-9b-flash", "qwen3.5-9b-flash", external_profile)
    mock_run.assert_not_called()
    assert rig_pid is None


def test_embedded_profile_launches_rig(monkeypatch) -> None:
    import json
    monkeypatch.delenv("AUDIAGENTIC_PI_BASE_URL", raising=False)
    local_profile: dict = {"model_file": "../../models/my.gguf"}
    fake_result = {"base_url": "http://127.0.0.1:9999/v1", "model": "my.gguf", "pid": 42}

    with patch("audiagentic.provisioning.harness.pi.runner.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(fake_result)
        endpoint, model, rig_pid = launch_rig_if_needed("my.gguf", "local-profile", local_profile)

    mock_run.assert_called_once()
    assert rig_pid == 42
    assert endpoint == "http://127.0.0.1:9999/v1"
