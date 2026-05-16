from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.provisioning.rig.embedded.launch import (
    load_model_profiles,
    resolve_model,
    resolve_model_profile,
)

MINIMAL_MODELS = {
    "default": "fast",
    "models": {
        "fast": {
            "aliases": ["quick", "fast-alias"],
            "model_file": "models/fast.gguf",
            "context": 4096,
            "parallel": 1,
            "gpu_layers": "all",
            "fit": "on",
            "reasoning": "off",
            "sampling": {},
            "chat_template_kwargs": {},
        }
    },
}


# ---------------------------------------------------------------------------
# load_model_profiles
# ---------------------------------------------------------------------------

def test_load_model_profiles_raises_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="not found"):
        load_model_profiles(tmp_path / "missing.json")


def test_load_model_profiles_returns_dict(tmp_path: Path) -> None:
    p = _write_models(tmp_path, MINIMAL_MODELS)
    data = load_model_profiles(p)
    assert data["default"] == "fast"


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


def test_resolve_model_profile_by_alias(tmp_path: Path) -> None:
    p = _write_models(tmp_path, MINIMAL_MODELS)
    profile = resolve_model_profile("quick", None, p)
    assert profile.name == "fast"


def test_resolve_model_profile_by_model_file_alias(tmp_path: Path) -> None:
    p = _write_models(tmp_path, MINIMAL_MODELS)
    profile = resolve_model_profile(None, "fast-alias", p)
    assert profile.name == "fast"


def test_resolve_model_profile_raises_when_no_default(tmp_path: Path) -> None:
    data = {"models": MINIMAL_MODELS["models"]}
    p = _write_models(tmp_path, data)
    with pytest.raises(SystemExit, match="No model profile specified"):
        resolve_model_profile(None, None, p)


def test_resolve_model_profile_raises_on_unknown_name(tmp_path: Path) -> None:
    p = _write_models(tmp_path, MINIMAL_MODELS)
    with pytest.raises(SystemExit, match="not found"):
        resolve_model_profile("nonexistent", None, p)


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------

def test_resolve_model_raises_without_override(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="No model file specified"):
        resolve_model(tmp_path, tmp_path, None)


def test_resolve_model_raises_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="Model not found"):
        resolve_model(tmp_path, tmp_path, "missing.gguf")


def test_resolve_model_returns_path_for_existing_file(tmp_path: Path) -> None:
    model_file = tmp_path / "my.gguf"
    model_file.write_bytes(b"")
    path, arg = resolve_model(tmp_path, tmp_path, str(model_file))
    assert path == model_file
    assert arg == str(model_file)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_models(root: Path, data: dict) -> Path:
    path = root / "models.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
