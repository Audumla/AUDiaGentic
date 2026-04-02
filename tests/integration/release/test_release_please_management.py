from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.runtime.release.release_please import (
    BASELINE_WORKFLOW,
    CANDIDATE_NAME,
    LEGACY_NAME,
    LEGACY_SUFFIX,
    MANAGED_NAME,
    ensure_release_please_baseline,
)
from tests.helpers import sandbox as sandbox_helper


def test_release_please_absent_installs_baseline(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "rp-absent")
    try:
        result = ensure_release_please_baseline(sandbox.repo)
        managed = sandbox.repo / ".github" / "workflows" / MANAGED_NAME
        assert managed.is_file()
        assert managed.read_text(encoding="utf-8") == BASELINE_WORKFLOW
        assert result["warnings"] == []
    finally:
        sandbox.cleanup()


def test_release_please_legacy_renamed(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "rp-legacy")
    try:
        workflow_dir = sandbox.repo / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        legacy = workflow_dir / LEGACY_NAME
        legacy.write_text("legacy", encoding="utf-8")

        result = ensure_release_please_baseline(sandbox.repo)
        assert (workflow_dir / LEGACY_SUFFIX).is_file()
        assert (workflow_dir / MANAGED_NAME).is_file()
        assert result["warnings"]
    finally:
        sandbox.cleanup()


def test_release_please_managed_modified_preserved(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "rp-modified")
    try:
        workflow_dir = sandbox.repo / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        managed = workflow_dir / MANAGED_NAME
        managed.write_text("custom", encoding="utf-8")

        result = ensure_release_please_baseline(sandbox.repo)
        assert managed.read_text(encoding="utf-8") == "custom"
        assert (workflow_dir / CANDIDATE_NAME).is_file()
        assert result["warnings"]
    finally:
        sandbox.cleanup()


def test_release_please_managed_unmodified_refresh(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "rp-unmodified")
    try:
        workflow_dir = sandbox.repo / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        managed = workflow_dir / MANAGED_NAME
        managed.write_text(BASELINE_WORKFLOW, encoding="utf-8")

        result = ensure_release_please_baseline(sandbox.repo)
        assert managed.read_text(encoding="utf-8") == BASELINE_WORKFLOW
        assert result["warnings"] == []
    finally:
        sandbox.cleanup()


def test_release_please_external_unknown(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "rp-external")
    try:
        workflow_dir = sandbox.repo / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "release-please.custom.yml").write_text("custom", encoding="utf-8")
        result = ensure_release_please_baseline(sandbox.repo)
        assert (workflow_dir / CANDIDATE_NAME).is_file()
        assert result["warnings"]
    finally:
        sandbox.cleanup()
