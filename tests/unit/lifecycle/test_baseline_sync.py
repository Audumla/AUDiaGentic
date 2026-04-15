from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.runtime.lifecycle.baseline_sync import sync_managed_baseline


def test_sync_managed_baseline_copies_managed_assets_and_excludes_runtime(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()

    report = sync_managed_baseline(target)

    assert ".audiagentic/project.yaml" in report["created-files"]
    assert ".audiagentic/prompts/ag-review/default.md" in report["created-files"]
    assert "AGENTS.md" in report["created-files"]
    assert ".github/workflows/release-please.audiagentic.yml" in report["created-files"]
    assert ".audiagentic/runtime/**" in report["excluded-paths"]
    assert (target / ".audiagentic" / "runtime").exists() is False
    assert (target / "docs" / "releases" / "CURRENT_RELEASE.md").exists() is False


def test_sync_managed_baseline_preserves_create_if_missing_files(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir(parents=True)
    (target / ".audiagentic").mkdir(parents=True)
    provider_path = target / ".audiagentic" / "providers.yaml"
    provider_path.write_text("contract-version: v1\nproviders:\n  custom: {}\n", encoding="utf-8")

    report = sync_managed_baseline(target)

    assert ".audiagentic/providers.yaml" in report["preserved-files"]
    assert "custom" in provider_path.read_text(encoding="utf-8")
