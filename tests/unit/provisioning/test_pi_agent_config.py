"""Pi agent config materialization tests — mirror opencode's contribution rendering coverage (HA09)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.harness.pi.install.config import materialize_agent_config


def _harness_cfg() -> dict:
    return {"rig": {"model": "qwen3.5-0.8b", "port": 42001, "provider": "audiagentic"}}


def test_materialize_writes_agents_md_via_contributions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pi materialize invokes the shared provider surface contribution pipeline."""
    project_root = tmp_path / "project"
    target_dir = tmp_path / "target"
    project_root.mkdir()
    target_dir.mkdir()

    calls: list[tuple[Path, str, str]] = []

    def _fake_operate(project_root: Path, provider_id: str, *, mode: str) -> dict:
        calls.append((project_root, provider_id, mode))
        # Simulate the contribution renderer writing AGENTS.md with managed blocks
        (project_root / "AGENTS.md").write_text(
            "<!-- ag:managed:begin -->\n## Agent ledger process\n\nFake content\n<!-- ag:managed:end -->",
            encoding="utf-8",
        )
        return {"ok": True, "written": ["AGENTS.md"]}

    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.operate_provider_surfaces",
        _fake_operate,
    )

    materialize_agent_config(target_dir, _harness_cfg(), project_root=project_root)

    # Verify the contribution pipeline was invoked for pi
    assert calls == [(project_root, "pi", "apply")]
    # AGENTS.md should exist with managed block content
    content = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Agent ledger process" in content


def test_materialize_tolerates_surface_apply_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A surface-apply failure must not break pi config materialization."""
    project_root = tmp_path / "project"
    target_dir = tmp_path / "target"
    project_root.mkdir()
    target_dir.mkdir()

    def _raise(*_args, **_kwargs):
        raise AudiaGenticError(code="CON-SRF-001", kind="providers-surfaces", message="boom")

    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.operate_provider_surfaces",
        _raise,
    )

    materialize_agent_config(target_dir, _harness_cfg(), project_root=project_root)

    # Core files should still be written despite the surface failure
    agent_dir = target_dir / "agent"
    assert (agent_dir / "models.json").exists()
    assert (agent_dir / "settings.json").exists()
    models_data = json.loads((agent_dir / "models.json").read_text(encoding="utf-8"))
    assert "audiagentic" in models_data.get("providers", {})


def test_surface_renderer_registered_for_pi() -> None:
    """Pi has a contribution renderer registered in the surfaces registry."""
    from audiagentic.components.providers.surfaces.registry import (
        load_contribution_renderer_registry,
        load_renderer_registry,
    )

    renderers = load_contribution_renderer_registry()
    assert "pi" in renderers

    skill_renderers = load_renderer_registry()
    assert "pi" in skill_renderers
