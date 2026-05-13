"""Validates that the correct rig launch path is taken for each model profile.

Root-cause test: qwen3.5-9b-flash has no model_file → must not launch embedded rig.
                 qwen3.5-2b-q4_k_s has model_file       → must launch embedded rig.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.provisioning.harness.pi.runner import launch_rig_if_needed, load_model_profile
from audiagentic.provisioning.rig.embedded.launch import (
    ensure_under,
    repo_root,
    resolve_under,
    runtime_bin_dir,
)

# ---------------------------------------------------------------------------
# Real models.json — profile shape assertions
# ---------------------------------------------------------------------------

def test_9b_flash_profile_has_model_file() -> None:
    _, profile = load_model_profile("qwen3.5-9b-flash", "qwen3.5-9b-flash")
    assert profile.get("model_file"), (
        "qwen3.5-9b-flash must have model_file pointing to the local GGUF"
    )


def test_2b_profile_has_model_file() -> None:
    _, profile = load_model_profile("qwen3.5-2b-q4_k_s", "qwen3.5-2b-q4_k_s")
    assert profile.get("model_file"), (
        "qwen3.5-2b-q4_k_s must have model_file — it runs as embedded rig"
    )


# ---------------------------------------------------------------------------
# launch_rig_if_needed routing — using real profile dicts
# ---------------------------------------------------------------------------

def test_9b_flash_attempts_embedded_launch(monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_PI_BASE_URL", raising=False)
    _, profile = load_model_profile("qwen3.5-9b-flash", "qwen3.5-9b-flash")
    fake_payload = {"base_url": "http://127.0.0.1:9999/v1", "model": "Qwen3.5-9B.gguf", "pid": 77}
    with patch("audiagentic.provisioning.harness.pi.runner.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(fake_payload)
        _, _, rig_pid = launch_rig_if_needed("qwen3.5-9b-flash", "qwen3.5-9b-flash", profile)
    mock_run.assert_called_once()
    assert rig_pid == 77


def test_2b_profile_attempts_embedded_launch(monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_PI_BASE_URL", raising=False)
    _, profile = load_model_profile("qwen3.5-2b-q4_k_s", "qwen3.5-2b-q4_k_s")
    fake_payload = {"base_url": "http://127.0.0.1:9999/v1", "model": "Qwen.gguf", "pid": 99}
    with patch("audiagentic.provisioning.harness.pi.runner.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(fake_payload)
        _, _, rig_pid = launch_rig_if_needed("qwen3.5-2b-q4_k_s", "qwen3.5-2b-q4_k_s", profile)
    mock_run.assert_called_once()
    assert rig_pid == 99


def test_2b_launch_command_passes_model_profile(monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_PI_BASE_URL", raising=False)
    _, profile = load_model_profile("qwen3.5-2b-q4_k_s", "qwen3.5-2b-q4_k_s")
    fake_payload = {"base_url": "http://127.0.0.1:9999/v1", "model": "Qwen.gguf", "pid": 99}
    with patch("audiagentic.provisioning.harness.pi.runner.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(fake_payload)
        launch_rig_if_needed("qwen3.5-2b-q4_k_s", "qwen3.5-2b-q4_k_s", profile)
    cmd = mock_run.call_args[0][0]
    assert "--model-profile" in cmd
    assert "qwen3.5-2b-q4_k_s" in cmd


# ---------------------------------------------------------------------------
# Model file path safety — ensure_under accepts 2b path relative to bin_dir
# ---------------------------------------------------------------------------

def _assert_model_file_within_bin_dir(profile_name: str) -> None:
    root = repo_root()
    bin_dir = runtime_bin_dir(root)
    _, profile = load_model_profile(profile_name, profile_name)
    model_file = profile["model_file"]
    assert isinstance(model_file, str)
    server_dir = bin_dir / "llama-server" / "windows"
    candidate = resolve_under(root, model_file, base=server_dir)
    assert candidate is not None
    result = ensure_under(candidate, bin_dir, "model_file")
    assert result == candidate


def test_2b_model_file_resolves_within_bin_dir() -> None:
    _assert_model_file_within_bin_dir("qwen3.5-2b-q4_k_s")


def test_9b_model_file_resolves_within_bin_dir() -> None:
    _assert_model_file_within_bin_dir("qwen3.5-9b-flash")
