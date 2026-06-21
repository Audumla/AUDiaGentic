from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.rig.embedded.config import load_rig_profiles, resolve_model_profile
from audiagentic.runtime.rig.embedded.launch import resolve_model, runtime_bin_dir
from audiagentic.runtime.rig.embedded.process import build_command

MINIMAL_MODELS = {
    "rig_model": {
        "profile": "fast",
        "model_id": "audiagentic-rig",
    },
    "profile_settings": {
        "base_fast": {
            "server": {
                "parallel": 1,
                "gpu_layers": "all",
                "fit": "on",
                "reasoning": "off",
                "context_size": 4096,
            },
            "agent": {
                "reasoning": False,
                "max_tokens": 2048,
            },
        }
    },
    "models": {
        "fast": {
            "extends": ["base_fast"],
            "model_file": "models/fast.gguf",
            "prompt": {
                "chat_template": {},
            },
        }
    },
}


# ---------------------------------------------------------------------------
# load_rig_profiles
# ---------------------------------------------------------------------------

def test_load_rig_profiles_raises_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError, match="not found"):
        load_rig_profiles(tmp_path / "missing.yaml")


def test_load_rig_profiles_returns_dict(tmp_path: Path) -> None:
    p = _write_models(tmp_path, MINIMAL_MODELS)
    data = load_rig_profiles(p)
    assert data["rig_model"]["profile"] == "fast"


# ---------------------------------------------------------------------------
# resolve_model_profile
# ---------------------------------------------------------------------------

def test_resolve_model_profile_uses_config_default(tmp_path: Path) -> None:
    p = _write_models(tmp_path, MINIMAL_MODELS)
    profile = resolve_model_profile(None, None, p)
    assert profile.name == "fast"


def test_resolve_model_profile_by_explicit_name(tmp_path: Path) -> None:
    p = _write_models(tmp_path, MINIMAL_MODELS)
    profile = resolve_model_profile("fast", None, p)
    assert profile.name == "fast"


def test_resolve_model_profile_by_rig_model_id(tmp_path: Path) -> None:
    p = _write_models(tmp_path, MINIMAL_MODELS)
    profile = resolve_model_profile("audiagentic-rig", None, p)
    assert profile.name == "fast"


def test_resolve_model_profile_by_model_file_name(tmp_path: Path) -> None:
    p = _write_models(tmp_path, MINIMAL_MODELS)
    profile = resolve_model_profile(None, "fast.gguf", p)
    assert profile.name == "fast"


def test_resolve_model_profile_raises_when_no_rig_model(tmp_path: Path) -> None:
    data = {"profile_settings": MINIMAL_MODELS["profile_settings"], "models": MINIMAL_MODELS["models"]}
    p = _write_models(tmp_path, data)
    with pytest.raises(AudiaGenticError, match="rig_model"):
        resolve_model_profile(None, None, p)


def test_resolve_model_profile_raises_on_unknown_name(tmp_path: Path) -> None:
    p = _write_models(tmp_path, MINIMAL_MODELS)
    with pytest.raises(AudiaGenticError, match="not found"):
        resolve_model_profile("nonexistent", None, p)


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------

def test_resolve_model_raises_without_override(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError, match="No model file specified"):
        resolve_model(tmp_path, tmp_path, None)


def test_resolve_model_raises_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError, match="Model not found"):
        resolve_model(tmp_path, tmp_path, "missing.gguf")


def test_resolve_model_returns_path_for_existing_file(tmp_path: Path) -> None:
    model_file = tmp_path / "my.gguf"
    model_file.write_bytes(b"")
    path, arg = resolve_model(tmp_path, tmp_path, str(model_file))
    assert path == model_file
    assert arg == str(model_file)


def test_build_command_passes_through_unknown_server_args(tmp_path: Path) -> None:
    binary = tmp_path / "llama-server"
    cmd = build_command(
        binary=binary,
        model_arg="models/test.gguf",
        host="127.0.0.1",
        port=42001,
        device=None,
        server_cfg={"spec_type": "draft-mtp", "context_size": 4096},
        chat_template_kwargs={},
        alias=None,
    )
    assert "--spec-type" in cmd
    assert "draft-mtp" in cmd


def test_runtime_bin_dir_prefers_project_provisioning_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    project_bin = project_root / ".audiagentic" / "provisioning" / "rig" / "embedded" / "bin"
    project_bin.mkdir(parents=True)
    global_bin = tmp_path / "home" / "harness" / "rig" / "bin"
    global_bin.mkdir(parents=True)
    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "home"))
    assert runtime_bin_dir() == project_bin


def test_runtime_bin_dir_falls_back_when_project_bin_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_bin = tmp_path / "home" / "harness" / "rig" / "bin"
    global_bin.mkdir(parents=True)
    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(Path(os.sep) / "missing-project-root"))
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "home"))
    path = runtime_bin_dir()
    assert path == global_bin


def test_resolve_model_falls_back_to_global_model_when_local_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_server_dir = project_root / ".audiagentic" / "provisioning" / "rig" / "embedded" / "bin" / "llama-server" / "windows"
    project_server_dir.mkdir(parents=True)
    global_model = tmp_path / "home" / "harness" / "rig" / "bin" / "models" / "fast.gguf"
    global_model.parent.mkdir(parents=True)
    global_model.write_bytes(b"gguf")

    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "home"))

    resolved_path, model_arg = resolve_model(
        project_root / ".audiagentic" / "provisioning" / "rig" / "embedded" / "bin",
        project_server_dir,
        "../../models/fast.gguf",
    )

    assert resolved_path == global_model
    assert model_arg == str(global_model)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_models(root: Path, data: dict) -> Path:
    path = root / "rig.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path
