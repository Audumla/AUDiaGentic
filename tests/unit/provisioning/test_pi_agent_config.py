"""Pi agent config materialization tests — mirror opencode's contribution rendering coverage (HA09)."""

from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers import providers_api
from audiagentic.foundation.contracts.errors import AudiaGenticError


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

    providers_api.materialize_provider_config(
        project_root, "pi", _harness_cfg(), agent_runtime=target_dir
    )

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

    providers_api.materialize_provider_config(
        project_root, "pi", _harness_cfg(), agent_runtime=target_dir
    )

    # Core files should still be written despite the surface failure
    # (model config goes through model-projection family, not materialize)
    agent_dir = target_dir / "agent"
    assert (agent_dir / "settings.json").exists()


@pytest.mark.no_parallel
def test_surface_renderer_registered_for_pi() -> None:
    """Pi has a contribution renderer registered in the surfaces registry.

    Reads the process-wide surfaces registry with no isolation of its own, so
    it cannot share a worker with anything that resets registries — which
    ``tests/unit/foundation`` does before every one of its tests. Pi registers
    its renderer from a custom ``surface.py`` at import time, and that
    registration is not restored by the post-reset repopulation path, so a
    reset on the same worker leaves pi permanently missing.
    """
    from audiagentic.components.providers.surfaces.registry import (
        load_contribution_renderer_registry,
        load_renderer_registry,
    )

    renderers = load_contribution_renderer_registry()
    assert "pi" in renderers

    skill_renderers = load_renderer_registry()
    assert "pi" in skill_renderers
