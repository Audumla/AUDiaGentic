from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.harness.opencode.install import materialize_agent_config


def _harness_cfg() -> dict:
    return {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}


def test_materialize_agent_config_writes_agents_md_template(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    materialize_agent_config(project_root, _harness_cfg(), project_root=project_root)

    content = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Project instructions" in content
    assert "Prompt tag doctrine" in content


def test_materialize_agent_config_applies_provider_surface_contributions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The previously-unused opencode surface renderer is now actually invoked."""
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

    materialize_agent_config(project_root, _harness_cfg(), project_root=project_root)

    assert calls == [(project_root, "opencode", "apply")]
    # AGENTS.md template write must still happen regardless.
    assert (project_root / "AGENTS.md").exists()


def test_materialize_agent_config_tolerates_surface_apply_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A surface-apply failure must not break config materialization."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    def _raise(*_args, **_kwargs):
        raise AudiaGenticError(code="CON-SRF-001", kind="providers-surfaces", message="boom")

    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.operate_provider_surfaces",
        _raise,
    )

    materialize_agent_config(project_root, _harness_cfg(), project_root=project_root)

    assert (project_root / "AGENTS.md").exists()
    assert (project_root / ".opencode" / "config.json").exists()
