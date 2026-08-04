from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.project import project_surfaces
from audiagentic.components.providers.surfaces.contributions import load_surface_contributions
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.lifecycle.fresh_install import apply_fresh_install


def test_project_instruction_crud_is_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_surfaces, "_reconcile", lambda _root: None)
    created = project_surfaces.create_project_instruction(
        tmp_path, "team-rules", "Team rules", "Use the project conventions."
    )
    assert created["id"] == "team-rules"
    assert project_surfaces.list_project_instructions(tmp_path)[0]["title"] == "Team rules"
    project_surfaces.update_project_instruction(tmp_path, "team-rules", body="Updated.")
    assert project_surfaces.get_project_instruction(tmp_path, "team-rules")["content"]["body"] == "Updated."
    project_surfaces.delete_project_instruction(tmp_path, "team-rules")
    assert project_surfaces.list_project_instructions(tmp_path) == []


def test_project_skill_crud_is_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_surfaces, "_reconcile", lambda _root: None)
    content = "---\nname: team-rules\ndescription: Team rules\n---\n\n# Team rules\n\nTrigger:\n- when relevant\n\nDo:\n- follow the rules\n\nDo not:\n- ignore them\n"
    project_surfaces.create_project_skill(tmp_path, "team-rules", content)
    assert project_surfaces.get_project_skill(tmp_path, "team-rules")["content"] == content
    assert project_surfaces.list_project_skills(tmp_path)[0]["id"] == "team-rules"
    project_surfaces.delete_project_skill(tmp_path, "team-rules")
    assert project_surfaces.list_project_skills(tmp_path) == []


def test_project_instruction_is_loaded_as_provider_contribution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_surfaces, "_reconcile", lambda _root: None)
    project_surfaces.create_project_instruction(tmp_path, "local", "Local instructions", "Only for this project.")
    ids = {item.contribution_id for item in load_surface_contributions(tmp_path)}
    assert "project/instruction/local" in ids


def test_fresh_project_can_create_project_surfaces(tmp_path: Path) -> None:
    """Project-owned mutations do not require optional components to be installed."""
    register_all_components()
    apply_fresh_install(tmp_path)
    project_surfaces.create_project_instruction(tmp_path, "local", "Local", "Only here.")
    project_surfaces.create_project_skill(
        tmp_path,
        "local",
        "---\nname: local\ndescription: Local skill\n---\n\n# Local\n\n"
        "Trigger:\n- local work\n\nDo:\n- follow local guidance\n\nDo not:\n- ignore it\n",
    )
    assert project_surfaces.list_project_instructions(tmp_path)[0]["id"] == "local"
    assert project_surfaces.list_project_skills(tmp_path)[0]["id"] == "local"
