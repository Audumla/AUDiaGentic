from __future__ import annotations

from pathlib import Path

from audiagentic.components.release.release_please.manage import _render_baseline


def test_packaged_release_workflow_asset_matches_default_baseline() -> None:
    root = Path(__file__).resolve().parents[3]
    asset = root / "src" / "audiagentic" / "config" / "components" / "release" / ".github" / "workflows" / "release.yml"

    assert asset.read_text(encoding="utf-8") == _render_baseline()


def test_release_finalization_uses_normal_pr_and_exact_merged_source() -> None:
    import yaml

    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    finalizer = workflow["jobs"]["finalize-ledger"]
    assert finalizer["permissions"]["pull-requests"] == "write"
    step = next(step for step in finalizer["steps"] if step.get("name") == "Commit release artifacts")
    script = step["run"]
    assert 'git push --set-upstream origin "$branch"' in script
    assert "gh pr create" in script
    assert 'gh pr merge "$pr" --merge --match-head-commit "$finalized_head"' in script
    assert 'git checkout --detach "$merged_sha"' in script
    assert "--admin" not in script
    assert "--force" not in script
    assert "\n          git push\n" not in script
