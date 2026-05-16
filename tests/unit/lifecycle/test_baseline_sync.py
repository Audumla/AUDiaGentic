from __future__ import annotations

from pathlib import Path

from audiagentic.runtime.lifecycle.baseline_sync import sync_managed_baseline


def test_sync_managed_baseline_copies_managed_assets_and_excludes_runtime(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()

    report = sync_managed_baseline(target)

    assert ".audiagentic/config/project.yaml" in report["created-files"]
    assert ".audiagentic/prompts/ag-review/default.md" in report["created-files"]
    assert "AGENTS.md" in report["created-files"]
    assert ".github/workflows/release.yml" in report["created-files"]
    assert any("runtime" in p for p in report["excluded-paths"])
    assert (target / ".audiagentic" / "runtime").exists() is False
    assert (target / "docs" / "releases" / "CURRENT_RELEASE.md").exists() is False


def test_sync_managed_baseline_copies_skill_sources(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()

    report = sync_managed_baseline(target)

    created = report["created-files"]
    assert any(p.startswith(".audiagentic/skills/") for p in created), (
        "agent-jobs skill sources must be synced by baseline sync"
    )
    assert (target / ".audiagentic" / "skills" / "ag-plan" / "skill.md").exists()
    assert (target / ".audiagentic" / "skills" / "ag-implement" / "skill.md").exists()
    assert (target / ".audiagentic" / "skills" / "ag-review" / "skill.md").exists()
    assert (target / ".audiagentic" / "skills" / "ag-audit" / "skill.md").exists()
    assert (target / ".audiagentic" / "skills" / "ag-check-in-prep" / "skill.md").exists()


def test_sync_managed_baseline_preserves_create_if_missing_files(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir(parents=True)
    (target / ".audiagentic" / "config" / "runtime").mkdir(parents=True)
    provider_path = target / ".audiagentic" / "config" / "runtime" / "providers.yaml"
    provider_path.write_text("contract-version: v1\nproviders:\n  custom: {}\n", encoding="utf-8")

    report = sync_managed_baseline(target)

    assert ".audiagentic/config/runtime/providers.yaml" in report["preserved-files"]
    assert "custom" in provider_path.read_text(encoding="utf-8")
