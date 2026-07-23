"""Descriptor-driven surface renderer factory (AR03).

The pure-template surface.py adapters were deleted; their rendering now comes
from make_standard_surface_renderer driven by the descriptor's ``surfaces:``
block. These tests pin the rendered shapes and prove a YAML-only provider
gets working surface rendering with zero adapter Python.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.adapters import _register_standard_surfaces
from audiagentic.components.providers.descriptors.base import ProviderDescriptor
from audiagentic.components.providers.surfaces.base import (
    SkillDefinition,
    SurfaceContribution,
    make_standard_surface_renderer,
)
from audiagentic.components.providers.surfaces.registry import (
    load_contribution_renderer_registry,
    load_renderer_registry,
)
from audiagentic.foundation.registry_utils import reset_all_registries

_SKILL = SkillDefinition(
    tag="jobs",
    name="jobs",
    description="Job control",
    title="Jobs skill",
    trigger=["run a job"],
    do=["use tags"],
    dont=["freelance"],
)


def test_yaml_driven_providers_have_renderers():
    """Every provider whose surface.py was deleted still has both renderers."""
    renderers = load_renderer_registry()
    contribs = load_contribution_renderer_registry()
    for pid in ("gemini", "qwen", "copilot", "goose", "plandex", "openhands"):
        assert pid in renderers, f"no surface renderer for {pid}"
        assert pid in contribs, f"no contribution renderer for {pid}"


def test_surface_registry_shared_loader_repopulates_both_registries():
    reset_all_registries()

    renderers = load_renderer_registry()
    contribs = load_contribution_renderer_registry()

    assert "gemini" in renderers
    assert "plandex" in contribs


def test_flat_skill_renderer_matches_previous_adapter_output(tmp_path: Path):
    """The factory reproduces the exact output of the deleted gemini surface.py."""
    render = load_renderer_registry()["gemini"]
    out = render(project_root=tmp_path, syntax={}, skills=[_SKILL], config={"path": ".x/skills/{tag}.md"})
    # agent-jobs inactive in tmp project -> skill file only, no GEMINI.md
    assert set(out) == {tmp_path / ".x" / "skills" / "jobs.md"}
    content = out[tmp_path / ".x" / "skills" / "jobs.md"]
    assert "Provider surface: `gemini`" in content
    assert "Launch example: `@jobs-gemini`" in content


def test_none_renderer_renders_no_skill_surfaces(tmp_path: Path):
    render = load_renderer_registry()["goose"]
    assert render(project_root=tmp_path, syntax={}, skills=[_SKILL], config={"path": "x/{tag}.md"}) == {}


def test_contribution_file_from_descriptor(tmp_path: Path):
    render = load_contribution_renderer_registry()["plandex"]
    blocks = render(
        project_root=tmp_path,
        contributions=[
            SurfaceContribution(contribution_id="t/1", owner_component="t", title="T", body="B")
        ],
    )
    assert [b.path for b in blocks] == [tmp_path / "AGENTS.md"]


def test_new_provider_needs_only_yaml(tmp_path: Path):
    """A provider defined purely by descriptor data gets working rendering."""
    # Complete lazy canonical loading before adding the test-only descriptor;
    # otherwise the first read correctly rebuilds both registries and removes
    # values that were never part of provider discovery.
    load_renderer_registry()
    load_contribution_renderer_registry()
    descriptor = ProviderDescriptor(
        provider_id="fixture-prov",
        display_name="Fixture Provider",
        instruction_file="FIXTURE.md",
        surfaces={"renderer": "flat-skill", "contribution-file": "FIXTURE.md"},
    )
    _register_standard_surfaces(descriptor)

    render = load_renderer_registry()["fixture-prov"]
    out = render(project_root=tmp_path, syntax={}, skills=[_SKILL], config={"path": "s/{tag}.md"})
    assert "Launch example: `@jobs-fixture-prov`" in out[tmp_path / "s" / "jobs.md"]

    contrib_render = load_contribution_renderer_registry()["fixture-prov"]
    blocks = contrib_render(
        project_root=tmp_path,
        contributions=[
            SurfaceContribution(contribution_id="t/1", owner_component="t", title="T", body="B")
        ],
    )
    assert blocks[0].path == tmp_path / "FIXTURE.md"


def test_custom_surface_module_wins_over_descriptor_block(tmp_path: Path):
    """_register_standard_surfaces never overwrites an existing registration."""
    from audiagentic.components.providers.surfaces.registry import register_renderer

    sentinel = make_standard_surface_renderer("sentinel-prov", style="none")
    register_renderer("sentinel-prov", sentinel)
    descriptor = ProviderDescriptor(
        provider_id="sentinel-prov",
        display_name="Sentinel",
        surfaces={"renderer": "flat-skill"},
    )
    _register_standard_surfaces(descriptor)
    assert load_renderer_registry()["sentinel-prov"] is sentinel
