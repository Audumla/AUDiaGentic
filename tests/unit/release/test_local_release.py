"""Tests for local_release module."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audiagentic.components.release.local_release import (
    _archive_ledger_locally,
    _create_git_tag,
    _create_github_release,
    _get_current_version,
    _publish_pypi,
    _run_build,
)


@pytest.fixture
def project_with_manifest(tmp_path: Path) -> Path:
    """Create a temp project with .release-please-manifest.json."""
    manifest = tmp_path / ".release-please-manifest.json"
    manifest.write_text(json.dumps({".": "0.1.1"}) + "\n")
    return tmp_path


@pytest.fixture
def project_with_ledger(tmp_path: Path) -> Path:
    """Create a temp project with manifest and ledger files."""
    manifest = tmp_path / ".release-please-manifest.json"
    manifest.write_text(json.dumps({".": "0.1.1"}) + "\n")

    releases_dir = tmp_path / "docs" / "releases"
    releases_dir.mkdir(parents=True)

    ledger = releases_dir / "CURRENT_RELEASE_LEDGER.ndjson"
    ledger.write_text(
        json.dumps({
            "event-id": "evt_001",
            "technical-summary": "added feature",
            "user-summary-candidate": "Added a new feature",
        }) + "\n"
    )
    return tmp_path


class TestGetCurrentVersion:
    def test_reads_version_from_manifest(self, project_with_manifest):
        version = _get_current_version(project_with_manifest)
        assert version == "0.1.1"

    def test_raises_when_manifest_missing(self, tmp_path):
        with pytest.raises(Exception):
            _get_current_version(tmp_path)


class TestArchiveLedgerLocally:
    def test_archives_current_to_historical(self, project_with_ledger):
        result = _archive_ledger_locally(project_with_ledger, "rel_0001")

        assert result["release-id"] == "rel_0001"
        assert result["archived-events"] == 1
        assert result["cleared-current"] is True

        historical = project_with_ledger / "docs" / "releases" / "LEDGER.ndjson"
        assert historical.exists()

        current = project_with_ledger / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
        current_data = json.loads(current.read_text())
        assert current_data == []

    def test_appends_to_existing_historical(self, project_with_ledger):
        historical = project_with_ledger / "docs" / "releases" / "LEDGER.ndjson"
        historical.write_text(
            json.dumps({"event-id": "evt_old", "technical-summary": "old event"}) + "\n"
        )

        result = _archive_ledger_locally(project_with_ledger, "rel_0002")

        assert result["archived-events"] == 1

        stored_lines = [line for line in historical.read_text().splitlines() if line.strip()]
        assert len(stored_lines) == 2
        stored = [json.loads(line) for line in stored_lines]
        assert stored[0]["event-id"] == "evt_old"
        assert stored[1]["event-id"] == "evt_001"

    def test_raises_when_current_ledger_missing(self, tmp_path):
        releases = tmp_path / "docs" / "releases"
        releases.mkdir(parents=True)

        with pytest.raises(Exception):
            _archive_ledger_locally(tmp_path, "rel_0001")


class TestRunBuild:
    def test_returns_artifacts_on_success(self, project_with_manifest, tmp_path):
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "test-0.1.1-py3-none-any.whl").write_text("fake wheel")
        (dist_dir / "test-0.1.1.tar.gz").write_text("fake sdist")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = _run_build(project_with_manifest)

        assert result["success"] is True
        assert result["dist-dir"] == "dist"

    def test_raises_on_build_failure(self, project_with_manifest):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="build failed")
            with pytest.raises(Exception):
                _run_build(project_with_manifest)


class TestCreateGitTag:
    def test_creates_and_pushes_tag(self, project_with_manifest):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = _create_git_tag(project_with_manifest, "v0.1.1", "rel_0001")

        assert result["created"] is True
        assert result["pushed"] is True
        assert result["tag"] == "v0.1.1"

    def test_returns_error_on_failure(self, project_with_manifest):
        import subprocess as sp

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = sp.CalledProcessError(1, "git", stderr="tag exists")
            result = _create_git_tag(project_with_manifest, "v0.1.1", "rel_0001")

        assert result["created"] is False
        assert "tag exists" in result["error"]


class TestPublishPyPI:
    def test_publishes_with_token_from_env(self, project_with_manifest):
        with patch("subprocess.run") as mock_run, patch.dict(
            "os.environ", {"TWINE_PASSWORD": "fake-token"}
        ):
            dist_dir = project_with_manifest / "dist"
            dist_dir.mkdir()
            (dist_dir / "test-0.1.1-py3-none-any.whl").write_text("fake")

            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = _publish_pypi(project_with_manifest, interactive=False)

        assert result["published"] is True

    def test_returns_no_token_when_missing(self, project_with_manifest):
        with patch.dict("os.environ", {}, clear=True):
            result = _publish_pypi(project_with_manifest, interactive=False)

        assert result["published"] is False
        assert "no token" in result["reason"]


class TestCreateGithubRelease:
    def test_uploads_to_github_release(self, project_with_manifest, tmp_path):
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "test-0.1.1-py3-none-any.whl").write_text("fake")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = _create_github_release(project_with_manifest, "v0.1.1")

        assert result["created"] is True
        assert result["tag"] == "v0.1.1"

    def test_returns_reason_when_gh_not_found(self, project_with_manifest):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = _create_github_release(project_with_manifest, "v0.1.1")

        assert result["created"] is False
        assert "gh CLI not found" in result["reason"]
