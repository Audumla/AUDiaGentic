from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.lifecycle.baseline_sync import sync_managed_baseline


def test_sync_managed_baseline_copies_managed_assets_and_excludes_runtime(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()

    report = sync_managed_baseline(target)

    assert ".audiagentic/config/project.yaml" in report["created-files"]
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
    assert (target / ".audiagentic" / "skills" / "ag-ledger" / "skill.md").exists()
    assert (target / ".audiagentic" / "skills" / "ag-check-in-prep" / "skill.md").exists()


def test_sync_managed_baseline_preserves_create_if_missing_files(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir(parents=True)
    (target / ".audiagentic" / "config" / "providers").mkdir(parents=True)
    provider_path = target / ".audiagentic" / "config" / "providers" / "custom.yaml"
    provider_path.write_text("install-mode: external-configured\naccess-mode: none\n", encoding="utf-8")

    report = sync_managed_baseline(target)

    assert ".audiagentic/config/providers" in report["preserved-files"]
    assert "access-mode: none" in provider_path.read_text(encoding="utf-8")
