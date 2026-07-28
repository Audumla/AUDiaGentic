"""Pi provider config materialization tests via providers_api (HA11).

Replaces old tests that imported from runtime.harness.pi.install — those
packages are deleted as part of HA11. All materialize work now routes through
providers_api.materialize_provider_config.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from audiagentic.components.providers import providers_api


def _harness_cfg() -> dict:
    return {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}


def test_materialize_pi_writes_settings_json(tmp_path: Path) -> None:
    """Pi materialize writes settings.json via providers_api."""
    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    providers_api.materialize_provider_config(
        project_root, "pi", _harness_cfg(), agent_runtime=harness_root
    )

    settings_path = harness_root / "agent" / "settings.json"
    assert settings_path.exists(), "settings.json should be written"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "theme" in data, f"settings.json missing 'theme': {data}"


def test_materialize_pi_copies_append_system_md(tmp_path: Path) -> None:
    """Pi materialize copies APPEND_SYSTEM.md via providers_api."""
    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    providers_api.materialize_provider_config(
        project_root, "pi", _harness_cfg(), agent_runtime=harness_root
    )

    append_md = harness_root / "agent" / "APPEND_SYSTEM.md"
    assert append_md.exists(), "APPEND_SYSTEM.md should be copied"


def test_materialize_pi_removes_stale_system_md(tmp_path: Path) -> None:
    """Pi materialize deletes stale agent/SYSTEM.md via providers_api."""
    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    # Pre-seed a stale SYSTEM.md at agent/ (should be deleted).
    (harness_root / "agent").mkdir(parents=True, exist_ok=True)
    (harness_root / "agent" / "SYSTEM.md").write_text("stale")

    providers_api.materialize_provider_config(
        project_root, "pi", _harness_cfg(), agent_runtime=harness_root
    )

    assert not (harness_root / "agent" / "SYSTEM.md").exists(), (
        "Stale agent/SYSTEM.md should be deleted during Pi materialize"
    )


def test_materialize_pi_applies_provider_surface_contributions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pi materialize invokes operate_provider_surfaces."""
    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    calls: list[tuple] = []

    def _fake_operate(project_root: Path, provider_id: str, *, mode: str) -> dict:
        calls.append((str(project_root), provider_id, mode))
        return {"ok": True, "written": []}

    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.operate_provider_surfaces",
        _fake_operate,
    )

    providers_api.materialize_provider_config(
        project_root, "pi", _harness_cfg(), agent_runtime=harness_root
    )

    assert calls == [(str(project_root), "pi", "apply")]
