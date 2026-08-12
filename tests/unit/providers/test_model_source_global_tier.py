"""AS105/AS101 pivot -- user-global model-sources tier and resolved view.

Capacity (concurrency, resource-id) for shared local-endpoint hardware lives
in the existing model-sources.yaml contract, layered at user-global +
project-local tiers, rather than in a separate agents-owned taxonomy. These
tests prove the tier stays isolated (no duplication into project files) and
that resolution actually merges both tiers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.services.config.model_source_config import (
    load_model_sources,
    load_resolved_model_sources,
    load_user_global_model_sources,
    user_global_model_sources_path,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture()
def audiagentic_home_dir(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(home))
    return home


def _local_gpu(**overrides) -> dict:
    base = {
        "source-class": "local-endpoint",
        "display-name": "Local GPU 0",
        "connector": "openai-compatible",
        "base-url": "http://127.0.0.1:8000/v1",
        "api-key-ref": "env:LOCAL_KEY",
        "model-id": "m27b1",
        "context-window": 131072,
        "max-output-tokens": 4096,
        "capabilities": {"tool-use": True, "reasoning": False, "vision": False},
        "resource-id": "local-gpu-0",
        "concurrency": 4,
    }
    base.update(overrides)
    return base


def _local_endpoint_without_capacity(**overrides) -> dict:
    base = _local_gpu()
    del base["resource-id"]
    del base["concurrency"]
    base.update(overrides)
    return base


def test_missing_user_global_file_returns_empty_v1_document(audiagentic_home_dir: Path) -> None:
    assert load_user_global_model_sources() == {"contract-version": "v1", "sources": {}}


def test_add_global_writes_user_global_file_only(
    audiagentic_home_dir: Path, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    result = providers_api.model_source_add_global("m27b1", _local_gpu())
    assert result["ok"] is True

    assert user_global_model_sources_path().exists()
    assert "m27b1" in load_user_global_model_sources()["sources"]
    # Project-local file must not exist -- nothing was written there.
    assert load_model_sources(project_root) == {"contract-version": "v1", "sources": {}}


def test_add_global_rejects_duplicate(audiagentic_home_dir: Path) -> None:
    providers_api.model_source_add_global("m27b1", _local_gpu())
    with pytest.raises(AudiaGenticError) as exc:
        providers_api.model_source_add_global("m27b1", _local_gpu())
    assert "already exists" in str(exc.value.message).lower()


def test_update_global_modifies_existing_source(audiagentic_home_dir: Path) -> None:
    providers_api.model_source_add_global("m27b1", _local_gpu())
    result = providers_api.model_source_update_global("m27b1", {"concurrency": 8})
    assert result["ok"] is True
    updated = load_user_global_model_sources()["sources"]["m27b1"]
    assert updated["concurrency"] == 8


def test_update_global_unknown_source_raises(audiagentic_home_dir: Path) -> None:
    with pytest.raises(AudiaGenticError):
        providers_api.model_source_update_global("nope", {"concurrency": 8})


def test_remove_global_deletes_source(audiagentic_home_dir: Path) -> None:
    providers_api.model_source_add_global("m27b1", _local_gpu())
    providers_api.model_source_remove_global("m27b1")
    assert load_user_global_model_sources()["sources"] == {}


def test_set_enabled_global_toggles_flag(audiagentic_home_dir: Path) -> None:
    providers_api.model_source_add_global("m27b1", _local_gpu())
    providers_api.model_source_set_enabled_global("m27b1", False)
    assert load_user_global_model_sources()["sources"]["m27b1"]["enabled"] is False


def test_list_global_summarizes_capacity_fields(audiagentic_home_dir: Path) -> None:
    providers_api.model_source_add_global("m27b1", _local_gpu())
    result = providers_api.model_source_list_global()
    assert result["sources"]["m27b1"]["resource-id"] == "local-gpu-0"
    assert result["sources"]["m27b1"]["concurrency"] == 4


def test_resolved_view_merges_global_and_project_local_sources(
    audiagentic_home_dir: Path, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    providers_api.model_source_add_global("m27b1", _local_gpu())
    providers_api.model_source_add(
        project_root,
        "project-only",
        _local_endpoint_without_capacity(**{"model-id": "project-model"}),
    )

    resolved = load_resolved_model_sources(project_root)["sources"]
    assert "m27b1" in resolved
    assert "project-only" in resolved

    # Project-local file must contain only its own source -- the global
    # source was never copied in by the resolution/read path.
    project_local = load_model_sources(project_root)["sources"]
    assert set(project_local) == {"project-only"}


def test_resolved_view_visible_from_every_project_without_duplication(
    audiagentic_home_dir: Path, tmp_path: Path
) -> None:
    """A shared GPU declared once is visible to two unrelated projects,
    and neither project's own model-sources.yaml is ever written to."""
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()

    providers_api.model_source_add_global("m27b1", _local_gpu())
    providers_api.model_source_add_global(
        "m27b2", _local_gpu(**{"resource-id": "local-gpu-1"})
    )

    for project_root in (project_a, project_b):
        resolved = load_resolved_model_sources(project_root)["sources"]
        assert set(resolved) == {"m27b1", "m27b2"}
        assert load_model_sources(project_root) == {"contract-version": "v1", "sources": {}}


def test_project_local_mutation_never_copies_inherited_global_sources(
    audiagentic_home_dir: Path, tmp_path: Path
) -> None:
    """Mutating a project's own sources (read-modify-write via
    model_source_add) must not round-trip the merged/resolved view --
    only the project's own declarations may land in its file."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    providers_api.model_source_add_global("m27b1", _local_gpu())
    providers_api.model_source_add(
        project_root,
        "project-only",
        _local_endpoint_without_capacity(**{"model-id": "project-model"}),
    )

    project_local = load_model_sources(project_root)["sources"]
    assert "m27b1" not in project_local
    assert set(project_local) == {"project-only"}


def test_model_source_list_resolved_api_summarizes_merged_sources(
    audiagentic_home_dir: Path, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    providers_api.model_source_add_global("m27b1", _local_gpu())
    result = providers_api.model_source_list_resolved(project_root)
    assert result["ok"] is True
    assert result["sources"]["m27b1"]["concurrency"] == 4
