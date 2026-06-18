"""Unit tests: generated skill files follow their owning component's lifecycle.

Generated per-tag skill files (provider ``skill_surface_path``) are whole managed
files, not fenced regions, so the region-rewrite prune could never remove them.
These tests guard the generic fix: a tag whose owning component is disabled or
uninstalled is inactive, its skill files are deleted by prune, and skill
generation refuses to regenerate them.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.optional.providers import skill_surfaces
from audiagentic.components.optional.providers.descriptors.registry import all_descriptors
from audiagentic.components.optional.providers.surfaces import contributions, manager


def _skill_paths_for_tag(project_root: Path, tag_id: str) -> list[Path]:
    """Every provider skill-surface file for a tag, from the real descriptors."""
    paths: list[Path] = []
    for descriptor in all_descriptors().values():
        if descriptor.skill_surface_path:
            paths.append(project_root / descriptor.skill_surface_path.format(tag=tag_id))
    return paths


# ── active_tag_ids ────────────────────────────────────────────────────────────

def test_active_tag_ids_none_returns_all_loaded() -> None:
    from audiagentic.components.optional.providers.tags.registry import all_tags_loaded

    assert contributions.active_tag_ids(None) == set(all_tags_loaded())


def test_active_tag_ids_filters_by_owner_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from audiagentic.components.optional.providers.tags.base import ActionDescriptor

    def _tag(tag_id: str, owner: str) -> ActionDescriptor:
        return ActionDescriptor(
            tag_id=tag_id,
            display_name=tag_id,
            description="",
            skill_content_file="skill.md",
            config_dir=Path("."),
            owner_component_id=owner,
        )

    fake_tags = {
        "tag-on": _tag("tag-on", "comp-on"),
        "tag-off": _tag("tag-off", "comp-off"),
        "tag-noowner": _tag("tag-noowner", ""),
    }
    monkeypatch.setattr(
        "audiagentic.components.optional.providers.tags.registry.all_tags_loaded",
        lambda: fake_tags,
    )
    monkeypatch.setattr(
        "audiagentic.foundation.components.registry.is_installed",
        lambda cid, root: True,
    )
    monkeypatch.setattr(
        "audiagentic.foundation.components.registry.is_enabled",
        lambda cid, root: cid == "comp-on",
    )

    active = contributions.active_tag_ids(Path("/tmp/project"))
    # Enabled owner active; disabled owner excluded; unknown owner treated active.
    assert active == {"tag-on", "tag-noowner"}


# ── prune deletes orphaned skill files ─────────────────────────────────────────

def test_prune_deletes_inactive_tag_skill_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tag_id = "ag-implement"
    skill_paths = _skill_paths_for_tag(tmp_path, tag_id)
    assert skill_paths, "expected at least one provider with a skill_surface_path"
    for path in skill_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<!-- MANAGED_BY_AUDIAGENTIC -->\n# stale skill\n", encoding="utf-8")

    # Force every tag inactive (owning component disabled/uninstalled).
    monkeypatch.setattr(contributions, "active_tag_ids", lambda project_root=None: set())

    result = manager.prune_provider_surfaces(tmp_path)

    for path in skill_paths:
        assert not path.exists(), f"{path} should have been deleted"
        assert str(path) in result["deleted"]
    # Per-tag directories (e.g. .claude/skills/<tag>/) are cleaned up when emptied.
    for path in skill_paths:
        if path.parent.name == tag_id:
            assert not path.parent.exists(), f"empty dir {path.parent} should be removed"


def test_prune_keeps_active_tag_skill_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tag_id = "ag-implement"
    skill_paths = _skill_paths_for_tag(tmp_path, tag_id)
    for path in skill_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<!-- MANAGED_BY_AUDIAGENTIC -->\n# active skill\n", encoding="utf-8")

    # Tag is active → its skill files must survive prune.
    monkeypatch.setattr(contributions, "active_tag_ids", lambda project_root=None: {tag_id})

    result = manager.prune_provider_surfaces(tmp_path)

    for path in skill_paths:
        assert path.exists(), f"{path} should have been kept"
        assert str(path) not in result["deleted"]


# ── generation refuses to regenerate inactive skills ───────────────────────────

def test_skill_generation_skips_inactive_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "audiagentic.components.optional.providers.surfaces.contributions.active_tag_ids",
        lambda project_root=None: set(),
    )
    skills = skill_surfaces._load_skills_from_registry(Path("/tmp/project"))
    assert skills == []
