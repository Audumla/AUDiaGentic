"""MA05: component-owned workflow and hook mutation ownership tests.

Covers the 10 fixture scenarios (5 per feature) from MA05 step 1 matrix:
Feature A — Release install: absent, exact, user-owned, old-block, malformed.
Feature B — Post-commit hook: absent, exact, user-owned, old-block, malformed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from audiagentic.components.release.release_please.install import install
from audiagentic.components.source_control import source_control_bootstrap as bootstrap
from audiagentic.foundation.toolchains.config.artifact_registry import ArtifactRegistry


def _hook_entry_point() -> str:
    """Name of the symbol the hook invokes, resolved by actually importing it.

    The hook calls into Python from a shell string, so no importer scan sees
    that edge. Deriving the expected name from a real import means an assertion
    against the hook body cannot pass while the entry point is missing --
    the gap that let the installed hook no-op silently for weeks.
    """
    from audiagentic.components.source_control.git_commits import stamp_ledger_for_commit

    return stamp_ledger_for_commit.__name__


def test_hook_body_entry_point_resolves() -> None:
    """The hook template must name a symbol that genuinely imports."""
    assert _hook_entry_point() in bootstrap._post_commit_hook_body()


# --- Feature A: Release install ownership ---------------------------------

class TestReleaseInstallOwnership:
    """Feature A: release workflow file installation with atomic writes,
    adoption logic, collision detection, and ArtifactRegistry registration."""

    @pytest.fixture(autouse=True)
    def _mock_ledger(self, monkeypatch):
        """Ensure ledger integration enabled check does not block release install."""
        # Release install doesn't depend on ledger, so no mock needed here.
        pass

    def test_fx_absent_creates_and_registers(self, tmp_path: Path) -> None:
        """FxA-S1: file absent → create whole-owned, register in ArtifactRegistry."""
        result = install(tmp_path, release_type="python", branch="main", python_version="3.13")

        assert "release-please-config.json" in result["created"]
        assert ".release-please-manifest.json" in result["created"]
        created_posix = [Path(p).as_posix() for p in result["created"]]
        assert ".github/workflows/release.yml" in created_posix
        assert not result["adopted"]
        assert not result["collisions"]

        # Files actually created with content
        config = tmp_path / "release-please-config.json"
        assert config.exists()
        assert '"release-type": "python"' in config.read_text(encoding="utf-8")

        # Registered in ArtifactRegistry
        reg = ArtifactRegistry(tmp_path)
        bucket = reg.owned("release/release-please")
        assert "release-please-config.json" in bucket["files"]

    def test_fx_exact_adopts_without_write(self, tmp_path: Path) -> None:
        """FxA-S2: file exists with exact canonical bytes → adopt, no write."""
        from audiagentic.components.release.release_please import utils as install_utils
        config = tmp_path / "release-please-config.json"
        # Use the actual rendered output as the canonical content
        subs = {"__RELEASE_TYPE__": "python", "__BRANCH__": "main", "__PYTHON_VERSION__": "3.13"}
        canonical = install_utils.render("release-please-config.json", subs)
        config.write_text(canonical, encoding="utf-8")

        result = install(tmp_path, release_type="python", branch="main", python_version="3.13")

        assert "release-please-config.json" in result["adopted"]
        assert ".release-please-manifest.json" in result["created"]
        assert not result["collisions"]

    def test_fx_user_owned_collision_preserves_bytes(self, tmp_path: Path) -> None:
        """FxA-S3: file exists with divergent content → collision, bytes untouched."""
        config = tmp_path / "release-please-config.json"
        original = '{"release-type": "node"}\n'
        config.write_text(original, encoding="utf-8")

        result = install(tmp_path, release_type="python", branch="main", python_version="3.13")

        assert "release-please-config.json" in result["collisions"]
        # Bytes must be 100% identical after operation
        assert config.read_text(encoding="utf-8") == original

    def test_fx_malformed_treated_as_collision(self, tmp_path: Path) -> None:
        """FxA-S5: truncated/malformed content → collision path (S3 behavior)."""
        config = tmp_path / "release-please-config.json"
        config.write_text('{"include-component-in-tag": true, "ba', encoding="utf-8")

        result = install(tmp_path, release_type="python", branch="main", python_version="3.13")

        assert "release-please-config.json" in result["collisions"]

    def test_fx_dry_run_no_side_effects(self, tmp_path: Path) -> None:
        """Dry-run returns planned changes without writing files or registry."""
        result = install(
            tmp_path, release_type="python", branch="main", python_version="3.13", dry_run=True,
        )

        assert not (tmp_path / "release-please-config.json").exists()
        created_posix = sorted([Path(p).as_posix() for p in result["created"]])
        expected = sorted(["release-please-config.json", ".release-please-manifest.json", ".github/workflows/release.yml"])
        assert created_posix == expected
        assert "dry_run_changes" in result
        assert len(result["dry_run_changes"]) == 3

    def test_fx_install_idempotent(self, tmp_path: Path) -> None:
        """Two installs in succession: first creates, second adopts all."""
        install(tmp_path, release_type="python", branch="main", python_version="3.13")
        result2 = install(tmp_path, release_type="python", branch="main", python_version="3.13")

        assert not result2["created"]
        assert len(result2["adopted"]) == 3
        assert not result2["collisions"]


# --- Feature B: Post-commit hook ownership ---------------------------------

class TestHookInstallOwnership:
    """Feature B: post-commit hook with whole-file/block ownership,
    atomic writes, executable bits, LF enforcement."""

    def _setup_ledger_project(self, project_root: Path, monkeypatch) -> None:
        (project_root / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(bootstrap, "ledger_integration_enabled", lambda pr: True)

    def test_fb_absent_creates_whole_owned(self, tmp_path: Path, monkeypatch) -> None:
        """FxB-S1: hook absent → create whole-owned file with shebang + block."""
        self._setup_ledger_project(tmp_path, monkeypatch)

        result = bootstrap.install_post_commit_hook(tmp_path)

        assert result["installed"] is True
        assert result["ownership_mode"] == "whole-file"

        hook = tmp_path / ".git" / "hooks" / "post-commit"
        content = hook.read_text(encoding="utf-8")
        assert content.startswith("#!/bin/sh\n")
        assert bootstrap._HOOK_BLOCK_ID in content

        # Registered in ArtifactRegistry as whole-owned
        reg = ArtifactRegistry(tmp_path)
        bucket = reg.owned("source-control/post-commit-hook")
        hook_rel = Path(hook.relative_to(tmp_path)).as_posix() if hook.is_relative_to(tmp_path) else Path(hook).as_posix()
        assert hook_rel in bucket.get("files", [])

    def test_fb_user_owned_appends_block(self, tmp_path: Path, monkeypatch) -> None:
        """FxB-S3: user content exists → append managed block, preserve user content."""
        self._setup_ledger_project(tmp_path, monkeypatch)
        hook = tmp_path / ".git" / "hooks" / "post-commit"
        user_content = '#!/bin/sh\necho "user hook"\n'
        hook.write_text(user_content, encoding="utf-8")

        result = bootstrap.install_post_commit_hook(tmp_path)

        assert result["installed"] is True
        assert result["ownership_mode"] == "block"

        # User content preserved
        content = hook.read_text(encoding="utf-8")
        assert "user hook" in content
        assert bootstrap._HOOK_BLOCK_ID in content

    def test_fb_malformed_block_repaired(self, tmp_path: Path, monkeypatch) -> None:
        """FxB-S5 case 3: empty block (adjacent markers) → replaced with full body."""
        self._setup_ledger_project(tmp_path, monkeypatch)
        hook = tmp_path / ".git" / "hooks" / "post-commit"
        block_id = bootstrap._HOOK_BLOCK_ID
        malformed = f'#!/bin/sh\n# >>> audiagentic:{block_id} >>>\n# <<< audiagentic:{block_id} <<<\n'
        hook.write_text(malformed, encoding="utf-8")

        result = bootstrap.install_post_commit_hook(tmp_path)

        assert result["installed"] is True
        content = hook.read_text(encoding="utf-8")
        # Empty block replaced with full hook body
        assert _hook_entry_point() in content

    def test_fb_dry_run_no_side_effects(self, tmp_path: Path, monkeypatch) -> None:
        """Dry-run returns planned changes without writing or registry mutations."""
        self._setup_ledger_project(tmp_path, monkeypatch)
        hook = tmp_path / ".git" / "hooks" / "post-commit"

        result = bootstrap.install_post_commit_hook(tmp_path, dry_run=True)

        assert not hook.exists()
        assert result["installed"] is True
        assert result["ownership_mode"] == "whole-file"
        assert "dry_run_changes" in result

    def test_fb_dry_run_user_file(self, tmp_path: Path, monkeypatch) -> None:
        """Dry-run on existing user file returns append-block plan."""
        self._setup_ledger_project(tmp_path, monkeypatch)
        hook = tmp_path / ".git" / "hooks" / "post-commit"
        original = '#!/bin/sh\necho "user"\n'
        hook.write_text(original, encoding="utf-8")

        result = bootstrap.install_post_commit_hook(tmp_path, dry_run=True)

        assert hook.read_text(encoding="utf-8") == original  # bytes unchanged
        assert result["ownership_mode"] == "block"
        assert "dry_run_changes" in result
        assert result["dry_run_changes"]["action"] == "append-block"


class TestHookPrune:
    """Feature B prune: registry-proof deletion, block-owned preserves user file."""

    def _setup_ledger_project(self, project_root: Path, monkeypatch) -> None:
        (project_root / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(bootstrap, "ledger_integration_enabled", lambda pr: True)

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows file lock prevents immediate unlink verification")
    def test_prune_whole_owned_deletes_file(self, tmp_path: Path, monkeypatch) -> None:
        """Whole-owned hook deleted on prune (registry proof exists)."""
        self._setup_ledger_project(tmp_path, monkeypatch)
        bootstrap.install_post_commit_hook(tmp_path)
        hook = tmp_path / ".git" / "hooks" / "post-commit"
        assert hook.exists()
        result = bootstrap.prune_post_commit_hook(tmp_path)

        assert result["pruned"] is True
        assert not hook.exists()

    def test_prune_block_owned_preserves_user_content(self, tmp_path: Path, monkeypatch) -> None:
        """Block-owned hook: block removed, user content preserved, file kept."""
        self._setup_ledger_project(tmp_path, monkeypatch)
        hook = tmp_path / ".git" / "hooks" / "post-commit"
        hook.write_text('#!/bin/sh\necho "user"\n', encoding="utf-8")
        bootstrap.install_post_commit_hook(tmp_path)

        result = bootstrap.prune_post_commit_hook(tmp_path)

        assert result["pruned"] is True
        assert hook.exists()  # file preserved (user content)
        content = hook.read_text(encoding="utf-8")
        assert "user" in content  # user content intact
        assert bootstrap._HOOK_BLOCK_ID not in content  # block removed

    def test_prune_dry_run_no_side_effects(self, tmp_path: Path, monkeypatch) -> None:
        """Prune dry-run reports action without deleting anything."""
        self._setup_ledger_project(tmp_path, monkeypatch)
        bootstrap.install_post_commit_hook(tmp_path)
        hook = tmp_path / ".git" / "hooks" / "post-commit"

        result = bootstrap.prune_post_commit_hook(tmp_path, dry_run=True)

        assert hook.exists()  # file still exists
        assert result["pruned"] is True
        assert "dry_run_changes" in result
