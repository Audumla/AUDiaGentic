from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers import providers_api


def _harness_cfg() -> dict:
    return {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}


def test_materialize_agent_config_writes_agents_md_template(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    providers_api.materialize_provider_config(project_root, "opencode", _harness_cfg())

    content = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Project instructions" in content
    assert "Prompt tag doctrine" in content


def test_materialize_agent_config_applies_provider_surface_contributions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OpenCode materialization applies contributions after project-scope filtering."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    calls: list[tuple[Path, str, str]] = []

    def _fake_operate(project_root: Path, provider_id: str, *, mode: str) -> dict:
        calls.append((project_root, provider_id, mode))
        return {"ok": True, "written": []}

    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.operate_provider_surfaces",
        _fake_operate,
    )

    providers_api.materialize_provider_config(project_root, "opencode", _harness_cfg())

    assert calls == [(project_root, "opencode", "apply")]
    # AGENTS.md template write must still happen regardless of surface apply.
    assert (project_root / "AGENTS.md").exists()
