"""Validate embedded rig routing through canonical rig model config."""
from __future__ import annotations

import json
from unittest.mock import patch

from audiagentic.runtime.harness.pi.runner import launch_rig_if_needed, load_model_profile
from audiagentic.runtime.rig.embedded.launch import (
    ensure_under,
    load_rig_model,
    resolve_profile_definition,
    resolve_under,
    runtime_bin_dir,
)


def _rig_target() -> tuple[str, str, dict[str, object]]:
    profile_name, model_id = load_rig_model()
    resolved_name, profile = load_model_profile(model_id, model_id)
    assert resolved_name == profile_name
    assert profile == resolve_profile_definition(profile_name)
    return model_id, profile_name, profile


def test_rig_model_profile_has_model_file() -> None:
    _, profile_name, profile = _rig_target()
    assert profile.get("model_file"), f"{profile_name} must define model_file"


def test_rig_model_extends_mtp_base() -> None:
    _, profile_name, _ = _rig_target()
    profile = resolve_profile_definition(profile_name)
    server = profile.get("server", {})
    assert isinstance(server, dict)
    assert server.get("spec_type") == "draft-mtp"


def test_rig_model_attempts_embedded_launch(monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_AG_BASE_URL", raising=False)
    model_id, profile_name, profile = _rig_target()
    fake_payload = {"base_url": "http://127.0.0.1:9999/v1", "model": "Qwen.gguf", "pid": 77}
    with patch("audiagentic.runtime.rig.registry.StartupLock") as mock_lock, \
         patch("audiagentic.runtime.rig.registry.ensure_rig_state", return_value=None), \
         patch("audiagentic.runtime.rig.registry.write_rig_state"), \
         patch("audiagentic.runtime.rig.registry.reap_orphan_rigs"), \
         patch("audiagentic.runtime.harness.pi.runner.rig.subprocess.run") as mock_run:
        mock_lock.return_value.__enter__ = lambda s: s
        mock_lock.return_value.__exit__ = lambda s, *a: None
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(fake_payload)
        _, _, rig_pid, _ = launch_rig_if_needed(model_id, profile_name, profile, 9999)
    mock_run.assert_called_once()
    assert rig_pid == 77


def test_rig_launch_command_passes_resolved_profile(monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_AG_BASE_URL", raising=False)
    model_id, profile_name, profile = _rig_target()
    fake_payload = {"base_url": "http://127.0.0.1:9999/v1", "model": "Qwen.gguf", "pid": 99}
    with patch("audiagentic.runtime.rig.registry.StartupLock") as mock_lock, \
         patch("audiagentic.runtime.rig.registry.ensure_rig_state", return_value=None), \
         patch("audiagentic.runtime.rig.registry.write_rig_state"), \
         patch("audiagentic.runtime.rig.registry.reap_orphan_rigs"), \
         patch("audiagentic.runtime.harness.pi.runner.rig.subprocess.run") as mock_run:
        mock_lock.return_value.__enter__ = lambda s: s
        mock_lock.return_value.__exit__ = lambda s, *a: None
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(fake_payload)
        launch_rig_if_needed(model_id, profile_name, profile, 9999)
    cmd = mock_run.call_args[0][0]
    assert "--model-profile" in cmd
    assert profile_name in cmd


def test_rig_model_file_resolves_within_bin_dir() -> None:
    _, _, profile = _rig_target()
    bin_dir = runtime_bin_dir()
    model_file = profile["model_file"]
    assert isinstance(model_file, str)
    server_dir = bin_dir / "llama-server" / "windows"
    candidate = resolve_under(bin_dir, model_file, base=server_dir)
    assert candidate is not None
    result = ensure_under(candidate, bin_dir, "model_file")
    assert result == candidate
